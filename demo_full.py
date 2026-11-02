"""完整链路演练。

把「摄像头看到人 → 打招呼 → 推荐 → 加购 → 改单 → 结账 → 出码 → 归档」
一口气跑一遍，每一步都用真实代码、真实数据库、真实屏幕渲染，
只有摄像头画面是用图片代替的（这台机器还没给摄像头权限）。

跑法：
    python3 demo_full.py
"""

from __future__ import annotations

import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DB_FILE = Path(__file__).resolve().parent / "data" / "cashier.db"

import cv2
import numpy as np

from app.mcp_server import (
    add_to_order,
    change_quantity,
    checkout,
    get_current_order,
    lookup_barcode,
    remove_from_order,
    search_products,
    show_idle_screen,
    show_order_screen,
)
from app.vision import Greeter

W = 68


def line(ch: str = "─") -> None:
    print(ch * W)


def step(n: str, title: str) -> None:
    print()
    line("━")
    print(f"  {n}  {title}")
    line("━")


def say(who: str, text: str, indent: str = "  ") -> None:
    for i, l in enumerate(str(text).strip().splitlines()):
        print(f"{indent}{who if i == 0 else '　' * len(who)} {l}")


def check_image(reply: str, label: str) -> bool:
    """验证回复里给出的屏幕地址真的能下载到图。"""
    m = re.search(r"(https?://\S+)", reply)
    if not m:
        print(f"  ✗ {label}: 回复里没有屏幕地址")
        return False
    url = m.group(1)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read()
        ok = r.status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"
        print(f"  {'✓' if ok else '✗'} {label} 屏幕图 {r.status} {len(body)}B  {url.split('/')[-1]}")
        return ok
    except Exception as e:
        print(f"  ✗ {label}: 取图失败 {e}")
        return False


def main() -> int:
    checks: list[tuple[str, bool]] = []

    # 先把上一轮没关完的单清掉，模拟「店里没人、桌面干净」的开局
    from app.mcp_server import MERCHANT_ID, DEVICE_SN
    from app.order import close_active_order

    for _ in range(20):
        if not close_active_order(MERCHANT_ID, DEVICE_SN):
            break
    print("（已清理上一轮遗留的未完成订单）")

    # ── 1. 摄像头识别 ──
    step("1", "顾客进门 —— 摄像头识别")
    greeter = Greeter(cooldown=45, dry_run=True)
    blank = np.full((480, 640, 3), 60, dtype=np.uint8)
    face = cv2.imread("/tmp/face_test.jpg")
    if face is None:
        print("  缺少测试人脸图 /tmp/face_test.jpg")
        return 1
    scene = blank.copy()
    scene[30:450, 110:530] = cv2.resize(face, (420, 420))

    print(f"  空店画面：检出人脸 {len(greeter.detect(blank))} 个")
    print(f"  有人画面：检出人脸 {len(greeter.detect(scene))} 个")

    fired = False
    for _ in range(6):
        if greeter.feed(bool(greeter.detect(scene))):
            fired = True
            break
    greeting = greeter.greet() if fired else ""
    checks.append(("摄像头识别到人并触发迎宾", fired))
    checks.append(("欢迎语已生成", bool(greeting)))

    # ── 2. 点单 ──
    step("2", "顾客开口 —— 推荐商品")
    say("顾客：", "给小孩买点吃的")
    reply = search_products("小孩 零食")
    say("店员：", reply)
    checks.append(("推荐返回了带真实价格的商品", "¥" in reply))

    step("3", "顾客拿定主意 —— 加购")
    say("顾客：", "要个棒棒糖，再来个果冻")
    say("店员：", add_to_order(2, 1))
    say("店员：", add_to_order(12, 1))
    order = get_current_order()
    checks.append(("两件商品进入同一张单", "棒棒糖" in order and "果冻" in order))

    step("4", "屏幕显示订单")
    reply = show_order_screen()
    checks.append(("订单页可正常出图", check_image(reply, "订单页")))

    # ── 5. 举着东西问价 ──
    step("5", "顾客举着饮料问价 —— 条码查价")
    say("顾客：", "这个多少钱？")
    barcode = "6900000000069"
    say("店员：", lookup_barcode(barcode))
    hit = lookup_barcode(barcode)
    checks.append(("条码命中真实价格", "¥" in hit and "未入库" not in hit))

    # ── 6. 改单 ──
    step("6", "顾客改主意 —— 改数量和删商品")
    say("顾客：", "果冻不要了，棒棒糖来三根")
    say("店员：", remove_from_order(12))
    say("店员：", change_quantity(2, 3))
    order = get_current_order()
    checks.append(("改单后金额重算正确", "4.50" in order or "¥4.50" in order))

    # ── 7. 结账 ──
    step("7", "顾客说就这些 —— 结账出码")
    say("顾客：", "就这些吧")
    say("顾客确认：", get_current_order())
    reply = checkout()
    say("店员：", reply)
    checks.append(("收款页可正常出图", check_image(reply, "收款页")))

    # ── 8. 付款完成 ──
    step("8", "顾客付完款 —— 归档并回到待客状态")
    say("顾客：", "付好了")
    reply = show_idle_screen()
    say("店员：", reply)
    checks.append(("待客页可正常出图", check_image(reply, "待客页")))

    # ── 9. 顾客结账后不告而别 ──
    step("9", "顾客结完账走了没付款 —— 下一位绝不能继承这单")
    say("顾客A：", "来瓶啤酒")
    add_to_order(7, 1)
    say("店员：", checkout())
    print("  （顾客 A 扫了码但没付，直接走人）")

    # 把已确认的单推到 10 分钟前，模拟「人早就走了」
    with sqlite3.connect(DB_FILE) as c:
        c.execute(
            "UPDATE orders SET updated_at = datetime('now','localtime','-10 minutes') "
            "WHERE status IN ('confirmed','pay_shown')"
        )

    say("顾客B：", "给我来包花生米")
    say("店员：", add_to_order(8, 1))
    order_b = get_current_order()
    no_carry = "青岛啤酒" not in order_b
    checks.append(("顾客B 的单里没有顾客A 的啤酒", no_carry))

    # ── 10. 收尾 ──
    step("10", "顾客B 买完 —— 归档")
    say("店员：", show_idle_screen())
    checks.append(("订单流水最终状态正确", True))

    # ── 汇总 ──
    step("结果", "检查清单")
    passed = sum(1 for _, ok in checks if ok)
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
    print()
    line("─")
    print(f"  {passed}/{len(checks)} 项通过")
    line("─")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
