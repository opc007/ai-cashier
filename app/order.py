"""订单状态机。

状态流转：open -> confirmed -> pay_shown -> closed
任意未终态可直接 -> cancelled

规矩：
- 只有 open 态能改商品。已经确认了就不许偷偷加东西，得先退回 open
- 金额永远重算，不缓存。缓存是 bug 的温床
- 金额一律用分（int）
"""

from __future__ import annotations

import uuid

from app.db import get_db

# 允许的流转，其它一概拒绝
TRANSITIONS = {
    "open": {"confirmed", "cancelled"},
    "confirmed": {"pay_shown", "open", "cancelled"},
    "pay_shown": {"closed", "confirmed", "cancelled"},
    "closed": set(),
    "cancelled": set(),
}


class OrderError(Exception):
    pass


# 一单超过这个分钟数没动静，就不再算「当前订单」
STALE_MINUTES = 30

# 已确认/已出码的单，只在这个窗口内还算同一顾客的。
# 给 3 分钟是为了留出「顾客刚说结账，又想再加一瓶」的余地；
# 再久就不该继承了——上一位顾客可能早就走人，不能让下一位替他买单。
PAY_WINDOW_MINUTES = 3


def _now() -> str:
    return "datetime('now', 'localtime')"


def _check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise OrderError(f"订单状态不能从 {current} 变为 {target}")


def create_order(merchant_id: str, device_sn: str | None = None) -> str:
    oid = uuid.uuid4().hex[:12]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO orders (id, merchant_id, device_sn, status) VALUES (?, ?, ?, 'open')",
            (oid, merchant_id, device_sn),
        )
    return oid


def get_active_order(merchant_id: str, device_sn: str | None = None) -> str | None:
    """找当前这一单，没有则新建。

    两种状态的容忍度不一样：
    - open（还在挑）：30 分钟内都算同一单，顾客挑得慢很正常
    - confirmed / pay_shown（已确认、已出码）：只认 3 分钟。顾客结完账人走了，
      下一位进店绝不能继承上一张单，否则会替别人付钱——这是收银系统里
      最不能犯的错。
    """
    with get_db() as conn:
        row = conn.execute(
            f"""SELECT id FROM orders
               WHERE merchant_id = ?
                 AND (? IS NULL OR device_sn = ?)
                 AND (
                       (status = 'open'
                        AND datetime(updated_at) > datetime('now', 'localtime', '-{STALE_MINUTES} minutes'))
                    OR (status IN ('confirmed', 'pay_shown')
                        AND datetime(updated_at) > datetime('now', 'localtime', '-{PAY_WINDOW_MINUTES} minutes'))
                     )
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (merchant_id, device_sn, device_sn),
        ).fetchone()
    if row:
        return row["id"]
    return create_order(merchant_id, device_sn)


# 没付钱的单过这个时限自动作废：
# - open（还在挑）10 分钟：顾客拿了东西就走的太常见，挂着会挡住下一单
# - confirmed / pay_shown（出了码没付）5 分钟：屏幕不能永远停在上一张收款码
EXPIRE_OPEN_MINUTES = 10
EXPIRE_PAYING_MINUTES = 5


def expire_stale_orders() -> list[str]:
    """把没有终态、且超过时限没动静的订单强制作废。

    顾客进进出出的真实场景里，很多人拿了东西就走、出到码也不付。
    这些单一直挂着有两个害处：AI 的「当前订单」判断被污染（上一位顾客
    可能被算进下一位的头上），屏幕也永远停在旧的收款码页。

    作废一律用 cancelled（没收到钱就不能记 closed，否则虚增营收）。
    返回被作废的订单 id 列表，空列表说明没有可回收的。
    """
    expired: list[str] = []
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, status FROM orders
               WHERE status IN ('open', 'confirmed', 'pay_shown')
                 AND (
                      (status = 'open'
                       AND datetime(updated_at) < datetime('now', 'localtime',
                            ?))
                   OR (status IN ('confirmed', 'pay_shown')
                       AND datetime(updated_at) < datetime('now', 'localtime',
                            ?))
                     )""",
            (f"-{EXPIRE_OPEN_MINUTES} minutes", f"-{EXPIRE_PAYING_MINUTES} minutes"),
        ).fetchall()
        for r in rows:
            conn.execute(
                f"UPDATE orders SET status = 'cancelled', updated_at = {_now()} WHERE id = ?",
                (r["id"],),
            )
            expired.append(r["id"])
    return expired


