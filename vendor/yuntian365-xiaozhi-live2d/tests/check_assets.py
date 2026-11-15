#!/usr/bin/env python3
"""Check the vendored live2d pack and that C6/factory binaries were not imported."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "live2d" / "assets" / "xiaozhi-live2d"
REPO = ROOT.parents[1]

REQUIRED = [
    "angry", "confident", "confused", "cool", "crying", "delicious",
    "embarrassed", "funny", "happy", "kissy", "laughing", "loving",
    "neutral", "relaxed", "sad", "shocked", "silly", "sleepy",
    "surprised", "thinking", "winking", "idle", "speaking", "happy_anim",
]
ALIASES = {
    "warning": "confused.png",
    "cancel": "sad.png",
    "cloud_download": "thinking.png",
    "cloud_off": "sad.png",
    "link": "thinking.png",
    "download": "thinking.png",
    "gear": "thinking.png",
}
GIF_MAGIC = b"GIF8"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def fail(msg: str) -> None:
    print("FAIL", msg)
    sys.exit(1)


def main() -> None:
    index_path = ASSET / "index.json"
    index = json.loads(index_path.read_text())
    entries = index.get("emoji_collection")
    if index.get("version") != 1 or not isinstance(entries, list):
        fail("index.json must be version 1 with emoji_collection")
    if len(entries) != 31:
        fail(f"expected 31 emotion entries, got {len(entries)}")

    by_name = {}
    for entry in entries:
        name = entry["name"]
        filename = entry["file"]
        if len(filename.encode("utf-8")) > 31:
            fail(f"filename longer than 31 bytes: {filename}")
        path = ASSET / filename
        if not path.is_file():
            fail(f"missing {filename}")
        blob = path.read_bytes()[:8]
        if filename.endswith(".gif") and not blob.startswith(GIF_MAGIC):
            fail(f"{filename} is not a GIF")
        if filename.endswith(".png") and not blob.startswith(PNG_MAGIC):
            fail(f"{filename} is not a PNG")
        by_name[name] = filename

    for name in REQUIRED:
        if name not in by_name:
            fail(f"missing emotion {name}")
    for alias, target in ALIASES.items():
        if by_name.get(alias) != target:
            fail(f"alias {alias} -> {by_name.get(alias)} (want {target})")
    if by_name["idle"] != "idle.gif" or by_name["speaking"] != "speaking.gif":
        fail("idle/speaking must be the GIF animations")

    for script in ("make_live2d.py", "build_assets_bin.py"):
        if not (ROOT / "live2d" / script).is_file():
            fail(f"missing generator {script}")
    for doc in ("LICENSE", "NOTICE.md", "README.upstream.md"):
        if not (ROOT / doc).is_file():
            fail(f"missing {doc}")
    if "yuntian" not in (ROOT / "NOTICE.md").read_text(encoding="utf-8").lower() and \
            "MIT" not in (ROOT / "LICENSE").read_text(encoding="utf-8"):
        fail("LICENSE/NOTICE missing")

    banned = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith(".bin") or "network_adapter" in name or name == "c6_factory.zip":
            banned.append(str(path.relative_to(REPO)))
    if banned:
        fail("third-party binaries present: " + ", ".join(banned))

    hooks = (REPO / "firmware_patches/main/application.cc").read_text()
    if "Skip server emotion" not in hooks or "XIAOZHI_LIVE2D_CHARACTER" not in hooks:
        fail("application.cc is missing the optional lip-sync hook")
    if 'display->SetEmotion("robot_2")' not in hooks:
        fail("stock robot_2 path was removed; the flag-off build must keep it")

    print(f"ok: {len(entries)} emotions, assets and license present, no vendor binaries")


if __name__ == "__main__":
    main()
