# -*- coding: utf-8 -*-
"""
把 Live2D 角色资源合并进小智的 assets.bin (无需重编固件)。

做法: 读取现有 build/generated_assets.bin -> 保留字体/语音模型等所有非表情条目
      -> 删除旧 emoji 文件 -> 加入 assets/xiaozhi-live2d/ 下的 PNG/GIF
      -> 重写 index.json 的 emoji_collection -> 用官方格式重新打包并校验。

用法:
  python build_assets_bin.py
  python build_assets_bin.py --base <其它 generated_assets.bin> --out <输出路径>
"""
import os
import sys
import json
import struct
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets" / "xiaozhi-live2d"
DEFAULT_BASE = Path(r"C:\xz\xiaozhi-esp32\build\generated_assets.bin")
DEFAULT_OUT = ROOT / "xiaozhi-live2d-assets.bin"
NAME_LENGTH = 32
MAX_SIZE = 8 * 1024 * 1024  # P4 partitions/v2/16m.csv 的 assets 分区

# 深色主题：写进 index.json 的 skin 段（assets.cc / LvglTheme::ParseColor 接受 #RRGGBB）。
# light 与 dark 两套主题都覆盖，保证不论当前用哪套主题，角色都站在深色背景上。
DARK_SKIN = {
    "light": {"text_color": "#E8F2FF", "background_color": "#101826"},
    "dark": {"text_color": "#EAF4FF", "background_color": "#0B1220"},
}

# 固件 Alert() 弹窗使用的系统级 emotion 名（application.cc / wifi_board.cc）。
# 这些不在 21 个角色情绪里，缺了会 fallback 到 material_symbols 字体图标，
# 并打 "Emoji not found: xxx" 警告。补成指向现有角色 PNG 的别名，
# 保证错误、配网、升级等界面也显示角色而不是一个图标。
SYSTEM_EMOTION_ALIASES = {
    "warning": "confused.png",
    "cancel": "sad.png",
    "cloud_download": "thinking.png",
    "cloud_off": "sad.png",
    "link": "thinking.png",
    "download": "thinking.png",
    "gear": "thinking.png",
}


def compute_checksum(data):
    return sum(data) & 0xFFFF


def read_entries(path):
    data = Path(path).read_bytes()
    if len(data) < 12:
        raise ValueError("assets 头部不合法")
    count, checksum, length = struct.unpack_from("<III", data)
    entry = struct.Struct(f"<{NAME_LENGTH}sIIHH")
    table_size = count * entry.size
    if length > len(data) - 12 or table_size > length:
        raise ValueError("assets 表被截断")
    payload = data[12:12 + length]
    if compute_checksum(payload) != checksum:
        raise ValueError("assets checksum 校验失败")
    files = {}
    for off in range(0, table_size, entry.size):
        name, size, start, width, height = entry.unpack_from(payload, off)
        name = name.split(b"\0", 1)[0].decode("utf-8")
        start += table_size
        end = start + 2 + size
        if not name or name in files or end > length or payload[start:start + 2] != b"ZZ":
            raise ValueError(f"非法条目: {name}")
        files[name] = (payload[start + 2:end], width, height)
    return files


def pack_entries(files):
    entry = struct.Struct(f"<{NAME_LENGTH}sIIHH")
    table, payload = bytearray(), bytearray()
    for name, (data, width, height) in files.items():
        encoded = name.encode("utf-8")
        if len(encoded) > NAME_LENGTH - 1:
            raise ValueError(f"文件名过长 (需 <=31 字节): {name}")
        table.extend(entry.pack(encoded, len(data), len(payload), width, height))
        payload.extend(b"ZZ" + data)
    payload = table + payload
    return struct.pack("<III", len(files), compute_checksum(payload), len(payload)) + payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(DEFAULT_BASE), help="现有 generated_assets.bin")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 assets.bin")
    args = ap.parse_args()

    base = Path(args.base)
    if not base.is_file():
        sys.exit(f"找不到基础 assets 包: {base}\n请先完成一次 idf.py build / build.py 让它生成。")

    files = read_entries(base)
    print(f"读取 {base.name}: {len(files)} 个条目, {base.stat().st_size / 1024:.0f} KB")

    index = json.loads(files["index.json"][0].decode("utf-8"))
    if index.get("version", 1) != 1:
        sys.exit("index.json version 必须为 1")

    # 删掉旧表情文件 (保留字体 / srmodels / skin 等所有其它资源)
    old_emoji = [e["file"] for e in index.get("emoji_collection", []) if isinstance(e, dict)]
    for name in old_emoji:
        files.pop(name, None)
    print(f"移除旧表情 {len(old_emoji)} 个")

    # 加入新角色资源
    new_entries = []
    for p in sorted(ASSET_DIR.iterdir()):
        if p.suffix.lower() not in (".png", ".gif"):
            continue
        if len(p.name.encode("utf-8")) > 31:
            raise ValueError(f"文件名过长: {p.name}")
        files[p.name] = (p.read_bytes(), 0, 0)
        new_entries.append({"name": p.stem, "file": p.name})

    # 补系统弹窗别名（多个 name 可以指向同一个 PNG，assets 只存一份文件）
    for alias, target in SYSTEM_EMOTION_ALIASES.items():
        if target not in files:
            raise ValueError(f"别名指向的文件不存在: {alias} -> {target}")
        new_entries.append({"name": alias, "file": target})

    index["emoji_collection"] = new_entries
    index["skin"] = DARK_SKIN
    files["index.json"] = (json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 0, 0)

    packed = pack_entries(files)
    if len(packed) > MAX_SIZE:
        sys.exit(f"资源包 {len(packed) / 1024 / 1024:.2f} MB 超过 assets 分区 8MB 上限")
    out = Path(args.out)
    out.write_bytes(packed)

    # 回读校验
    check = read_entries(out)
    assert len(check) == len(files), "回读条目数不一致"
    print(f"\n生成成功: {out}")
    print(f"  条目 {len(files)} 个, {len(packed) / 1024 / 1024:.2f} MB / 8.00 MB")
    print(f"  表情 {len(new_entries)} 个（含 {len(SYSTEM_EMOTION_ALIASES)} 个系统别名）, checksum 校验通过")
    print(f"  主题: 深色 light={DARK_SKIN['light']['background_color']} / dark={DARK_SKIN['dark']['background_color']}")
    print(f"  保留资源: {[k for k in files if not k.endswith(('.png', '.gif'))]}")


if __name__ == "__main__":
    main()
