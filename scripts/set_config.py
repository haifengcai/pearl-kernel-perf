#!/usr/bin/env python3
"""把 KCONFIG 片段叠加到 .config 上（就地替换同名项，缺失则追加）。

用法: set_config.py <out/.config> <fragment> [更多片段...]
支持的行格式:
    CONFIG_FOO=y
    CONFIG_FOO="value"
    # CONFIG_FOO is not set
其余以 # 开头的是注释，忽略。
"""
import sys

PREFIX = "# CONFIG_"


def key_of(line: str):
    s = line.strip()
    if s.startswith(PREFIX) and s.endswith(" is not set"):
        return s[len("# "):].split()[0]
    if s.startswith("CONFIG_") and "=" in s:
        return s.split("=", 1)[0]
    return None


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    cfg_path, fragments = sys.argv[1], sys.argv[2:]
    with open(cfg_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    index = {}
    for i, line in enumerate(lines):
        k = key_of(line)
        if k and k not in index:
            index[k] = i

    changed, added = 0, 0
    for frag in fragments:
        with open(frag, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n").strip()
                if not line or (line.startswith("#") and not line.startswith(PREFIX)):
                    continue
                if not line.startswith("CONFIG_") and not line.startswith(PREFIX):
                    continue
                k = key_of(line)
                if k is None:
                    continue
                if k in index:
                    i = index[k]
                    if lines[i] != line:
                        lines[i] = line
                        changed += 1
                else:
                    index[k] = len(lines)
                    lines.append(line)
                    added += 1

    with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[set_config] modified={changed} appended={added} -> {cfg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
