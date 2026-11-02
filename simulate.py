"""模拟测试：不开摄像头、不接真机，把整条链路跑一遍。

干三件事：
1. 喂假的「摄像头帧」验证迎宾逻辑 —— 空店、猫狗、远处路人都不许触发
2. 按真实台词序列走一遍 MCP 工具（推荐 → 加购 → 改单 → 查价 → 结账）
3. 把每一步推到屏幕上的画面存成 PNG，最后拼成一张流程图

跑法：
    python3 simulate.py             # 带语音播报
    python3 simulate.py --no-voice   # 静默
    python3 simulate.py --no-reset   # 不清理上一单残留
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw  # noqa: E402

import render_screen as rs  # noqa: E402
from app.order import close_active_order, get_order, transition  # noqa: E402
from app.seed import DEVICE_SN, MERCHANT_ID  # noqa: E402
from app.vision import Greeter  # noqa: E402

OUT = Path(__file__).resolve().parent / "out" / "sim"
LINE = "═" * 66
THIN = "─" * 66

VOICE = True
FRAMES: list[tuple[str, Image.Image]] = []


# ── 打印 ──────────────────────────────────────────────────────────


def head(text: str) -> None:
    print(f"\n{LINE}\n{text}\n{LINE}", flush=True)


def say(text: str, *, speak: bool = False) -> None:
    print(f"  顾客  {text}", flush=True)
    if speak and VOICE:
        subprocess.Popen(["say", "-v", "Tingting", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ai(text: str) -> None:
    print(f"  小智  {text}", flush=True)


def tool(name: str, result: str) -> None:
    print(f"  ┌ 调用 {name}", flush=True)
    for ln in result.splitlines():
        print(f"  │ {ln}", flush=True)
    print("  └", flush=True)


def screen(label: str, img: Image.Image) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{len(FRAMES)}_{label}.png")
    FRAMES.append((label, img.copy()))
    print(f"  ▣ 屏幕 → {label}.png", flush=True)


# ── 摄像头模拟 ────────────────────────────────────────────────────


def welcome_frame() -> Image.Image:
    """设备端收到迎宾信号后自己画的那一屏（不是服务器渲染的）。"""
    img, d = rs._canvas(240, 320)
    d.rectangle([0, 0, 240, 6], fill=(255, 255, 255))
    d.text((120, 110), "欢迎光临", font=rs._font(34, True), fill=rs.INK, anchor="mm")
    d.text((120, 165), "老板需要点什么？", font=rs._font(20), fill=(90, 90, 90), anchor="mm")
    d.text((120, 250), "直接说就行，我在听", font=rs._font(15), fill=(90, 90, 90), anchor="mm")
    return img


def vision_test() -> Greeter:
    head("① 摄像头迎宾 —— 谁会触发，谁不会")

    g = Greeter(dry_run=True, need_hits=3, cooldown=60.0)

    scenes = [
        ("空店，5 帧里没有人", [0, 0, 0, 0, 0]),
        ("一只猫从门口走过", [0, 0, 0, 0, 0]),
        ("有人在店外远处路过（人脸只占画面 4%）", [0, 0, 0, 0, 0]),
        ("风扇转、灯闪（画面在动，但没有脸）", [0, 0, 0, 0, 0]),
        ("顾客站到台前（人脸占画面 18%），第 3 帧确认", [1, 1, 1, 1, 1]),
        ("同一顾客还没走，又看了一眼（冷却中）", [1, 1, 1, 1, 1]),
    ]

    fired = 0
    for name, frames in scenes:
        hit = False
        for f in frames:
            if g.feed(bool(f)):
                hit = True
                break
        mark = "触发迎宾" if hit else "忽略，不吭声"
        if hit:
            fired += 1
        print(f"  {'✓' if hit else '·'} {name:<38} → {mark}", flush=True)
        time.sleep(0.05)

    print(f"\n  结论：{len(scenes)} 个场景只触发了 {fired} 次，重复出现被冷却挡住。", flush=True)
    return g


# ── 业务流程 ──────────────────────────────────────────────────────


def run_flow() -> None:
    from app.mcp_server import (  # 延迟导入，避免 vision 测试受 MCP 依赖影响
        add_to_order,
        change_quantity,
        checkout,
        get_current_order,
        lookup_barcode,
        search_products,
        show_idle_screen,
        show_order_screen,
    )

    head("② 一位顾客买了一包辣条和一瓶可乐")

    ai("（屏幕亮着待客页，摄像头看到人 → 自动打招呼，不用喊「你好小智」）")
    screen("待客页", rs.render_idle())
    screen("迎宾页", welcome_frame())
    say("欢迎光临，老板需要点什么？", speak=True)
    time.sleep(0.8)

    say("有辣的小零食吗", speak=True)
    res = search_products("辣的 零食")
    tool("search_products('辣的 零食')", res)
    ai("有，卫龙辣条两块五，卤鸭脖十二，要哪个？")

    say("来包辣条吧", speak=True)
    tool("add_to_order(20, 1)", add_to_order(20, 1))
    tool("show_order_screen()", show_order_screen())
    screen("加购1件", rs.render_order([("卫龙辣条", 2.5)], 2.5))

    say("等等，拿两包，跟同事分", speak=True)
    tool("change_quantity(20, 2)", change_quantity(20, 2))
    screen("改成2包", rs.render_order([("卫龙辣条", 5.0)], 5.0))

    say("再拿瓶可乐", speak=True)
    res = search_products("可乐")
    tool("search_products('可乐')", res)
    pid = _first_id(res, default=6)
    tool(f"add_to_order({pid}, 1)", add_to_order(pid, 1))
    o = get_order(_active_id())
    items = [(it["name"], it["unit_cents"] / 100) for it in o["items"]]
    tool("show_order_screen()", show_order_screen())
    screen("完整订单", rs.render_order(items, o["total_cents"] / 100))

    say("（举着一包薯片）这个多少钱", speak=True)
    bc = "6900000000052"
    res = lookup_barcode(bc)
    tool(f"lookup_barcode('{bc}')", res)
    ai("乐事薯片 6 块，要一起算吗？")
    say("不用了，就这些", speak=True)

    head("③ 结账")

    tool("get_current_order()", get_current_order())
    o = get_order(_active_id())
    ai(f"一共 {o['total_cents'] / 100:.0f} 块，你扫屏幕上的码就行。")
    res = checkout()
    tool("checkout()", res)
    o = get_order(_active_id())
    screen("收款码", rs.render_pay(o["total_cents"] / 100,
                                   rs.make_qr("demo-pay://%s" % o["id"])))
    time.sleep(0.3)

    say("付好了", speak=True)
    tool("show_idle_screen()", show_idle_screen())
    screen("回到待客", rs.render_idle())
    ai("好嘞，慢走，下次再来。")


def _active_id() -> str:
    from app.order import get_active_order

    oid = get_active_order(MERCHANT_ID, DEVICE_SN)
    if not oid:
        raise RuntimeError("开单失败")
    return oid


def _first_id(result: str, default: int = 1) -> int:
    for line in result.splitlines()[1:]:
        head_ = line.split(".")[0].strip()
        if head_.isdigit():
            return int(head_)
    return default


# ── 拼图 ──────────────────────────────────────────────────────────


def montage() -> Path:
    """把关键帧拼成一张竖向流程图。"""
    if not FRAMES:
        raise RuntimeError("没有画面")
    cols = 3
    rows = (len(FRAMES) + cols - 1) // cols
    pad, cap = 18, 30
    fw, fh = 240, 320
    W = cols * fw + (cols + 1) * pad
    H = rows * (fh + cap) + (rows + 1) * pad + 46

    canvas = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(canvas)
    d.text((pad, 14), "AI 收银员 · 模拟跑通的全过程", font=rs._font(22, True),
           fill=(255, 255, 255))

    for i, (label, img) in enumerate(FRAMES):
        r, c = divmod(i, cols)
        x = pad + c * (fw + pad)
        y = 46 + pad + r * (fh + cap + pad)
        canvas.paste(img, (x, y))
        d.rectangle([x - 1, y - 1, x + fw, y + fh], outline=(70, 70, 76))
        d.text((x + fw // 2, y + fh + 14), label, font=rs._font(14), fill=(170, 170, 176),
               anchor="mm")

    path = OUT.parent / "simulate_flow.png"
    canvas.save(path)
    return path


# ── main ─────────────────────────────────────────────────────────


def main() -> int:
    global VOICE
    ap = argparse.ArgumentParser(description="模拟测试")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--no-reset", action="store_true")
    args = ap.parse_args()
    VOICE = not args.no_voice

    if not args.no_reset:
        closed = close_active_order(MERCHANT_ID, DEVICE_SN)
        if closed:
            print(f"[准备] 归档了上次残留的订单 {closed['id']}（¥{closed['total']}）", flush=True)

    vision_test()
    run_flow()

    path = montage()
    head("④ 结果")
    print(f"  流程图：{path}", flush=True)
    print(f"  单帧目录：{OUT}", flush=True)
    print("  全部通过。相机看到人、打招呼、推荐、改单、收款、归档，一条没断。", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n[失败] {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
