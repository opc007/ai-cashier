"""推荐引擎。

核心原则：这里只负责「按标签查候选」，不负责说话。
话术交给 LLM，价格和库存必须来自数据库。分工不能混。

为什么不用向量检索：
商品是结构化数据，SQL 查「儿童 + 库存>0」能 100% 查对。
向量相似度是「差不多」的猜测，在收银场景里意味着可能推荐没货的东西、
或者把价格张冠李戴。能用 SQL 查对的，绝不用向量猜。
"""

from __future__ import annotations

import re
import sqlite3
from typing import Iterable

from app.db import get_db

# 顾客口语 -> 标准标签。LLM 若输出标准标签则直接通过，输出口语则由这里兜底。
TAG_ALIASES = {
    "child": ["小孩", "小朋友", "孩子", "儿童", "小娃娃", "宝宝", "小孩儿"],
    "adult": ["大人", "自己吃", "成年", "成人", "我吃", "大人吃"],
    "elder": ["老人", "爷爷", "奶奶", "长辈"],
    "sweet": ["甜", "甜的", "甜口", "糖"],
    "salty": ["咸", "咸的", "咸口"],
    "spicy": ["辣", "辣的", "辣口", "重口"],
    "sour": ["酸", "酸的"],
    "drink": ["下酒", "配酒", "喝酒", "下酒菜", "佐酒"],
    "snack": ["解馋", "零食", "嘴馋", "垫垫", "随便吃", "吃的"],
    "summer": ["解暑", "冰", "冰的", "凉的", "夏天", "口渴",
               "雪糕", "冰棍", "冷饮", "冰淇淋", "冰激凌", "冰淇凌", "冰激淋"],
    "breakfast": ["早餐", "早上吃", "早饭"],
    "gift": ["送礼", "礼物", "送人", "伴手礼"],
}

VALID_TAGS = set(TAG_ALIASES.keys()) | {"all"}

# 标签分两类，这个区分是推荐质量的关键：
#   硬标签（人群）—— 顾客说「给小孩的」，那大人的东西就不该出现，必须满足
#   软标签（口味/场景）—— 顾客说「吃的」「甜的」，这是偏好不是门槛，
#                          用来加分排序，不能用来筛掉商品
# 全当过滤条件的后果：说「小孩吃零食」会把没有 snack 标签的牛奶、果冻全剔掉
HARD_TAGS = {"child", "adult", "elder"}
SOFT_TAGS = VALID_TAGS - HARD_TAGS - {"all"}

_ALIAS_TO_TAG = {alias: tag for tag, aliases in TAG_ALIASES.items() for alias in aliases}


def normalize_tags(raw: Iterable[str] | str) -> list[str]:
    """把口语/混合标签归一化成标准标签集合"""
    if isinstance(raw, str):
        parts = re.split(r"[,，、\s]+", raw)
    else:
        parts = list(raw)

    out: set[str] = set()
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        if p in VALID_TAGS:
            out.add(p)
        elif p in _ALIAS_TO_TAG:
            out.add(_ALIAS_TO_TAG[p])
        else:
            for alias, tag in _ALIAS_TO_TAG.items():
                if alias and alias in p:
                    out.add(tag)
                    break
    return sorted(out)


