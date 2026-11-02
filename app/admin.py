"""商户后台。

一个能在浏览器里用的商品库管理界面，替代手改数据库。

跑法：
    python3 app/admin.py
然后浏览器打开 http://127.0.0.1:8800

设计上有意做得土一点：原生 JS + fetch，不引框架、不引构建工具。
店里要用的东西，能打开、能改、能存就行，越少依赖越不容易坏。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

# 直接 `python3 app/admin.py` 跑时，sys.path[0] 是 app/，找不到 app.autotag。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from app.autotag import infer
from app.db import init_db
from app.settings import get_scripts, save_scripts

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("CASHIER_DB", str(ROOT / "data" / "cashier.db"))
STATIC_DIR = ROOT / "app" / "static"
QR_PATH = ROOT / "data" / "merchant_qr.png"

# 启动时把库结构补齐（settings 等新表），老库也能平滑升级
init_db(DB_PATH)

# 标签的中文名，跟 recommend.py 的 TAG_ALIASES 保持一致
TAG_LABELS = {
    "child": "小孩",
    "adult": "成人",
    "all": "通用",
    "sweet": "甜",
    "salty": "咸",
    "spicy": "辣",
    "snack": "零食",
    "drink": "下酒",
    "breakfast": "早餐",
    "summer": "解暑",
    "gift": "送礼",
}

app = FastAPI(title="AI 收银员 - 商户后台")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


class VariantIn(BaseModel):
    label: str
    unit: str = "箱"
    pack_qty: int = Field(default=1, ge=1, description="1箱/1件 = 多少个零售单位")
    price: float = Field(ge=0, description="单位：元")
    barcode: str | None = None
    stock: int = Field(default=0, ge=0)
    active: bool = True


class ProductIn(BaseModel):
    name: str
    price: float = Field(ge=0, description="单位：元")
    barcode: str | None = None
    category: str | None = None
    unit: str = "件"
    stock: int = Field(default=0, ge=0)
    active: bool = True
    tags: list[str] = []
    variants: list[VariantIn] = []


class MerchantIn(BaseModel):
    name: str
    greeting: str | None = None


# ─────────────────────────── 页面 ───────────────────────────


@app.get("/", response_class=HTMLResponse)
def index():
    page = STATIC_DIR / "admin.html"
    if not page.exists():
        return HTMLResponse("<h1>缺少页面文件 app/static/admin.html</h1>", status_code=500)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/meta")
def meta():
    return {"tags": TAG_LABELS}


# ─────────────────────────── 商户 ───────────────────────────


@app.get("/api/merchant")
def get_merchant(merchant_id: str = "demo-store"):
    with conn() as c:
        row = c.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,)).fetchone()
        if not row:
            raise HTTPException(404, "商户不存在")
        return dict(row)


@app.put("/api/merchant")
def update_merchant(data: MerchantIn, merchant_id: str = "demo-store"):
    with conn() as c:
        c.execute(
            "UPDATE merchants SET name = ?, greeting = COALESCE(?, greeting) WHERE id = ?",
            (data.name, data.greeting, merchant_id),
        )
    return {"ok": True}


@app.post("/api/merchant/qr")
async def upload_qr(file: UploadFile = File(...), merchant_id: str = "demo-store"):
    """上传商户收款码。存成 PNG，屏幕渲染时直接贴进付款页。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件是空的")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "文件太大了，收款码图片不该超过 5MB")

    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(data)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"这不是一张能识别的图片: {e}")

    QR_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 统一转 PNG：JPEG 压缩会破坏二维码的方块边缘，导致扫不出来
    img.save(QR_PATH, format="PNG", optimize=True)

    with conn() as c:
        c.execute(
            "UPDATE merchants SET qr_image_path = ? WHERE id = ?",
            (str(QR_PATH), merchant_id),
        )
    return {"ok": True, "size": img.size, "path": str(QR_PATH)}


@app.get("/api/merchant/qr")
def get_qr(merchant_id: str = "demo-store"):
    with conn() as c:
        row = c.execute(
            "SELECT qr_image_path FROM merchants WHERE id = ?", (merchant_id,)
        ).fetchone()
    p = row["qr_image_path"] if row else None
    if not p or not os.path.exists(p):
        return {"exists": False}
    with open(p, "rb") as f:
        return Response(f.read(), media_type="image/png")


# ─────────────────────────── 商品 ───────────────────────────


def _product_row_to_dict(row: sqlite3.Row, tags: list[str], variants: list[dict] | None = None) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price_cents"] / 100,
        "price_cents": row["price_cents"],
        "barcode": row["barcode"],
        "category": row["category"],
        "unit": row["unit"],
        "stock": row["stock"],
        "active": bool(row["active"]),
        "tags": tags,
        "variants": variants or [],
    }


def _variants_of(c: sqlite3.Connection, pid: int) -> list[dict]:
    return [
        {
            "id": v["id"],
            "label": v["label"],
            "unit": v["unit"],
            "pack_qty": v["pack_qty"],
            "price": v["price_cents"] / 100,
            "barcode": v["barcode"],
            "stock": v["stock"],
            "active": bool(v["active"]),
        }
        for v in c.execute(
            "SELECT * FROM product_variants WHERE product_id = ? ORDER BY id", (pid,)
        ).fetchall()
    ]


