"""数据库层：SQLite schema 与连接管理。

设计要点：
1. 所有业务表都带 merchant_id —— 现在只服务一家店，但结构为多商户预留，将来不返工
2. 金额一律用「分」存整数，绝不用浮点。收银系统里 0.1 + 0.2 = 0.30000000000000004 是事故
3. 标签用关联表而不是 JSON 字符串，查询干净、能建索引
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cashier.db")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS merchants (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    qr_image_path TEXT,
    greeting      TEXT NOT NULL DEFAULT '欢迎光临，老板需要点什么？',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS devices (
    device_sn   TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    bound_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    barcode     TEXT,
    category    TEXT,
    unit        TEXT NOT NULL DEFAULT '件',
    stock       INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_barcode
    ON products(merchant_id, barcode) WHERE barcode IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_merchant ON products(merchant_id, active);

CREATE TABLE IF NOT EXISTS product_tags (
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    PRIMARY KEY (product_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON product_tags(tag);

-- 批量规格：一个商品除零售单位（包/瓶）外的整箱/整件规格。
-- 主商品行本身就是默认零售规格，这里只存大份规格。
CREATE TABLE IF NOT EXISTS product_variants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,                    -- 规格名：整箱 / 1件
    unit        TEXT NOT NULL DEFAULT '箱',       -- 下单时的计量单位
    pack_qty    INTEGER NOT NULL DEFAULT 1 CHECK (pack_qty > 0),  -- 1箱=多少包
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    barcode     TEXT,
    stock       INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id, active);

CREATE TABLE IF NOT EXISTS llm_configs (
    merchant_id TEXT PRIMARY KEY REFERENCES merchants(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL DEFAULT 'deepseek',
    base_url    TEXT NOT NULL DEFAULT 'https://api.deepseek.com',
    api_key     TEXT,
    model       TEXT NOT NULL DEFAULT 'deepseek-chat',
    temperature REAL NOT NULL DEFAULT 0.7,
    max_tokens  INTEGER NOT NULL DEFAULT 512
);

CREATE TABLE IF NOT EXISTS orders (
    id          TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    device_sn   TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    total_cents INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_orders_merchant ON orders(merchant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
    name       TEXT NOT NULL,
    unit_cents INTEGER NOT NULL,
    qty        INTEGER NOT NULL DEFAULT 1 CHECK (qty > 0)
);

CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT,
    device_sn   TEXT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_conv_merchant ON conversations(merchant_id, created_at DESC);
"""

# 订单状态机：open -> confirmed -> pay_shown -> closed，任意态可 cancelled
ORDER_STATES = ("open", "confirmed", "pay_shown", "closed", "cancelled")


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db(db_path: str = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """老库升级：给已有的 order_items 补 variant_id 列（新库由 SCHEMA 直接建好）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(order_items)").fetchall()}
    if "variant_id" not in cols:
        conn.execute(
            "ALTER TABLE order_items ADD COLUMN variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL"
        )


def yuan(cents: int) -> str:
    """分 -> 元字符串，用于展示"""
    return f"{cents / 100:.2f}"


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {DB_PATH}")
