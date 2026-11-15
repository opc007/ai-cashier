# -*- coding: utf-8 -*-
"""
小智 Live2D 风格角色资源生成器 (设备端 / ESP32-P4 / LVGL)

输入: source/ 下三张一致性立绘 (base / blink / talk)
输出: assets/xiaozhi-live2d/ 下的 RGBA PNG + 透明 GIF + index.json

设计要点:
- 三张原图构图/光照/背景完全一致, 只在眼部/嘴部有差异 -> 局部图层替换合成动画
- 灰渐变背景用「逐行背景色估计 + 边缘连通域」抠成透明, 角色内部白色区域不受影响
- 所有资源统一 280x340 RGBA (P4 800x480 屏, LVGL 按原尺寸居中显示)
"""
import os
import math
import json
import glob
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "source")
OUT = os.path.join(ROOT, "assets", "xiaozhi-live2d")
os.makedirs(OUT, exist_ok=True)

W, H = 280, 340
# 原图 1024x1024 上的局部区域 (x0, y0, x1, y1); 实测眼睛 y~290-350, 嘴 y~420
EYE_BOX = (360, 268, 665, 365)
MOUTH_BOX = (450, 395, 590, 480)
WATERMARK_BOX = (875, 925, 1024, 1024)
# 换算到 280x340 画布后的脸部锚点 (左眼 / 右眼 / 眼线高度)
LX, RX, EY = 120, 172, 106

EMOTIONS = [
    "angry", "confident", "confused", "cool", "crying", "delicious",
    "embarrassed", "funny", "happy", "kissy", "laughing", "loving",
    "neutral", "relaxed", "sad", "shocked", "silly", "sleepy",
    "surprised", "thinking", "winking",
]


def load_sources():
    files = sorted(glob.glob(os.path.join(SRC, "*.png")))
    # 三张图由固定时间戳区分: 基础 / 闭眼(04-37-10) / 张嘴(04-37-37)
    blink = [f for f in files if "04-37-10" in f]
    talk = [f for f in files if "04-37-37" in f]
    base = [f for f in files if f not in (blink + talk)]
    assert base and blink and talk, "source/ 下需要三张立绘 (base / blink / talk)"
    return (Image.open(base[0]).convert("RGB"),
            Image.open(blink[0]).convert("RGB"),
            Image.open(talk[0]).convert("RGB"))


def remove_watermark(arr):
    """右下角生成水印: 用逐行背景色填掉"""
    x0, y0, x1, y1 = WATERMARK_BOX
    for y in range(y0, y1):
        strip = np.concatenate([arr[y, 0:45], arr[y, 980:1024]], axis=0)
        bg = np.median(strip, axis=0).astype(np.uint8)
        arr[y, x0:x1] = bg
    return arr


def estimate_background(arr):
    """逐行估计灰渐变背景色"""
    h, w = arr.shape[:2]
    left = np.median(arr[:, 0:45, :].astype(np.float32), axis=1)
    right = np.median(arr[:, 980:1024, :].astype(np.float32), axis=1)
    bg = (left + right) / 2.0
    # y 方向平滑, 去掉局部光斑干扰
    k = np.ones(41, np.float32) / 41.0
    bg = np.stack([np.convolve(bg[:, c], k, mode="same") for c in range(3)], axis=1)
    return bg[:, np.newaxis, :]  # (H,1,3) 便于广播


_SESSION = None


def get_session():
    """复用 u2netp 语义分割会话 (4.7MB 轻量模型)"""
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session("u2netp")
    return _SESSION


def extract_matte(rgb_arr):
    """语义分割抠掉灰渐变背景。纯颜色分割对这张图无效 (白发/白衣与灰底色值接近)。"""
    from rembg import remove
    arr = remove_watermark(rgb_arr.copy())
    out = remove(Image.fromarray(arr, "RGB"), session=get_session(),
                 alpha_matting=False).convert("RGBA")
    rgba = np.array(out)

    # 语义分割会弱化天线顶端的发光 Wi-Fi 图标, 用色键把发光部分补回来
    x0, y0, x1, y1 = 220, 25, 340, 125
    f = arr.astype(np.float32)
    bg = estimate_background(arr).astype(np.float32)
    d = np.sqrt(np.mean((f - bg) ** 2, axis=2))
    patch = np.clip((d[y0:y1, x0:x1] - 12.0) / 28.0, 0, 1) * 255
    rgba[y0:y1, x0:x1, 3] = np.maximum(rgba[y0:y1, x0:x1, 3], patch.astype(np.uint8))
    return Image.fromarray(rgba, "RGBA")