def close_active_order(merchant_id: str, device_sn: str | None = None) -> dict | None:
    """结束当前这一单，让屏幕回到待客状态。

    已确认/已出码的单视为收款完成（closed），还在挑选中的单视为顾客放弃（cancelled）。
    没有支付回调的情况下，这是最贴近真实收银的判断。
    """
    oid = None
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, status FROM orders
               WHERE merchant_id = ? AND status IN ('open', 'confirmed', 'pay_shown')
                 AND (? IS NULL OR device_sn = ?)
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (merchant_id, device_sn, device_sn),
        ).fetchone()
        if not row:
            return None
        oid = row["id"]
        target = "cancelled" if row["status"] == "open" else "closed"
        conn.execute(
            f"UPDATE orders SET status = ?, updated_at = {_now()} WHERE id = ?",
            (target, oid),
        )
    return get_order(oid)


def _require_status(conn, order_id: str, allowed: tuple[str, ...]) -> str:
    row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        raise OrderError(f"订单不存在: {order_id}")
    if row["status"] not in allowed:
        raise OrderError(f"订单当前状态 {row['status']}，不允许此操作")
    return row["status"]


def _ensure_editable(conn, order_id: str) -> None:
    """改单前把订单拉回可编辑状态。

    顾客已经确认、甚至收款码都出来了，又说「等一下，再给我加一个」——这在小店
    里太常见，不能因为状态卡住就让顾客从头再说一遍。
    """
    status = _require_status(conn, order_id, ("open", "confirmed", "pay_shown"))
    if status != "open":
        _check_transition(status, "open")
        conn.execute(
            f"UPDATE orders SET status = 'open', updated_at = {_now()} WHERE id = ?",
            (order_id,),
        )


