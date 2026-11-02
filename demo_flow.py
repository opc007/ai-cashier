"""端到端流程演示：从顾客进店到出收款码。

不接设备、不接大模型，纯本地跑通业务逻辑，用来验证：
推荐引擎 / 条码命中 / 订单状态机 / 收款页渲染 这四块是否配合正确。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.order import (  # noqa: E402
    OrderError,
    add_by_barcode,
    add_item,
    get_active_order,
    remove_item,
    transition,
)
from app.recommend import find_by_barcode, fuzzy_search, normalize_tags, recommend  # noqa: E402
from app.seed import DEVICE_SN, MERCHANT_ID  # noqa: E402
from render_screen import make_qr, render_pay  # noqa: E402

LINE = "─" * 62


def title(text: str) -> None:
    print(f"\n{LINE}\n{text}\n{LINE}")


def show_candidates(items: list[dict]) -> None:
    if not items:
        print("  （没有匹配的商品）")
        return
    for it in items:
        hit = f" 命中{it['hits']}" if it.get("hits") else ""
        print(f"  · {it['name']:<18} ¥{it['price']:>6} /{it['unit']}{hit}")


def show_order(o: dict) -> None:
    for it in o["items"]:
        print(f"  {it['name']:<20} ¥{it['unit_price']:>6} × {it['qty']}  = ¥{it['subtotal']:>7}")
    print(f"  {'合计':<20} {'':>6}   {'':>3}    ¥{o['total']:>7}   [{o['status']}]")


def main() -> None:
    print(f"\n商户: {MERCHANT_ID}   设备: {DEVICE_SN}")

    # ---- 1. 顾客进门，AI 主动问候，顾客说「给孩子买点吃的」
    title("① 顾客: 给小孩买点吃的 → 推荐引擎按标签检索")
    tags = normalize_tags("小孩 零食")
    print(f"  口语「小孩 零食」归一化为标签: {tags}")
    show_candidates(recommend(MERCHANT_ID, tags, limit=4))

    order_id = get_active_order(MERCHANT_ID, DEVICE_SN)
    print(f"\n  已开单: {order_id}")

    # ---- 2. 顾客选定两样，加进订单
    title("② 加购：棒棒糖 ×2、旺仔牛奶 ×1")
    lollipop = fuzzy_search(MERCHANT_ID, "棒棒糖")[0]
    milk = fuzzy_search(MERCHANT_ID, "旺仔")[0]
    o = add_item(order_id, lollipop["id"], qty=2)
    o = add_item(order_id, milk["id"], qty=1)
    show_order(o)

    # ---- 3. 顾客举起一瓶饮料问价格 → 条码精确命中
    title("③ 顾客举瓶饮料问价 → 条码精确命中（不靠模型猜）")
    demo_barcode = find_by_barcode(MERCHANT_ID, "6900000000069")
    print(f"  条码 6900000000069 命中: {demo_barcode['name']}  ¥{demo_barcode['price']}")
    o = add_by_barcode(order_id, "6900000000069", qty=1)
    show_order(o)

    # ---- 4. 顾客改主意，退掉一瓶牛奶
    title("④ 顾客改主意：牛奶不要了")
    o = remove_item(order_id, milk["id"])
    show_order(o)

    # ---- 5. 状态机保护：已确认的订单不能偷偷改
    title("⑤ 确认订单，然后试图再改 → 应被状态机拒绝")
    o = transition(order_id, "confirmed")
    print(f"  确认后状态: {o['status']}  合计 ¥{o['total']}")
    try:
        add_item(order_id, lollipop["id"], qty=1)
        print("  ✗ 严重问题：已确认订单竟然被修改了")
    except OrderError as e:
        print(f"  ✓ 正确拦截: {e}")

    # ---- 6. 出收款码
    title("⑥ 顾客扫码付款 → 渲染付款页")
    o = transition(order_id, "pay_shown")
    os.makedirs("./out", exist_ok=True)
    qr = make_qr(f"https://example.com/pay/{order_id}")
    pay_img = render_pay(o["total"], qr, 240, 320, hint=f"应付 ¥{o['total']}")
    pay_path = f"./out/pay_{order_id}.png"
    pay_img.save(pay_path, "PNG", optimize=True)
    print(f"  付款页已生成: {pay_path}  ({os.path.getsize(pay_path) / 1024:.1f} KB)")
    print(f"  订单 {order_id} 状态: {o['status']}")

    title("⑦ 结账完成")
    o = transition(order_id, "closed")
    print(f"  最终状态: {o['status']}  收款 ¥{o['total']}")
    print(f"\n付款页路径: {os.path.abspath(pay_path)}\n")


if __name__ == "__main__":
    main()
