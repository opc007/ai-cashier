"""样例数据：一家零食铺的商品库。

条码按 EAN-13 规则生成（含正确校验位），可以直接拿去给 zbar 解码测试——
如果校验位算错，解码器会直接拒绝，所以这里必须算对。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db, init_db, yuan  # noqa: E402

MERCHANT_ID = "demo-store"
DEVICE_SN = "dc:0a:69:53:0c:88"

# (名称, 价格元, 分类, 标签, 单位)
PRODUCTS = [
    ("大白兔奶糖", 3.5, "candy", ["child", "sweet"], "包"),
    ("阿尔卑斯棒棒糖", 1.5, "candy", ["child", "sweet"], "支"),
    ("旺仔牛奶 245ml", 4.5, "drink", ["child", "sweet", "breakfast"], "罐"),
    ("蒙牛纯牛奶 250ml", 3.5, "drink", ["child", "adult", "breakfast"], "盒"),
    ("乐事薯片 原味", 6.0, "snack", ["adult", "salty", "snack"], "包"),
    ("可口可乐 330ml", 3.0, "drink", ["adult", "sweet", "summer"], "罐"),
    ("青岛啤酒 330ml", 5.0, "beer", ["adult", "drink"], "罐"),
    ("油炸花生米", 4.0, "nut", ["adult", "salty", "drink"], "包"),
    ("卤鸭脖", 12.0, "snack", ["adult", "spicy", "drink"], "份"),
    ("雪碧 330ml", 3.0, "drink", ["adult", "sweet", "summer"], "罐"),
    ("旺旺雪饼", 5.0, "snack", ["child", "salty", "snack"], "包"),
    ("喜之郎果冻", 2.0, "candy", ["child", "sweet"], "个"),
    ("奥利奥饼干", 7.5, "biscuit", ["child", "adult", "sweet"], "包"),
    ("康师傅红烧牛肉面", 4.5, "noodle", ["adult", "snack"], "桶"),
    ("洽洽香瓜子", 6.5, "nut", ["adult", "salty", "drink"], "包"),
    ("王老吉 310ml", 4.0, "drink", ["adult", "summer"], "罐"),
    ("农夫山泉 550ml", 2.0, "drink", ["all"], "瓶"),
    ("伊利小布丁", 1.0, "icecream", ["child", "sweet", "summer"], "支"),
    ("德芙巧克力", 8.0, "candy", ["adult", "sweet", "gift"], "排"),
    ("卫龙辣条", 2.5, "snack", ["child", "adult", "spicy"], "包"),
    ("红星二锅头 100ml", 8.0, "beer", ["adult", "drink"], "瓶"),
    ("乡巴佬卤蛋", 2.0, "snack", ["adult", "salty"], "个"),
]


def ean13_checksum(first12: str) -> str:
    """按 EAN-13 规则计算校验位：奇数位权重 1，偶数位权重 3"""
    total = 0
    for i, ch in enumerate(first12):
        d = int(ch)
        total += d if i % 2 == 0 else d * 3
    return str((10 - total % 10) % 10)


def make_barcode(seq: int) -> str:
    """690 是中国大陆前缀，后 9 位为流水号"""
    body = f"690{seq:09d}"
    return body + ean13_checksum(body)


def seed(rebuild: bool = False) -> None:
    init_db()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE merchant_id = ?", (MERCHANT_ID,)
        ).fetchone()["n"]
        if existing and not rebuild:
            print(f"已存在 {existing} 个商品，跳过灌数据（要重建加 --rebuild）")
            return
        if rebuild:
            conn.execute("DELETE FROM product_tags")
            conn.execute("DELETE FROM products WHERE merchant_id = ?", (MERCHANT_ID,))
            conn.execute("DELETE FROM orders WHERE merchant_id = ?", (MERCHANT_ID,))

        conn.execute(
            "INSERT OR IGNORE INTO merchants (id, name, greeting) VALUES (?, ?, ?)",
            (MERCHANT_ID, "阿叔零食铺（演示）", "欢迎光临，老板需要点什么？"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO devices (device_sn, merchant_id) VALUES (?, ?)",
            (DEVICE_SN, MERCHANT_ID),
        )
        conn.execute(
            """INSERT OR IGNORE INTO llm_configs
               (merchant_id, provider, base_url, model, temperature)
               VALUES (?, 'deepseek', 'https://api.deepseek.com', 'deepseek-chat', 0.7)""",
            (MERCHANT_ID,),
        )

        for i, (name, price, category, tags, unit) in enumerate(PRODUCTS, start=1):
            cur = conn.execute(
                """INSERT INTO products
                   (merchant_id, name, price_cents, barcode, category, unit, stock)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (MERCHANT_ID, name, round(price * 100), make_barcode(i), category, unit, 50),
            )
            pid = cur.lastrowid
            conn.executemany(
                "INSERT OR IGNORE INTO product_tags (product_id, tag) VALUES (?, ?)",
                [(pid, t) for t in tags],
            )

        total = conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE merchant_id = ?", (MERCHANT_ID,)
        ).fetchone()["n"]
        print(f"灌入完成：{total} 个商品，商户 {MERCHANT_ID}，设备 {DEVICE_SN}")


def dump() -> None:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name, p.price_cents, p.barcode, p.unit,
                      GROUP_CONCAT(t.tag, ' ') AS tags
               FROM products p LEFT JOIN product_tags t ON t.product_id = p.id
               WHERE p.merchant_id = ?
               GROUP BY p.id ORDER BY p.id""",
            (MERCHANT_ID,),
        ).fetchall()
    print(f"{'ID':<4}{'名称':<20}{'价格':>7}  {'条码':<15}{'标签'}")
    print("-" * 74)
    for r in rows:
        print(f"{r['id']:<4}{r['name']:<20}{yuan(r['price_cents']):>7}  {r['barcode']:<15}{r['tags']}")
    print("-" * 74)
    print(f"共 {len(rows)} 项")


if __name__ == "__main__":
    seed(rebuild="--rebuild" in sys.argv)
    dump()
