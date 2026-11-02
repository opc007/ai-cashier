#!/usr/bin/env python3
"""小智 AI 收银员 - 屏幕页面渲染器

把设备屏幕当成一块「服务器渲染的幻灯片」：所有页面用 PIL 合成成图片，
再通过 MCP 工具 self.screen.preview_image（参数只有一个 url）推给设备全屏显示。

用法:
    python3 render_screen.py pay --amount 28.50 --out ./out/pay.png
    python3 render_screen.py pay --amount 28.50 --qr ./merchant_qr.png --out ./out/pay_real.png
    python3 render_screen.py idle --out ./out/idle.png
    python3 render_screen.py order --out ./out/order.png
"""

import argparse
import os
import sys

import qrcode
from PIL import Image, ImageDraw, ImageFont

# macOS 中文黑体，index 0 = W3(常规) / 1 = W6(粗)
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FALLBACK_FONTS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

INK = (26, 26, 28)
MUTED = (128, 128, 132)
ACCENT = (198, 40, 40)
PAPER = (250, 250, 248)
BAR = (28, 28, 30)


def _font(size, bold=False):
    path = FONT_PATH if os.path.exists(FONT_PATH) else FALLBACK_FONTS[0]
    try:
        return ImageFont.truetype(path, size, index=1 if bold else 0)
    except Exception:
        return ImageFont.truetype(path, size)


def make_qr(data, box_size=10, border=3):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _canvas(w, h):
    img = Image.new("RGB", (w, h), PAPER)
    return img, ImageDraw.Draw(img)


def render_pay(amount, qr_img, w=240, h=320, hint="付款后请告知店员"):
    """收款页：顶栏 + 金额 + 二维码 + 底部提示"""
    img, d = _canvas(w, h)

    bar_h = 28
    d.rectangle([0, 0, w, bar_h], fill=BAR)
    d.text((w // 2, bar_h // 2), "扫码付款", font=_font(14), fill="white", anchor="mm")

    d.text((w // 2, 46), "应付金额", font=_font(12), fill=MUTED, anchor="mm")
    # 调用方可能传 float，也可能传已经格式化好的字符串（订单接口里的 total 就是
    # 字符串），这里统一转一次，免得哪天又多一个「Unknown format code 'f'」
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        amt = 0.0
    d.text((w // 2, 76), f"¥{amt:.2f}", font=_font(30, bold=True), fill=ACCENT, anchor="mm")

    qr_size = h - 124
    qr_resized = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    qx = (w - qr_size) // 2
    qy = 100
    img.paste(qr_resized, (qx, qy))

    d.text((w // 2, h - 12), hint, font=_font(10), fill=MUTED, anchor="mm")
    return img


def render_idle(w=240, h=320):
    """待客页：欢迎光临 + 引导语"""
    img, d = _canvas(w, h)

    bar_h = 28
    d.rectangle([0, 0, w, bar_h], fill=BAR)
    d.text((w // 2, bar_h // 2), "营业中", font=_font(14), fill="white", anchor="mm")

    d.text((w // 2, 104), "欢迎光临", font=_font(34, bold=True), fill=INK, anchor="mm")
    d.text((w // 2, 152), "老板需要点什么？", font=_font(17), fill=INK, anchor="mm")

    d.line([(60, 186), (w - 60, 186)], fill=(210, 210, 208), width=1)

    lines = ["直接说出想要的东西", "我会帮你推荐", "选好了说「就这些」"]
    y = 210
    for ln in lines:
        d.text((w // 2, y), ln, font=_font(12), fill=MUTED, anchor="mm")
        y += 24

    return img


def render_order(items, total, w=240, h=320):
    """订单确认页：商品清单 + 合计"""
    img, d = _canvas(w, h)

    bar_h = 28
    d.rectangle([0, 0, w, bar_h], fill=BAR)
    d.text((w // 2, bar_h // 2), "订单确认", font=_font(14), fill="white", anchor="mm")

    y = 48
    for name, price in items[:6]:
        d.text((14, y), name, font=_font(12), fill=INK, anchor="lm")
        d.text((w - 14, y), f"{price:.2f}", font=_font(12), fill=INK, anchor="rm")
        y += 24

    d.line([(14, y + 4), (w - 14, y + 4)], fill=(210, 210, 208), width=1)

    d.text((14, y + 28), "合计", font=_font(13, bold=True), fill=INK, anchor="lm")
    d.text((w - 14, y + 28), f"¥{total:.2f}", font=_font(20, bold=True), fill=ACCENT, anchor="rm")

    d.text((w // 2, h - 40), "确认无误请说「付款」", font=_font(11), fill=MUTED, anchor="mm")
    d.text((w // 2, h - 20), "需要修改直接说", font=_font(11), fill=MUTED, anchor="mm")
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", choices=["pay", "idle", "order"])
    ap.add_argument("--amount", default="28.50")
    ap.add_argument("--qr", help="商户收款码图片路径；不给则生成 demo 码")
    ap.add_argument("--width", type=int, default=240)
    ap.add_argument("--height", type=int, default=320)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = args.out or f"./out/{args.page}_{args.width}x{args.height}.png"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    if args.page == "pay":
        if args.qr:
            if not os.path.exists(args.qr):
                sys.exit(f"找不到收款码图片: {args.qr}")
            qr_img = Image.open(args.qr).convert("RGB")
            if qr_img.width != qr_img.height:
                side = min(qr_img.width, qr_img.height)
                left = (qr_img.width - side) // 2
                top = (qr_img.height - side) // 2
                qr_img = qr_img.crop((left, top, left + side, top + side))
        else:
            qr_img = make_qr("https://example.com/demo-merchant-pay")
        img = render_pay(args.amount, qr_img, args.width, args.height)
    elif args.page == "idle":
        img = render_idle(args.width, args.height)
    else:
        items = [("棒棒糖", 2.0), ("牛奶 250ml", 4.5), ("薯片", 6.0), ("果冻", 3.5)]
        img = render_order(items, sum(p for _, p in items), args.width, args.height)

    img.save(out, "PNG", optimize=True)
    size_kb = os.path.getsize(out) / 1024
    print(f"已生成 {out}  {img.width}x{img.height}  {size_kb:.1f} KB")
    if size_kb > 50:
        print("⚠️  超过 50KB，设备端分配内部 RAM 可能失败，建议降低色深或缩小尺寸")


if __name__ == "__main__":
    main()
