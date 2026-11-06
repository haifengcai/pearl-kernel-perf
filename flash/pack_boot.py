#!/usr/bin/env python3
"""把新编译的 kernel Image 塞回原厂 boot.img，生成可直接 fastboot flash 的镜像。

只支持 Android boot image v3/v4（本机是 v4）。ramdisk、cmdline、签名块原样保留，
仅替换 kernel 段并重算尺寸/对齐。AVB 校验在本机为关闭状态（verifiedbootstate=orange）。

用法:
    python pack_boot.py --base boot_a.img --kernel out/arch/arm64/boot/Image --out boot_perf.img
    python pack_boot.py --base boot_a.img --kernel <原镜像里的 kernel> --out /tmp/rt.img --self-test
"""
import argparse
import os
import struct
import sys

MAGIC = b"ANDROID!"


def align(n: int, page: int = 4096) -> int:
    return (n + page - 1) // page * page


def parse(path: str):
    with open(path, "rb") as f:
        data = f.read()

    if data[:8] != MAGIC:
        raise SystemExit(f"{path}: 不是 Android boot image（magic={data[:8]!r}）")

    kernel_size, ramdisk_size, os_version, header_size = struct.unpack_from("<IIII", data, 8)
    header_version = struct.unpack_from("<I", data, 40)[0]
    if header_version not in (3, 4):
        raise SystemExit(f"只支持 boot v3/v4，当前 v{header_version}")

    page = 4096
    off = align(header_size, page)
    kernel = data[off:off + kernel_size]
    off += align(kernel_size, page)
    ramdisk = data[off:off + ramdisk_size]
    off += align(ramdisk_size, page)

    sig = b""
    if header_version == 4:
        sig_size = struct.unpack_from("<I", data, header_size - 4)[0]
        if 0 < sig_size <= 4096 * 4:
            sig = data[off:off + sig_size]

    return {
        "data": data,
        "raw_header": bytes(data[:header_size]),
        "header_size": header_size,
        "header_version": header_version,
        "kernel": kernel,
        "ramdisk": ramdisk,
        "sig": sig,
        "page": page,
    }


def build(img, kernel, out_path: str, total_size: int):
    header = bytearray(img["raw_header"])
    struct.pack_into("<I", header, 8, len(kernel))
    struct.pack_into("<I", header, 12, len(img["ramdisk"]))
    if img["header_version"] == 4:
        struct.pack_into("<I", header, img["header_size"] - 4, len(img["sig"]))

    page = img["page"]
    body = bytes(header).ljust(align(len(header), page), b"\0")
    body += kernel.ljust(align(len(kernel), page), b"\0")
    body += img["ramdisk"].ljust(align(len(img["ramdisk"]), page), b"\0")
    if img["sig"]:
        body += img["sig"].ljust(align(len(img["sig"]), page), b"\0")

    if total_size and len(body) > total_size:
        raise SystemExit(f"新镜像 {len(body)} 字节 超出分区 {total_size} 字节")
    if total_size:
        body = body.ljust(total_size, b"\0")

    with open(out_path, "wb") as f:
        f.write(body)
    return len(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-size", action="store_true",
                    help="输出补齐到与原镜像等长（默认开启，写入分区更安全）")
    ap.add_argument("--self-test", action="store_true",
                    help="用原镜像里的 kernel 回填，验证解包/重打包是否无损")
    args = ap.parse_args()

    img = parse(args.base)
    print(f"boot v{img['header_version']} header={img['header_size']} "
          f"kernel={len(img['kernel'])} ramdisk={len(img['ramdisk'])} sig={len(img['sig'])}")

    if args.self_test:
        n = build(img, img["kernel"], args.out, 0)
        with open(args.base, "rb") as f:
            orig = f.read(n)
        with open(args.out, "rb") as f:
            new = f.read(n)
        if orig == new:
            print("自检通过：解包->重打包 与原镜像逐字节一致")
            os.remove(args.out)
            return 0
        diff = next(i for i in range(n) if orig[i] != new[i])
        print(f"自检失败：首个差异位于 0x{diff:x}")
        return 1

    with open(args.kernel, "rb") as f:
        kernel = f.read()
    total = os.path.getsize(args.base) if args.keep_size else 0
    n = build(img, kernel, args.out, total)
    print(f"已生成 {args.out}  kernel={len(kernel)}  总大小={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
