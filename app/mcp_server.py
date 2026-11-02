"""MCP 服务：把商品库和订单能力暴露给小智的大模型。

这是「第一阶段」的核心资产——语音走小智官方云（ASR/LLM/TTS 全部现成），
只有商品查询和订单操作走本地。通过小智控制台的 MCP 接入点（wss://）连上去。

设计原则：
1. 工具返回要短。每个返回控制在 1KB 内，别把整个商品表塞给模型
2. 价格只从数据库出，工具不提供「报价」能力，模型无法编造价格
3. 工具名和 docstring 必须让模型清楚「什么时候该调」，这不是给人看的
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.order import (  # noqa: E402
    OrderError,
    add_item,
    close_active_order,
    get_active_order,
    get_order,
    remove_item,
    set_qty,
    transition,
)
from app.recommend import (  # noqa: E402
    find_by_barcode,
    fuzzy_search,
    recommend,
    similar_search,
)
from app.settings import get_scripts  # noqa: E402

MERCHANT_ID = os.getenv("CASHIER_MERCHANT_ID", "demo-store")
DEVICE_SN = os.getenv("CASHIER_DEVICE_SN", "dc:0a:69:53:0c:88")


def _lan_ip() -> str:
    """本机在局域网里的地址。设备要靠它来下载屏幕图片。"""
    ip = os.getenv("CASHIER_LAN_IP")
    if ip:
        return ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        addr = s.getsockname()[0]
        s.close()
        return addr
    except Exception:
        return "127.0.0.1"


# 屏幕图片服务的端口。设备访问不到 localhost，必须是局域网 IP。
SCREEN_PORT = int(os.getenv("SCREEN_PORT", "8801"))
SCREEN_BASE = os.getenv("SCREEN_BASE_URL") or f"http://{_lan_ip()}:{SCREEN_PORT}"
SCREEN_LOCAL = f"http://127.0.0.1:{SCREEN_PORT}"


def _show(path: str) -> str:
    """把某个画面登记到屏幕服务上，设备轮询到后会自动常驻显示。

    之前是让模型自己调 self.screen.preview_image——但那是设备端 user-only
    工具，云端模型既看不到也调不了，而且 preview 5 秒就隐藏。
    现在改成服务端登记、固件轮询常驻显示，模型只管调本服务端的工具。
    """
    import json as _json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{SCREEN_LOCAL}/show",
            data=_json.dumps({"path": path}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return "屏幕已更新。"
            return f"屏幕更新失败：{resp.read().decode(errors='replace')}"
    except Exception as e:
        return f"屏幕更新失败（屏幕服务没开？）：{e}"


mcp = FastMCP("xiaozhi-cashier")


def _fmt_products(items: list[dict]) -> str:
    if not items:
        return "没有找到符合条件的商品。"
    lines = [f"找到 {len(items)} 个："]
    for it in items:
        line = f"{it['id']}.{it['name']} ¥{it['price']}/{it['unit']}"
        if it.get("variants"):
            specs = "；".join(
                f"{v['label']}(含{v['pack_qty']}{it['unit']}) ¥{v['price']}/{v['unit']} [规格号{v['id']}]"
                for v in it["variants"]
            )
            line += f"；另有：{specs}"
        lines.append(line)
    return "\n".join(lines)


def _fmt_order(o: dict) -> str:
    if not o["items"]:
        return "当前订单是空的。"
    lines = [f"订单({o['status']})："]
    for it in o["items"]:
        lines.append(f"{it['name']} ¥{it['unit_price']}×{it['qty']}={it['subtotal']}")
    lines.append(f"合计 ¥{o['total']}")
    return "\n".join(lines)


def _current_order_id() -> str:
    return get_active_order(MERCHANT_ID, DEVICE_SN)


@mcp.tool()
def search_products(query: str, limit: int = 4) -> str:
    """按顾客的口语描述查找商品，返回候选清单。

    什么时候用：顾客说出想买什么、或者描述偏好时。例如「给小孩买点零食」
    「来点下酒的」「有什么甜的」「有没有冰的饮料」。
    query 直接填顾客原话或你总结的偏好词，例如「小孩 零食」「下酒」「甜」。
    注意：本工具只返回候选商品和真实价格，不要自己编造商品或价格。
    """
    # 顾客指名道姓要某样东西（「可乐」「乐事薯片」）时，名称匹配才是对的答案。
    # 之前先走标签推荐，导致「可乐」被拆成不认识的口语、退化成"全店最便宜的四个"，
    # 顾客会听到一堆小布丁和棒棒糖。所以名称命中要排在最前面。
    kw = query.strip()
    named = fuzzy_search(MERCHANT_ID, kw, limit=limit)
    if named:
        return _fmt_products(named)

    # 名称差一个字也要认得：老板把「冰淇淋」录成「冰淇凌」，顾客说的还是
    # 冰淇淋。真人店员不会因为错一个字就听不懂。
    alike = similar_search(MERCHANT_ID, kw, limit=limit)
    if alike:
        return _fmt_products(alike)

    items = recommend(MERCHANT_ID, query, limit=limit)
    if items:
        return _fmt_products(items)
    return "没有找到符合条件的商品。可以问顾客想要什么口味，或者推荐店里常卖的几样。"


@mcp.tool()
def lookup_barcode(barcode: str) -> str:
    """用条码查询商品和价格。

    什么时候用：顾客把商品拿到摄像头前询问价格，并且识别出了条码数字时。
    这是最可靠的查价方式，命中后必须使用返回的价格，不允许自行估算。
    """
    p = find_by_barcode(MERCHANT_ID, barcode)
    if not p:
        return f"条码 {barcode} 未入库。请让顾客描述一下是什么商品。"
    return f"{p['id']}.{p['name']} ¥{p['price']}/{p['unit']}（库存{p['stock']}）"


@mcp.tool()
def add_to_order(product_id: int, qty: int = 1, variant_id: int = 0) -> str:
    """把商品加入当前订单。

    什么时候用：顾客明确说要买某个商品之后。product_id 必须是
    search_products 或 lookup_barcode 返回的编号，不能自己造。
    如果顾客只是问价格、还没说要买，不要调用本工具。
    顾客要整箱/整件时，把 search_products 返回的对应 [规格号] 填到
    variant_id（例如来一箱 → variant_id=规格号）；买零售单位（包/瓶）时
    variant_id 保持 0 不填。
    """
    try:
        o = add_item(_current_order_id(), product_id, qty, variant_id or None)
        return _fmt_order(o)
    except OrderError as e:
        return f"加购失败：{e}"


@mcp.tool()
def remove_from_order(product_id: int, variant_id: int = 0) -> str:
    """从当前订单里删除某个商品。

    什么时候用：顾客说不要了、拿掉、退掉某样东西。
    如果删的是整箱/整件规格，带上加购时用的 variant_id。
    """
    try:
        o = remove_item(_current_order_id(), product_id, variant_id or None)
        return _fmt_order(o)
    except OrderError as e:
        return f"删除失败：{e}"


@mcp.tool()
def change_quantity(product_id: int, qty: int, variant_id: int = 0) -> str:
    """修改订单中某个商品的数量。

    什么时候用：顾客说要两瓶、再来一个、只要一个。
    qty 填修改后的总数，不是增量。要买 3 个就传 3。
    如果改的是整箱/整件规格，带上加购时用的 variant_id。
    """
    try:
        o = set_qty(_current_order_id(), product_id, qty, variant_id or None)
        return _fmt_order(o)
    except OrderError as e:
        return f"修改失败：{e}"


@mcp.tool()
def get_current_order() -> str:
    """查看当前订单的内容和合计金额。

    什么时候用：顾客问「我现在买了什么」「一共多少钱」，或者你需要在
    确认、结账之前复述一遍订单时。
    """
    return _fmt_order(get_order(_current_order_id()))


@mcp.tool()
def show_order_screen() -> str:
    """把当前订单显示到设备屏幕上。

    什么时候用：每次加购、删单、改数量之后都应该调一次，让顾客能看见
    自己买了什么、一共多少钱。顾客问「我买了什么」时也调它。
    屏幕会常驻显示，直到下一次换画面。
    """
    oid = _current_order_id()
    o = get_order(oid)
    if not o["items"]:
        return "订单还是空的，屏幕上没什么可显示。先帮顾客挑商品。"
    return _show(f"/order/{oid}.png")


@mcp.tool()
def show_idle_screen() -> str:
    """结束当前这一单，把屏幕切回待客页（欢迎光临）。

    什么时候用：顾客没买东西就走了、或者接待下一位之前。
    调用后这一单就归档了，下一位顾客会开一张新单。
    顾客付完款要用 mark_paid（它会顺带说送客语并切回待客页）。
    """
    closed = close_active_order(MERCHANT_ID, DEVICE_SN)
    head = "这一单已归档"
    if closed and closed["items"]:
        head += f"（{closed['count']} 件、¥{closed['total']}）"
    return f"{head}，屏幕切回待客状态。\n{_show('/idle.png')}"


@mcp.tool()
def checkout() -> str:
    """确认订单，进入收款环节，并把收款二维码显示到屏幕上（常驻）。

    什么时候用：顾客明确表示买完了、就要这些、可以结账了。
    调用前建议先复述一遍订单金额让顾客确认，避免误操作。
    返回里带付款引导语，请自然地说出来引导顾客扫码；顾客说付好了
    就调 mark_paid。
    """
    oid = _current_order_id()
    o = get_order(oid)
    if not o["items"]:
        return "订单是空的，没有可结账的商品。"
    try:
        o = transition(oid, "confirmed")
        o = transition(oid, "pay_shown")
    except OrderError as e:
        return f"结账失败：{e}"
    guide = get_scripts()["payment_guide"].replace("{total}", f"{o['total']}")
    return (
        f"订单已确认，应付 ¥{o['total']}，收款二维码已显示在屏幕上。\n{_show(f'/pay/{oid}.png')}\n"
        f"引导语（请用自己的语气说，别念稿）：{guide}"
    )


@mcp.tool()
def mark_paid() -> str:
    """顾客付完款后调用：把这一单结掉，屏幕切回待客页，并拿到送客语。

    什么时候用：顾客说「付好了」「付完了」「扫过了」。
    不要在顾客还没说付款完成时提前调用。
    就算之前忘了调 checkout，也会自动把订单状态补齐到已结清。
    """
    oid = _current_order_id()
    o = get_order(oid)
    if o["status"] == "closed":
        return "这一单已经结过了。"
    # 状态链自动补齐：open -> confirmed -> pay_shown -> closed
    chain = {"open": ("confirmed", "pay_shown"), "confirmed": ("pay_shown",)}
    try:
        for step in chain.get(o["status"], ()):
            o = transition(oid, step)
        o = transition(oid, "closed")
    except OrderError as e:
        return f"结单失败：{e}"
    farewell = get_scripts()["farewell"]
    return (
        f"订单 ¥{o['total']} 已结清，屏幕已切回待客页。\n{_show('/idle.png')}\n"
        f"送客语（请用自己的语气说，别念稿）：{farewell}"
    )


@mcp.tool()
def end_service() -> str:
    """顾客走了但没买东西时调用：作废这一单，屏幕切回待客页，准备接待下一位。

    什么时候用：
    - 顾客说「我先走了」「就随便看看」「下次再来」
    - 顾客明显已经离开（叫几声都不回应）
    - 顾客说「不要了」「算了不买了」
    顾客付完款离开要用 mark_paid，不要用这个。
    调用后店里空了也没关系：有人进来设备会自动迎宾，你正常接待就行。
    """
    closed = close_active_order(MERCHANT_ID, DEVICE_SN)
    if closed and closed["items"]:
        head = f"上一单（{closed['count']} 件、¥{closed['total']}）已作废归档"
    else:
        head = "没有未完成的订单"
    farewell = get_scripts()["farewell"]
    return (
        f"{head}，屏幕已切回待客页，可以接待下一位顾客了。\n{_show('/idle.png')}\n"
        f"顾客临走时可以说一句送客语（用自己的语气，别念稿）：{farewell}"
    )


@mcp.tool()
def get_service_scripts() -> str:
    """获取老板在后台预设的服务话术：欢迎语、付款引导语、送客语。

    什么时候用：会话刚开始、或需要按老板的口径跟顾客说话时。
    返回的三条话术请用自己的语气自然表达，不要一字一句念稿。
    """
    s = get_scripts()
    return (
        f"欢迎语：{s['greeting']}\n"
        f"付款引导语（{{total}} 换成实际金额）：{s['payment_guide']}\n"
        f"送客语：{s['farewell']}"
    )


if __name__ == "__main__":
    # 顺手把屏幕图片服务也起起来，这样只需要跑一个进程
    from app.screen_server import serve_in_thread

    try:
        serve_in_thread()
        print(f"[mcp] 屏幕服务已启动: {SCREEN_BASE}/idle.png", file=sys.stderr)
    except OSError as e:
        print(f"[mcp] 屏幕服务启动失败（端口可能被占用）: {e}", file=sys.stderr)

    mcp.run(transport="stdio")
