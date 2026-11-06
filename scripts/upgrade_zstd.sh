#!/usr/bin/env bash
# 把内核树里的 lib/zstd 从 1.4.10 升级到 zstd 1.5.x（取自指定内核版本，默认 v6.6）。
#
# 只替换「zstd 库本体 + 公开头文件 + crypto/zstd.c 适配层」，
# 不动任何导出结构体，因此不影响 vendor 模块的 CRC。
# f2fs / squashfs 这两处直接调用私有 API 的代码由 configs/zstd-upgrade.config 关闭。
set -euo pipefail

KERNEL_DIR=${1:?用法: upgrade_zstd.sh <kernel_dir>}
KERNEL_DIR=$(cd "$KERNEL_DIR" && pwd)
ZSTD_TAG=${ZSTD_TAG:-v6.6}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "==> 下载 linux ${ZSTD_TAG} 源码包"
curl -L --retry 3 --retry-delay 5 -o "$WORK/linux.tar.gz" \
  "https://codeload.github.com/torvalds/linux/tar.gz/refs/tags/${ZSTD_TAG}"

echo "==> 解出 lib/zstd、include/linux/zstd*.h、crypto/zstd.c"
tar -C "$WORK" -xzf "$WORK/linux.tar.gz" \
  --wildcards 'linux-*/lib/zstd/*' 'linux-*/include/linux/zstd*.h' 'linux-*/crypto/zstd.c' \
  --no-same-owner

SRC_DIR=$(ls -d "$WORK"/linux-*/lib/zstd | head -1)
SRC_ROOT=$(dirname "$(dirname "$SRC_DIR")")

echo "==> 备份原有 lib/zstd"
if [ -d "$KERNEL_DIR/lib/zstd" ]; then
  rm -rf "$KERNEL_DIR/lib/zstd.orig"
  cp -a "$KERNEL_DIR/lib/zstd" "$KERNEL_DIR/lib/zstd.orig"
fi

echo "==> 替换 lib/zstd"
rm -rf "$KERNEL_DIR/lib/zstd"
cp -a "$SRC_DIR" "$KERNEL_DIR/lib/zstd"
find "$KERNEL_DIR/lib/zstd" -name '*.sh' -delete

echo "==> 同步 include/linux/zstd*.h"
shopt -s nullglob
hdr_count=0
for h in "$SRC_ROOT"/include/linux/zstd*.h; do
  cp -av "$h" "$KERNEL_DIR/include/linux/"
  hdr_count=$((hdr_count + 1))
done
shopt -u nullglob
if [ "$hdr_count" -eq 0 ]; then
  echo "错误：源码包里没找到 include/linux/zstd*.h" >&2
  exit 1
fi
echo "    共同步 $hdr_count 个头文件"

echo "==> 同步 crypto/zstd.c（按新接口重写适配层）"
cp -av "$SRC_ROOT/crypto/zstd.c" "$KERNEL_DIR/crypto/zstd.c"

echo "==> 结果检查"
ls "$KERNEL_DIR/lib/zstd"
echo "---- crypto/zstd.c 使用的接口 ----"
grep -nE 'zstd_(create|free|compress|decompress|init|params)' "$KERNEL_DIR/crypto/zstd.c" | head -20

echo "==> zstd 升级完成（版本: ${ZSTD_TAG}）"
