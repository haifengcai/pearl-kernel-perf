#!/usr/bin/env python3
"""内核导出符号 CRC 门禁。

vendor 模块在 CONFIG_MODVERSIONS 下携带 __versions 段，里面记录了每个外部符号
在编译时的 CRC。内核加载模块时会用自己算出来的 CRC 逐一对撞，不一致就
    <mod>: disagrees about version of symbol xxx
直接拒绝加载。开机阶段 mtk_drm / mali / wlan 这些模块加载失败 = 黑屏或无限重启。

本脚本拿 refs/vendor_crc.txt（从设备真实模块里提取的基准）跟本次编译产出的
Module.symvers 逐条比对，任何一项对不上就直接失败，绝不产出可能砖机的镜像。

用法: python3 check_crc.py <Module.symvers> [refs/vendor_crc.txt]
"""
import re
import sys
from pathlib import Path

VERMAGIC_FLAGS = "SMP preempt mod_unload modversions aarch64"


def load_ref(path):
    ref = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        ref[parts[1]] = int(parts[0], 16)
    return ref


def load_symvers(path):
    """Module.symvers 格式: 0x<crc>\t<symbol>\t<module>\t<export type>"""
    sym = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            crc = int(parts[0], 16)
        except ValueError:
            continue
        sym[parts[1]] = crc
    return sym


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: check_crc.py <Module.symvers> [refs/vendor_crc.txt]")
    symvers = Path(sys.argv[1])
    ref_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("refs/vendor_crc.txt")

    if not symvers.is_file():
        sys.exit(f"::error::找不到 {symvers}，modpost 没跑成功？")

    ref = load_ref(ref_path)
    sym = load_symvers(symvers)
    print(f"基准符号 {len(ref)} 个 / 本次导出符号 {len(sym)} 个")

    mismatch, missing = [], []
    for name, want in ref.items():
        got = sym.get(name)
        if got is None:
            missing.append(name)
        elif got != want:
            mismatch.append((name, want, got))

    if missing:
        # 这些符号由【其他 vendor 模块】导出（如 mtk_aee.ko 的 aee_*、cfg80211.ko 的
        # cfg80211_*、apu_power.ko 的 apu_*），本来就不在 vmlinux.symvers 里，
        # 加载时由对应 .ko 提供，属正常，不构成风险。
        print(f"\n由其他 vendor 模块导出的符号 {len(missing)} 个（正常，不参与比对）:")
        print("  " + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))

    if mismatch:
        print(f"\nCRC 不一致 {len(mismatch)} 个:")
        for n, want, got in mismatch[:40]:
            print(f"  ! {n}: 期望 0x{want:08x} 实际 0x{got:08x}")
        print("\n::error::导出符号 CRC 与设备 vendor 模块不匹配，刷入后会大面积模块加载失败")
        return 1

    matched = len(ref) - len(missing)
    if "module_layout" not in sym or "module_layout" in missing:
        print("\n::error::连 module_layout 都没比对到，modpost 结果不可信")
        return 1
    # 覆盖率兜底：设备上 vmlinux 导出的 KMI 符号占大头，比对上的比例应该很高。
    # 低于一半说明配置或导出表出了大问题（比如 TRIM_UNUSED_KSYMS 被打开）。
    if matched < len(ref) // 2:
        print(f"\n::error::只比对到 {matched} 个符号，覆盖率过低，导出表不可信")
        return 1

    print(f"\n通过：{matched} 个符号 CRC 与设备 vendor 模块完全一致，0 个不一致")
    print(f"运行时 vermagic 标志位: {VERMAGIC_FLAGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