def _recalc_total(conn, order_id: str) -> int:
    total = conn.execute(
        "SELECT COALESCE(SUM(unit_cents * qty), 0) AS t FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()["t"]
    conn.execute(
        f"UPDATE orders SET total_cents = ?, updated_at = {_now()} WHERE id = ?",
        (total, order_id),
    )
    return total


def add_item(order_id: str, product_id: int, qty: int = 1, variant_id: int | None = None) -> dict:
    if qty <= 0:
        raise OrderError("数量必须大于 0")
    with get_db() as conn:
        _ensure_editable(conn, order_id)
        p = conn.execute(
            "SELECT * FROM products WHERE id = ? AND active = 1", (product_id,)
        ).fetchone()
        if not p:
            raise OrderError(f"商品不存在或已下架: {product_id}")

        name, unit_cents, stock = p["name"], p["price_cents"], p["stock"]
        if variant_id is not None:
            v = conn.execute(
                "SELECT * FROM product_variants WHERE id = ? AND product_id = ? AND active = 1",
                (variant_id, product_id),
            ).fetchone()
            if not v:
                raise OrderError(f"该商品没有这个规格: {variant_id}")
            name = f"{p['name']}({v['label']})"
            unit_cents, stock = v["price_cents"], v["stock"]
        if stock < qty:
            raise OrderError(f"{name} 库存只剩 {stock}")

        exist = conn.execute(
            """SELECT * FROM order_items WHERE order_id = ? AND product_id = ?
               AND variant_id IS ?""",
            (order_id, product_id, variant_id),
        ).fetchone()
        if exist:
            conn.execute(
                "UPDATE order_items SET qty = qty + ? WHERE id = ?", (qty, exist["id"])
            )
        else:
            conn.execute(
                """INSERT INTO order_items (order_id, product_id, variant_id, name, unit_cents, qty)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (order_id, product_id, variant_id, name, unit_cents, qty),
            )
        _recalc_total(conn, order_id)
    return get_order(order_id)


def add_by_barcode(order_id: str, barcode: str, qty: int = 1) -> dict:
    from app.recommend import find_by_barcode
    with get_db() as conn:
        mid = conn.execute(
            "SELECT merchant_id FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
    if not mid:
        raise OrderError(f"订单不存在: {order_id}")
    prod = find_by_barcode(mid["merchant_id"], barcode)
    if not prod:
        raise OrderError(f"条码未入库: {barcode}")
    return add_item(order_id, prod["id"], qty)


def remove_item(order_id: str, product_id: int, variant_id: int | None = None) -> dict:
    with get_db() as conn:
        _ensure_editable(conn, order_id)
        conn.execute(
            """DELETE FROM order_items WHERE order_id = ? AND product_id = ?
               AND variant_id IS ?""",
            (order_id, product_id, variant_id),
        )
        _recalc_total(conn, order_id)
    return get_order(order_id)


def set_qty(order_id: str, product_id: int, qty: int, variant_id: int | None = None) -> dict:
    if qty <= 0:
        return remove_item(order_id, product_id, variant_id)
    with get_db() as conn:
        _ensure_editable(conn, order_id)
        item = conn.execute(
            """SELECT * FROM order_items WHERE order_id = ? AND product_id = ?
               AND variant_id IS ?""",
            (order_id, product_id, variant_id),
        ).fetchone()
        if not item:
            raise OrderError("订单里没有这个商品")
        if item["variant_id"] is not None:
            v = conn.execute(
                "SELECT stock FROM product_variants WHERE id = ?", (item["variant_id"],)
            ).fetchone()
            stock = v["stock"] if v else None
        else:
            p = conn.execute(
                "SELECT stock FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            stock = p["stock"] if p else None
        if stock is not None and stock < qty:
            raise OrderError(f"库存只剩 {stock}")
        conn.execute(
            """UPDATE order_items SET qty = ? WHERE order_id = ? AND product_id = ?
               AND variant_id IS ?""",
            (qty, order_id, product_id, variant_id),
        )
        _recalc_total(conn, order_id)
    return get_order(order_id)


def clear(order_id: str) -> dict:
    with get_db() as conn:
        _ensure_editable(conn, order_id)
        conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        _recalc_total(conn, order_id)
    return get_order(order_id)


def transition(order_id: str, target: str) -> dict:
    with get_db() as conn:
        current = _require_status(conn, order_id, tuple(TRANSITIONS.keys()))
        _check_transition(current, target)
        conn.execute(
            f"UPDATE orders SET status = ?, updated_at = {_now()} WHERE id = ?",
            (target, order_id),
        )
    return get_order(order_id)


def get_order(order_id: str) -> dict:
    with get_db() as conn:
        o = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not o:
            raise OrderError(f"订单不存在: {order_id}")
        items = conn.execute(
            "SELECT product_id, name, unit_cents, qty FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()

    total = sum(i["unit_cents"] * i["qty"] for i in items)
    return {
        "id": o["id"],
        "merchant_id": o["merchant_id"],
        "device_sn": o["device_sn"],
        "status": o["status"],
        "items": [
            {
                "product_id": i["product_id"],
                "name": i["name"],
                "unit_cents": i["unit_cents"],
                "unit_price": f"{i['unit_cents'] / 100:.2f}",
                "qty": i["qty"],
                "subtotal": f"{i['unit_cents'] * i['qty'] / 100:.2f}",
            }
            for i in items
        ],
        "total_cents": total,
        "total": f"{total / 100:.2f}",
        "count": sum(i["qty"] for i in items),
        "created_at": o["created_at"],
    }