def _save_variants(c: sqlite3.Connection, pid: int, variants: list[VariantIn]) -> None:
    """整存整取：先清后写，规格以本次提交为准。"""
    c.execute("DELETE FROM product_variants WHERE product_id = ?", (pid,))
    for v in variants:
        if not v.label.strip():
            continue
        c.execute(
            """INSERT INTO product_variants
                   (product_id, label, unit, pack_qty, price_cents, barcode, stock, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                v.label.strip(),
                v.unit or "箱",
                v.pack_qty,
                int(round(v.price * 100)),
                v.barcode or None,
                v.stock,
                1 if v.active else 0,
            ),
        )


@app.get("/api/products")
def list_products(q: str = "", tag: str = "", merchant_id: str = "demo-store"):
    sql = "SELECT * FROM products WHERE merchant_id = ?"
    args: list = [merchant_id]
    if q:
        sql += " AND (name LIKE ? OR barcode LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if tag:
        sql += " AND id IN (SELECT product_id FROM product_tags WHERE tag = ?)"
        args.append(tag)
    sql += " ORDER BY id"

    with conn() as c:
        rows = c.execute(sql, args).fetchall()
        out = []
        for r in rows:
            tg = [
                x["tag"]
                for x in c.execute(
                    "SELECT tag FROM product_tags WHERE product_id = ? ORDER BY tag", (r["id"],)
                ).fetchall()
            ]
            out.append(_product_row_to_dict(r, tg, _variants_of(c, r["id"])))
    return out


@app.post("/api/products")
def create_product(p: ProductIn, merchant_id: str = "demo-store"):
    if not p.name.strip():
        raise HTTPException(400, "商品名不能为空")
    # 老板只填名字和价格时，按名字自动补标签——没标签的商品顾客问「冰的」
    # 「给小孩的」时会被漏掉，等于录了也卖不动。
    tags = list(p.tags) or infer(p.name)
    auto = not p.tags
    with conn() as c:
        cur = c.execute(
            """INSERT INTO products (merchant_id, name, price_cents, barcode, category, unit, stock, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                merchant_id,
                p.name.strip(),
                int(round(p.price * 100)),
                p.barcode or None,
                p.category or None,
                p.unit or "件",
                p.stock,
                1 if p.active else 0,
            ),
        )
        pid = cur.lastrowid
        for t in tags:
            c.execute("INSERT OR IGNORE INTO product_tags (product_id, tag) VALUES (?, ?)", (pid, t))
        _save_variants(c, pid, p.variants)
    return {"ok": True, "id": pid, "tags": tags, "auto_tagged": auto}


@app.put("/api/products/{pid}")
def update_product(pid: int, p: ProductIn):
    if not p.name.strip():
        raise HTTPException(400, "商品名不能为空")
    tags = list(p.tags) or infer(p.name)
    auto = not p.tags
    with conn() as c:
        row = c.execute("SELECT id FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "商品不存在")
        c.execute(
            """UPDATE products SET name = ?, price_cents = ?, barcode = ?, category = ?,
                   unit = ?, stock = ?, active = ? WHERE id = ?""",
            (
                p.name.strip(),
                int(round(p.price * 100)),
                p.barcode or None,
                p.category or None,
                p.unit or "件",
                p.stock,
                1 if p.active else 0,
                pid,
            ),
        )
        c.execute("DELETE FROM product_tags WHERE product_id = ?", (pid,))
        for t in tags:
            c.execute("INSERT OR IGNORE INTO product_tags (product_id, tag) VALUES (?, ?)", (pid, t))
        _save_variants(c, pid, p.variants)
    return {"ok": True, "tags": tags, "auto_tagged": auto}


@app.delete("/api/products/{pid}")
def delete_product(pid: int):
    """删除商品。历史订单里的快照不受影响（order_items 存了名称和单价）。"""
    with conn() as c:
        row = c.execute("SELECT id FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "商品不存在")
        c.execute("DELETE FROM products WHERE id = ?", (pid,))
    return {"ok": True}


# ─────────────────────────── 订单 ───────────────────────────


@app.get("/api/orders")
def list_orders(limit: int = 30, merchant_id: str = "demo-store"):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE merchant_id = ? ORDER BY created_at DESC LIMIT ?",
            (merchant_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            items = c.execute(
                "SELECT name, unit_cents, qty FROM order_items WHERE order_id = ? ORDER BY id",
                (r["id"],),
            ).fetchall()
            out.append(
                {
                    "id": r["id"],
                    "status": r["status"],
                    "total": r["total_cents"] / 100,
                    "created_at": r["created_at"],
                    "items": [
                        {
                            "name": i["name"],
                            "qty": i["qty"],
                            "subtotal": i["unit_cents"] * i["qty"] / 100,
                        }
                        for i in items
                    ],
                }
            )
    return out


@app.get("/api/stats")
def stats(merchant_id: str = "demo-store"):
    with conn() as c:
        n_products = c.execute(
            "SELECT COUNT(*) FROM products WHERE merchant_id = ? AND active = 1", (merchant_id,)
        ).fetchone()[0]
        closed = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_cents),0) FROM orders WHERE merchant_id = ? AND status = 'closed'",
            (merchant_id,),
        ).fetchone()
        today = c.execute(
            """SELECT COUNT(*), COALESCE(SUM(total_cents),0) FROM orders
               WHERE merchant_id = ? AND status = 'closed'
                 AND date(created_at) = date('now','localtime')""",
            (merchant_id,),
        ).fetchone()
    return {
        "products": n_products,
        "orders_total": closed[0],
        "revenue_total": closed[1] / 100,
        "orders_today": today[0],
        "revenue_today": today[1] / 100,
    }


class ScriptsIn(BaseModel):
    greeting: str | None = None
    payment_guide: str | None = None
    farewell: str | None = None


@app.get("/api/scripts")
def scripts_get():
    return {"scripts": get_scripts(), "defaults": {
        "payment_guide_note": "付款引导语里 {total} 会被替换成实际金额"
    }}


@app.put("/api/scripts")
def scripts_put(data: ScriptsIn):
    saved = save_scripts(data.model_dump(exclude_none=True))
    return {"scripts": saved}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("ADMIN_PORT", "8800"))
    print(f"商户后台: http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
