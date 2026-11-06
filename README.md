# pearl-kernel-perf

Redmi Note 12T Pro（`pearl` / MT6895 / 天玑 8200-Ultra）性能与省电向内核的重编译工程。
源码基线是设备正在运行的那棵：`ztc1997/android_gki_kernel_5.10_common` 的
`android12-5.10-2025-09` 分支（Linux 5.10.240）。

## 为什么必须"复刻"而不是"换一个内核"

这台机器的 391 个 vendor 模块（屏幕、触摸、WiFi、音频、相机…）在加载时校验内核版本串，
也就是 vermagic：

```
5.10.240-ztc1997-android12-9-02429-gb280068f4235 SMP preempt mod_unload modversions aarch64
```

只要这个串对不上，模块全部拒绝加载，直接黑屏/起不来。工程里做了三件事保证一致：

1. `configs/device.config` 直接来自手机 `/proc/config.gz`，就是出厂内核的配置；
2. `CONFIG_LOCALVERSION` 被钉死为 `-ztc1997-android12-9-02429-gb280068f4235`，并关闭
   `LOCALVERSION_AUTO`，避免 git 状态影响版本串；
3. CI 里有一道断言，`out/include/config/kernel.release` 不等于目标串就直接失败，
   不会产出半成品。

另外只做**纯配置项**改动（BBR、FQ、CAKE、压缩器），不碰任何被导出的结构体，
所以 `MODVERSIONS` 的 CRC 也不会变。

## 目录结构

```
.github/workflows/build.yml   CI：装 clang r584948 → 拉源码 → 合配置 → 编译 → 校验 → 出包
configs/device.config         设备原厂内核配置（6756 行，含 vermagic 钉死）
configs/perf.config           性能/省电补丁：BBR + FQ + CAKE + 压缩器
configs/zstd-upgrade.config   zstd 升级时关闭 f2fs/squashfs 的私有 zstd 调用
scripts/set_config.py         KCONFIG 片段叠加工具
scripts/upgrade_zstd.sh       把 lib/zstd 从 1.4.10 换成 1.5.x（取自 linux v6.6）
flash/pack_boot.py            把新 Image 塞回原厂 boot.img（已通过逐字节自检）
```

## 跑一次编译

### 方式 A：网页上传（不需要装任何东西）

1. 在 GitHub 新建一个 **public** 仓库（public 才有免费不限时的 Actions 额度），
   名字随意，比如 `pearl-kernel-perf`；
2. 把本目录下所有文件按原结构上传（`.github/workflows/build.yml` 的路径必须保持）；
3. 打开 Actions → `build-pearl-kernel` → Run workflow：
   - `base_branch` 保持 `android12-5.10-2025-09`
   - `zstd_upgrade` 第一轮**留空/false**，先确认能开机再开
4. 等 40~70 分钟，下载 artifact `kernel-Image`。

### 方式 B：git push

```bash
git init && git add -A
git commit -m "pearl kernel perf build"
git remote add origin git@github.com:<你的用户名>/pearl-kernel-perf.git
git push -u origin main
```

## 本地打包成可刷的 boot.img

CI 只产出 `Image`，ramdisk / cmdline / 签名块沿用你手机上的原厂 boot，打包在本地做：

```bash
# work/boot_a.img 是从你手机 dd 出来的原厂 boot（已备份，勿删）
python flash/pack_boot.py --base ../work/boot_a.img \
       --kernel Image-5.10.240-ztc1997-android12-9-02429-gb280068f4235 \
       --out boot_perf.img --keep-size
```

脚本支持 `--self-test`：用原 kernel 回填后与原镜像逐字节比对，验证解包/重打包无损
（本机已验证通过）。

## 刷入

```bash
adb reboot bootloader
fastboot devices
fastboot flash boot boot_perf.img
fastboot reboot
```

> 当前槽位是 `_a`；`fastboot flash boot` 会自动刷到当前活动槽。

## 回滚（重要，先看）

原厂 boot 已经在 `work/boot_a.img`（64 MB，dd 自 `boot_a`，即当前运行中的这一版）：

```bash
adb reboot bootloader
fastboot flash boot ../work/boot_a.img
fastboot reboot
```

如果开不了机但能进 fastboot，上面这条就能救回来；KernelSU 的 `su` 也依赖这个内核，
回滚后 root 状态与现在完全一致。

## zstd 升级（实验性，第二轮再开）

- 内核树里的 **lz4 已经是 1.10.0（最新）**，不需要动；
- zstd 是 1.4.10 老 API，`scripts/upgrade_zstd.sh` 会把 `lib/zstd`、`include/linux/zstd*.h`
  和 `crypto/zstd.c` 换成 linux v6.6 的实现（1.5.x），zram 走 crypto API，能直接吃到新库；
- 第一版同时关掉 `F2FS_FS_ZSTD` 与 `SQUASHFS_ZSTD`，因为这两处直接调私有 API，
  新旧接口差异最大、最容易编不过，而且日常用不到。

开了这个开关如果编译报错，把日志发我，按报错点补适配即可；不影响关掉时的正常出包。

## 这版改了什么（对照出厂内核）

| 项 | 出厂内核 | 本工程 |
|---|---|---|
| TCP 拥塞控制 | cubic | **BBR**（默认） |
| 队列规则 | 无 fq | fq / fq_codel / cake |
| zram | zstd（1.4.10） | 同上，可选升级到 1.5.x |
| 调试性开销 | ACK 默认 | 未改动（保持 vendor 兼容） |

BBR 的作用是弱网、高负载下延迟不炸、重传少，体感就是"刷视频不转圈"；
fq/cake 解决下载时的 bufferbloat（边下边卡）。zram 换新 zstd 后压缩/解压更快，
内存吃紧时的卡顿会缓一点。