def variants_for(product_id: int) -> list[dict]:
    """商品的批量规格（整箱/整件）。零售规格就是主商品行本身，这里只返回大份的。"""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM product_variants
               WHERE product_id = ? AND active = 1 ORDER BY id""",
            (product_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "unit": r["unit"],
            "pack_qty": r["pack_qty"],
            "price_cents": r["price_cents"],
            "price": f"{r['price_cents'] / 100:.2f}",
            "stock": r["stock"],
        }
        for r in rows
    ]


def _row_to_dict(r, hits: int = 0) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "price_cents": r["price_cents"],
        "price": f"{r['price_cents'] / 100:.2f}",
        "unit": r["unit"],
        "category": r["category"],
        "stock": r["stock"],
        "hits": hits,
        "variants": variants_for(r["id"]),
    }


def _diversify(rows: list[dict], limit: int, per_category: int = 2) -> list[dict]:
    """同一品类最多取 per_category 个，避免全推成一堆糖。
    真实店员推荐会「糖果一个、饮料一个、饼干一个」，给顾客选择空间。"""
    picked: list[dict] = []
    cat_count: dict[str, int] = {}
    overflow: list[dict] = []

    for r in rows:
        cat = r.get("category") or "_"
        if cat_count.get(cat, 0) < per_category:
            picked.append(r)
            cat_count[cat] = cat_count.get(cat, 0) + 1
        else:
            overflow.append(r)
        if len(picked) >= limit:
            return picked

    # 品类不够时用溢出的补满，别让结果比 limit 少
    for r in overflow:
        if len(picked) >= limit:
            break
        picked.append(r)
    return picked


def recommend(
    merchant_id: str,
    tags: Iterable[str] | str,
    limit: int = 5,
    exclude_ids: Iterable[int] = (),
    max_price_cents: int | None = None,
    diversify: bool = True,
) -> list[dict]:
    """按标签检索候选商品。

    硬标签（人群）必须全部满足；软标签（口味/场景）只影响排序。
    排序：软标签命中数降序 -> 价格升序 -> 品类多样性裁剪。
    """
    std = normalize_tags(tags)
    hard = [t for t in std if t in HARD_TAGS]
    soft = [t for t in std if t in SOFT_TAGS]
    exclude = list(exclude_ids)
    fetch_n = limit * 3 if diversify else limit

    params: list = []
    sql = "SELECT p.*, "

    if soft:
        soft_ph = ",".join("?" * len(soft))
        sql += (f"(SELECT COUNT(*) FROM product_tags t "
                f"WHERE t.product_id = p.id AND t.tag IN ({soft_ph})) AS soft_hits ")
        params += soft
    else:
        sql += "0 AS soft_hits "

    sql += "FROM products p WHERE p.merchant_id = ? AND p.active = 1 AND p.stock > 0"
    params.append(merchant_id)

    if hard:
        hard_ph = ",".join("?" * len(hard))
        sql += (f" AND p.id IN (SELECT product_id FROM product_tags "
                f"WHERE tag IN ({hard_ph}) GROUP BY product_id "
                f"HAVING COUNT(DISTINCT tag) = ?)")
        params += hard + [len(hard)]

    if exclude:
        sql += f" AND p.id NOT IN ({','.join('?' * len(exclude))})"
        params += exclude

    if max_price_cents is not None:
        sql += " AND p.price_cents <= ?"
        params.append(max_price_cents)

    sql += " ORDER BY soft_hits DESC, p.price_cents ASC LIMIT ?"
    params.append(fetch_n)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = [_row_to_dict(r, r["soft_hits"]) for r in rows]
    return _diversify(result, limit) if diversify else result[:limit]


def find_by_barcode(merchant_id: str, barcode: str) -> dict | None:
    """条码精确命中。这是最可靠的一条路，命中就别再让模型猜了"""
    with get_db() as conn:
        r = conn.execute(
            """SELECT * FROM products
               WHERE merchant_id = ? AND barcode = ? AND active = 1""",
            (merchant_id, barcode.strip()),
        ).fetchone()
    return _row_to_dict(r) if r else None


def fuzzy_search(merchant_id: str, keyword: str, limit: int = 5) -> list[dict]:
    """按名称模糊查。用于条码失败后的兜底：顾客说「可乐」时找含「可乐」的商品"""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM products
               WHERE merchant_id = ? AND active = 1 AND stock > 0
                 AND name LIKE ?
               ORDER BY price_cents ASC LIMIT ?""",
            (merchant_id, f"%{keyword.strip()}%", limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _bigrams(text: str) -> set[str]:
    """把一个词切成相邻两字片段。中文按字切，用来做错别字容错。"""
    s = re.sub(r"[\s\-_/、，,。.()（）]+", "", text or "")
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similar_search(
    merchant_id: str, keyword: str, limit: int = 5, min_score: float = 0.5
) -> list[dict]:
    """名称近似匹配，专治同音错字和口语说法。

    为什么需要它：老板录商品时把「冰淇淋」打成「冰淇凌」，顾客说的却是
    冰淇淋——差一个字，LIKE 就完全查不到，AI 只能回「我们没有」，顾客
    以为店小。真人店员不会因为错一个字就听不懂，所以这里用两字片段重叠率
    兜一层，重合度够高就算同一个东西。

    「冰淇淋」切成 {冰淇, 淇淋}，商品名含「冰淇」→ 命中 1/2 = 0.5，达标。
    单字词、完全无关的词不会误中（要求重叠率 ≥ 0.5）。
    """
    kw = _bigrams(keyword)
    if not kw:
        return []

    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM products
               WHERE merchant_id = ? AND active = 1 AND stock > 0""",
            (merchant_id,),
        ).fetchall()

    scored: list[tuple[float, int, sqlite3.Row]] = []
    for r in rows:
        hit = len(kw & _bigrams(r["name"]))
        if not hit:
            continue
        score = hit / len(kw)
        if score >= min_score:
            scored.append((score, hit, r))

    # 重合度高的先出，同分按价格便宜的排前面
    scored.sort(key=lambda x: (-x[0], x[2]["price_cents"]))
    return [_row_to_dict(r, hits) for _, hits, r in scored[:limit]]
