"""店铺级设置：服务话术等可配置项。

放数据库而不是写死在代码里，是因为老板改话术不该找程序员。
默认值在这里兜底，后台没改过就用默认。
"""

from __future__ import annotations

from app.db import get_db

# 话术三件套。{total} 是占位符，结账时替换成实际金额。
DEFAULT_SCRIPTS = {
    "greeting": "欢迎光临！想买点什么？店里好吃的好喝的都有。",
    "payment_guide": "好的，一共 {total} 元。请用手机扫屏幕上的二维码付款，付好了跟我说一声。",
    "farewell": "收到啦，付款成功。东西拿好，慢走，欢迎下次再来！",
}

_KEYS = tuple(DEFAULT_SCRIPTS.keys())


def _ensure_table() -> None:
    """settings 表是后加的，老库第一次用到时自动补建。"""
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '', "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
        )


def get_scripts() -> dict[str, str]:
    """读话术，缺的 key 用默认值补齐。"""
    scripts = dict(DEFAULT_SCRIPTS)
    _ensure_table()
    with get_db() as conn:
        for key in _KEYS:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row and row["value"].strip():
                scripts[key] = row["value"]
    return scripts


def save_scripts(data: dict[str, str]) -> dict[str, str]:
    """保存话术。只认认识的 key，空的恢复默认。"""
    _ensure_table()
    with get_db() as conn:
        for key in _KEYS:
            if key not in data:
                continue
            value = (data[key] or "").strip()
            if not value:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                continue
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now', 'localtime')",
                (key, value),
            )
    return get_scripts()