def crop_fit(img):
    """裁掉左右空白并等比缩放到 W x H 画布 (底部对齐)"""
    a = np.array(img.getchannel("A"))
    ys, xs = np.where(a > 20)
    if len(xs) == 0:
        return img.resize((W, H), Image.LANCZOS)
    x0, x1 = max(0, xs.min() - 12), min(img.width, xs.max() + 12)
    y0, y1 = 0, img.height
    cut = img.crop((x0, y0, x1, y1))
    scale = min(W / cut.width, H / cut.height)
    nw, nh = int(cut.width * scale), int(cut.height * scale)
    cut = cut.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.paste(cut, ((W - nw) // 2, H - nh), cut)
    return canvas


def paste_layer(dst, src, box, feather=7):
    """把 src 的局部区域贴到 dst, 边缘羽化, 保证接缝无痕"""
    x0, y0, x1, y1 = box
    patch = src.crop(box).convert("RGBA")
    pw, ph = patch.size
    mask = Image.new("L", (pw, ph), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([feather, feather, pw - feather, ph - feather], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    tmp = dst.copy()
    tmp.paste(patch, (x0, y0), mask)
    return tmp


def breathe(img, phase, amp=1.0):
    """呼吸: 轻微等比缩放 + 垂直位移 (底部锚定)"""
    s = 1.0 + 0.012 * amp * math.sin(phase)
    dy = int(round(3 * amp * (0.5 - 0.5 * math.cos(phase))))
    nw, nh = int(img.width * s), int(img.height * s)
    scaled = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.paste(scaled, ((W - nw) // 2, H - nh - dy), scaled)
    return canvas


def pose_warp(img, phase, amp=1.0):
    """连续网格变形：头部摆动 / 侧发飘动 / 双臂反相摆动 / 胸腔局部呼吸 / 重心偏移。

    不做图层切割（半身立绘没有分层 PSD，硬切会露接缝），而是构造 2D 平滑权重场，
    用 cv2.remap 对整张 RGBA 做一次连续重采样。各部位用不同频率/相位的正弦叠加，
    避免所有部位同步运动造成机械感；底边锚定防止露出透明缝。
    """
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    def gauss(v, c, sigma):
        return np.exp(-((v - c) / sigma) ** 2)

    # 权重场，坐标来自 280x340 画布实测（半身像：头 ~y20-170，肩 ~y180，
    # 胸 ~y210-280，腰以下到 y340，左右长发与手臂分布在 x<100 / x>180）
    head = gauss(yy, 105, 95)
    lhair = gauss(xx, 55, 48) * np.clip((yy - 110) / 150.0, 0, 1)
    rhair = gauss(xx, 225, 48) * np.clip((yy - 110) / 150.0, 0, 1)
    larm = gauss(xx, 32, 36) * np.clip((yy - 195) / 110.0, 0, 1)
    rarm = gauss(xx, 248, 36) * np.clip((yy - 195) / 110.0, 0, 1)
    chest = gauss(yy, 245, 55) * gauss(xx, 140, 85)

    s_head = math.sin(phase)
    s_sway = math.sin(phase * 0.5 + 0.7)
    s_hair = math.sin(phase + 1.2)
    s_arm = math.sin(phase * 0.75 + 2.1)
    breath = 0.5 - 0.5 * math.cos(phase)

    # 只让局部权重场非零：躯干等其余区域完全不动，帧间差分才能压下来
    dx = (2.6 * amp * s_head * head
          + 1.8 * amp * s_hair * lhair
          - 1.7 * amp * s_hair * rhair
          + 2.4 * amp * s_arm * larm
          - 2.4 * amp * s_arm * rarm)
    dy = (1.4 * amp * math.sin(phase + 0.4) * head
          + 1.8 * amp * breath * chest)
    # 软阈值：把权重场远端的微小位移归零（保持连续，不产生接缝）
    dx = np.sign(dx) * np.maximum(np.abs(dx) - 0.12, 0.0)
    dy = np.sign(dy) * np.maximum(np.abs(dy) - 0.12, 0.0)
    dy = dy * np.clip((h - yy) / 40.0, 0.0, 1.0)  # 底边锚定

    map_x = (xx - dx).astype(np.float32)
    map_y = (yy - dy).astype(np.float32)
    out = cv2.remap(arr, map_x, map_y, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return Image.fromarray(out, "RGBA")


def overlay_decor(img, kind):
    """表情叠加: 眉/泪/汗/心/星/问号/腮红/墨镜 等, 全部绘制在透明图层上"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # 角色在 280x340 画布上的脸部锚点 (由 1024 原图等比换算)
    lx, rx, ey = LX, RX, EY
    blush = (255, 150, 165, 105)

    def arc(points, fill, width=3):
        d.line(points, fill=fill, width=width, joint="curve")

    if kind in ("angry", "confused", "thinking", "sad"):
        # 眉毛: 八字 / 倒八字
        if kind == "angry":
            arc([(lx-14, ey-24), (lx+10, ey-16)], (60, 40, 55, 220), 4)
            arc([(rx-10, ey-16), (rx+14, ey-24)], (60, 40, 55, 220), 4)
        elif kind == "sad":
            arc([(lx-14, ey-16), (lx+10, ey-25)], (90, 80, 100, 190), 3)
            arc([(rx-10, ey-25), (rx+14, ey-16)], (90, 80, 100, 190), 3)
        else:
            arc([(lx-12, ey-25), (lx+10, ey-22)], (90, 80, 100, 170), 3)
            arc([(rx-10, ey-16), (rx+12, ey-25)], (90, 80, 100, 170), 3)

    if kind in ("happy", "embarrassed", "loving", "kissy", "delicious", "laughing"):
        d.ellipse([lx-26, ey+8, lx-4, ey+22], fill=blush)
        d.ellipse([rx+4, ey+8, rx+26, ey+22], fill=blush)

    if kind in ("crying", "sad", "embarrassed"):
        # 泪滴 / 汗滴
        for (x, y) in [(lx-2, ey+16), (rx+2, ey+18)]:
            d.ellipse([x-4, y, x+4, y+13], fill=(150, 220, 255, 210))
        d.ellipse([rx+26, ey-20, rx+34, ey-6], fill=(170, 230, 255, 200))

    if kind == "loving":
        for (x, y, s) in [(40, 70, 14), (232, 105, 11), (58, 150, 9)]:
            d.ellipse([x-s, y-s//2, x, y+s], fill=(255, 110, 150, 210))
            d.ellipse([x, y-s//2, x+s, y+s], fill=(255, 110, 150, 210))
            d.polygon([(x-s, y+s//3), (x+s, y+s//3), (x, y+s+7)], fill=(255, 110, 150, 210))

    if kind in ("surprised", "shocked", "funny", "silly"):
        for (x, y, s) in [(46, 66, 7), (238, 92, 6), (36, 168, 5)]:
            d.line([(x-s, y), (x+s, y)], fill=(255, 225, 120, 220), width=3)
            d.line([(x, y-s), (x, y+s)], fill=(255, 225, 120, 220), width=3)

    if kind == "thinking":
        d.ellipse([210, 36, 240, 62], fill=(255, 255, 255, 190))
        d.ellipse([228, 62, 240, 72], fill=(255, 255, 255, 190))
        d.text((219, 40), "?", fill=(80, 120, 170, 230))

    if kind == "sleepy":
        try:
            font = ImageFont.truetype("arial.ttf", 26)
        except Exception:
            font = ImageFont.load_default()
        d.text((206, 52), "z", font=font, fill=(150, 205, 255, 220))
        d.text((224, 34), "Z", font=font, fill=(150, 205, 255, 235))

    if kind == "cool":
        d.rounded_rectangle([lx-22, ey-14, rx+22, ey+12], radius=8,
                            fill=(25, 32, 48, 215), outline=(90, 200, 245, 235), width=2)
        d.line([(140, ey-14), (140, ey+12)], fill=(90, 200, 245, 180), width=2)

    if kind == "kissy":
        d.ellipse([132, 136, 148, 150], outline=(235, 105, 135, 220), width=3)

    if kind == "confident":
        arc([(lx-14, ey-22), (lx+10, ey-24)], (60, 40, 55, 200), 3)
        arc([(rx-10, ey-24), (rx+14, ey-22)], (60, 40, 55, 200), 3)

    return Image.alpha_composite(img, layer)


def tint(img, color, strength=0.12):
    """轻微整体色调偏移, 用来区分情绪氛围"""
    layer = Image.new("RGBA", img.size, color + (int(255 * strength),))
    return Image.alpha_composite(img, layer)


def to_p(img, transparent_index=255, colors=96, palette=None):
    """RGBA -> P 模式(带透明索引)。palette 非空时复用固定调色板，
    静止区域像素才能逐帧完全一致，GIF 帧间差分才压得下来。"""
    rgb = Image.new("RGB", img.size, (255, 0, 255))
    rgb.paste(img.convert("RGB"), mask=img.getchannel("A").point(lambda a: 255 if a >= 110 else 0))
    if palette is not None:
        p = rgb.quantize(palette=palette, dither=0)
    else:
        p = rgb.quantize(colors=colors, method=Image.MEDIANCUT, dither=0)
    pal = bytearray(p.getpalette() or [])
    if len(pal) < 768:
        pal += bytearray(768 - len(pal))
    pal[transparent_index*3:transparent_index*3+3] = bytes([255, 0, 255])
    p.putpalette(bytes(pal))
    # 强制把透明像素映射到透明索引, 避免量化后洋红残留在画面里
    solid = img.getchannel("A").point(lambda a: 255 if a >= 110 else 0)
    p.paste(255, mask=Image.eval(solid, lambda v: 255 - v))
    p.info["transparency"] = transparent_index
    return p


def save_gif(frames, name, durations, colors=96):
    # 第一帧生成调色板，其余帧复用；避免逐帧量化抖动造成整幅画面都在变
    first = to_p(frames[0], colors=colors)
    palette = first.copy()
    ps = [first] + [to_p(f, colors=colors, palette=palette) for f in frames[1:]]
    path = os.path.join(OUT, name + ".gif")
    ps[0].save(path, save_all=True, append_images=ps[1:], duration=durations,
               loop=0, disposal=2, optimize=True, transparency=255)
    return path


def main():
    base_rgb, blink_rgb, talk_rgb = load_sources()
    base = extract_matte(np.array(base_rgb))
    blink = extract_matte(np.array(blink_rgb))
    talk = extract_matte(np.array(talk_rgb))

    # 抠图检查图: 贴到深蓝设备屏底色上
    dbg = Image.new("RGBA", (1024, 1024), (18, 26, 40, 255))
    dbg.alpha_composite(base)
    dbg.convert("RGB").save(os.path.join(ROOT, "matte_check.png"))

    # ---- 局部图层: 在原始 1024 分辨率上替换, 再统一缩放 ----
    def compose(eyes="base", mouth="base", pose=None, amp=1.0, decor=None):
        img = base.copy()
        if eyes == "blink":
            img = paste_layer(img, blink, EYE_BOX, 9)
        elif eyes == "half":
            b = paste_layer(base.copy(), blink, EYE_BOX, 9)
            img = Image.blend(base, b, 0.55)
        elif eyes == "wink":
            # 左半用闭眼变体 (闭左眼), 右半保留睁眼
            tmp = paste_layer(base.copy(), blink, EYE_BOX, 9)
            img = Image.new("RGBA", (1024, 1024))
            img.paste(tmp.crop((0, 0, 510, 1024)), (0, 0))
            img.paste(base.crop((510, 0, 1024, 1024)), (510, 0))
        if mouth == "talk":
            img = paste_layer(img, talk, MOUTH_BOX, 8)
        elif mouth == "half":
            t = paste_layer(img.copy(), talk, MOUTH_BOX, 8)
            img = Image.blend(img, t, 0.55)
        small = crop_fit(img)
        if decor:
            small = overlay_decor(small, decor)
        return pose_warp(small, pose, amp) if pose is not None else small

    # ---- 静帧表情 ----
    expr_map = {
        "neutral":   dict(),
        "happy":     dict(eyes="blink", decor="happy"),
        "laughing":  dict(mouth="talk", eyes="blink", decor="laughing"),
        "sad":       dict(decor="sad", tone=(70, 100, 170)),
        "crying":    dict(mouth="talk", decor="crying", tone=(70, 110, 180)),
        "angry":     dict(decor="angry", tone=(190, 70, 70)),
        "confused":  dict(decor="confused"),
        "thinking":  dict(decor="thinking"),
        "surprised": dict(mouth="talk", decor="surprised"),
        "shocked":   dict(mouth="talk", decor="shocked", tone=(120, 150, 220)),
        "sleepy":    dict(eyes="blink", decor="sleepy", tone=(60, 80, 140)),
        "relaxed":   dict(eyes="blink", tone=(120, 190, 210)),
        "winking":   dict(eyes="wink", decor="happy"),
        "loving":    dict(eyes="blink", decor="loving", tone=(220, 110, 150)),
        "kissy":     dict(decor="kissy", tone=(220, 120, 150)),
        "embarrassed": dict(decor="embarrassed", tone=(220, 130, 140)),
        "cool":      dict(decor="cool", tone=(80, 140, 190)),
        "confident": dict(decor="confident"),
        "delicious": dict(eyes="blink", decor="delicious"),
        "funny":     dict(mouth="talk", decor="funny"),
        "silly":     dict(mouth="talk", decor="silly"),
    }
    for name, spec in expr_map.items():
        img = compose(eyes=spec.get("eyes", "base"), mouth=spec.get("mouth", "base"))
        if spec.get("decor"):
            img = overlay_decor(img, spec["decor"])
        if spec.get("tone"):
            img = tint(img, spec["tone"], 0.10)
        img.save(os.path.join(OUT, name + ".png"), optimize=True, compress_level=9)

    # ---- 待机动画: 20 帧 / 90ms，头摆 + 发梢 + 双臂 + 胸腔呼吸 + 眨眼 ----
    idle = []
    for i in range(20):
        ph = 2 * math.pi * i / 20
        if i in (7, 16):
            e = "blink"
        elif i in (6, 8, 15, 17):
            e = "half"
        else:
            e = "base"
        idle.append(compose(eyes=e, pose=ph))
    save_gif(idle, "idle", [90] * 20)

    # ---- 说话动画: 12 帧 / 90ms，口型开合叠加肢体动作 ----
    mouth_seq = ["base", "half", "talk", "talk", "half", "base",
                 "base", "half", "talk", "talk", "half", "base"]
    talking = []
    for i in range(12):
        ph = 2 * math.pi * i / 12 + 0.35
        talking.append(compose(mouth=mouth_seq[i], pose=ph, amp=1.15))
    save_gif(talking, "speaking", [90] * 12)

    # ---- 情绪动画: 14 帧 / 90ms，幅度更大 ----
    happy_frames = []
    for i in range(14):
        ph = 2 * math.pi * i / 14
        e = "blink" if i in (4, 11) else ("half" if i in (3, 5, 10, 12) else "base")
        happy_frames.append(compose(eyes=e, pose=ph, amp=1.35, decor="happy"))
    save_gif(happy_frames, "happy_anim", [90] * 14)

    # ---- index.json ----
    entries = []
    for name in EMOTIONS:
        entries.append({"name": name, "file": name + ".png"})
    entries += [
        {"name": "idle", "file": "idle.gif"},
        {"name": "speaking", "file": "speaking.gif"},
        {"name": "happy_anim", "file": "happy_anim.gif"},
    ]
    # 固件 Alert() 弹窗用的系统 emotion，指向现有静帧，避免 fallback 到字体图标
    system_aliases = {
        "warning": "confused.png",
        "cancel": "sad.png",
        "cloud_download": "thinking.png",
        "cloud_off": "sad.png",
        "link": "thinking.png",
        "download": "thinking.png",
        "gear": "thinking.png",
    }
    for alias, target in system_aliases.items():
        entries.append({"name": alias, "file": target})
    index = {"version": 1, "emoji_collection": entries}
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print("OUTPUT:", OUT)
    print("FILES:", len(os.listdir(OUT)), "TOTAL:", round(total / 1024, 1), "KB")
    for f in sorted(os.listdir(OUT)):
        print(" ", f, round(os.path.getsize(os.path.join(OUT, f)) / 1024, 1), "KB")


if __name__ == "__main__":
    main()
