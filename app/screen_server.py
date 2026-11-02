"""屏幕推图服务。

设备端 `self.screen.preview_image` 只接受一个 url，自己 HTTP GET 下载后全屏显示。
所以服务器的做法是：把要显示的画面渲染成 PNG，挂在这台 Mac 的局域网上，
再把地址交给设备去取。

三种页面：
    /idle.png              待客页
    /order/<order_id>.png  订单确认页
    /pay/<order_id>.png    收款页（带商户收款码）

跑法：
    python3 app/screen_server.py
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import render_screen as rs  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cashier.db")

# 屏幕分辨率。这块板是 ST7789 系列，240x320 是最常见配置。
# 如果实际显示错位，改这两个值即可（常见备选：172x320、240x280、240x240）。
SCREEN_W = int(os.getenv("SCREEN_W", "240"))
SCREEN_H = int(os.getenv("SCREEN_H", "320"))

# 设备要通过局域网访问这个地址，所以绑局域网 IP 而不是 127.0.0.1
HOST = os.getenv("SCREEN_HOST", "0.0.0.0")
PORT = int(os.getenv("SCREEN_PORT", "8801"))


def _conn() -> sqlite3.Connection:
    # 每次请求新建连接，避免多线程共享连接的问题
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _load_order(order_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return None
        items = c.execute(
            "SELECT name, unit_cents, qty FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchall()
        return {
            "id": row["id"],
            "merchant_id": row["merchant_id"],
            "status": row["status"],
            "total": row["total_cents"] / 100.0,
            "items": [
                (it["name"], it["unit_cents"] * it["qty"] / 100.0) for it in items
            ],
        }


def _merchant_qr(merchant_id: str) -> Image.Image:
    """商户的收款码。没配就用一张占位码，等后台传了真码自动替换。"""
    with _conn() as c:
        row = c.execute(
            "SELECT qr_image_path FROM merchants WHERE id = ?", (merchant_id,)
        ).fetchone()
    path = row["qr_image_path"] if row else None
    if path and os.path.exists(path):
        return Image.open(path).convert("RGB")
    return rs.make_qr("请在后台上传商户收款码", box_size=10, border=3)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # PNG 而非 JPEG：二维码是高频黑白图案，JPEG 压缩会在方块边缘产生伪影
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─────────────────────────── 设备画面状态 ───────────────────────────
#
# 设备固件每 1.5 秒轮询 /next_screen，发现 v 变了就来拉原始帧。
# 为什么要轮询而不是让大模型喊设备显示：设备端的 self.screen.preview_image
# 是 user-only 工具（云端模型看不到），而且 preview 5 秒自动隐藏。
# 收银二维码必须常驻到顾客付完款，所以改成「服务端登记、设备常驻显示」。

_screen_lock = threading.Lock()
_current_screen = {"v": None, "raw": None}  # v=画面版本（即页面路径）, raw=RGB565 字节


def _to_rgb565(img: Image.Image) -> bytes:
    """PNG 帧转 RGB565 小端字节。LVGL 的 RGB565 就是 uint16 逐像素小端。"""
    img = img.convert("RGB").resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    arr = np.frombuffer(img.tobytes(), dtype=np.uint8).reshape(SCREEN_H, SCREEN_W, 3)
    r = (arr[:, :, 0].astype(np.uint16) >> 3) << 11
    g = (arr[:, :, 1].astype(np.uint16) >> 2) << 5
    b = arr[:, :, 2].astype(np.uint16) >> 3
    return ((r | g | b).astype("<u2")).tobytes()


def set_screen(path: str) -> bool:
    """登记要显示的画面。渲染失败返回 False，调用方（MCP 工具）要给模型报错。"""
    try:
        png = build_page(path)
        if png is None:
            return False
        img = Image.open(io.BytesIO(png))
        raw = _to_rgb565(img)
    except Exception as e:  # 渲染崩了不能把旧画面顶掉
        sys.stderr.write(f"[screen] set_screen {path} failed: {e}\n")
        return False
    with _screen_lock:
        _current_screen["v"] = path
        _current_screen["raw"] = raw
    return True


def get_screen_state() -> dict:
    with _screen_lock:
        return {"v": _current_screen["v"], "raw": _current_screen["raw"]}


def build_page(path: str) -> bytes | None:
    """根据 URL 路径渲染页面，返回 PNG 字节。不认识的路由返回 None。"""
    clean = path.split("?")[0].rstrip("/")

    if clean in ("/idle.png", "/idle"):
        return _png(rs.render_idle(w=SCREEN_W, h=SCREEN_H))

    if clean.startswith("/order/"):
        oid = clean[len("/order/"):].replace(".png", "")
        o = _load_order(oid)
        if not o:
            return None
        return _png(rs.render_order(o["items"], o["total"], w=SCREEN_W, h=SCREEN_H))

    if clean.startswith("/pay/"):
        oid = clean[len("/pay/"):].replace(".png", "")
        o = _load_order(oid)
        if not o:
            return None
        qr = _merchant_qr(o["merchant_id"])
        return _png(
            rs.render_pay(f"{o['total']:.2f}", qr, w=SCREEN_W, h=SCREEN_H)
        )

    return None


def _rgb565_to_image(raw: bytes, w: int, h: int, swap: bool) -> Image.Image:
    import array

    a = array.array("H")
    a.frombytes(raw[: w * h * 2])
    if swap:
        a.byteswap()
    px = bytearray(w * h * 3)
    for i, v in enumerate(a):
        px[i * 3] = ((v >> 11) & 0x1F) * 255 // 31
        px[i * 3 + 1] = ((v >> 5) & 0x3F) * 255 // 63
        px[i * 3 + 2] = (v & 0x1F) * 255 // 31
    return Image.frombytes("RGB", (w, h), bytes(px))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @staticmethod
    def _expire_stale() -> None:
        """每次设备轮询时回收过期订单；有作废的就切回待客页。

        顾客出到码没付就走了，屏幕必须自动回到「欢迎光临」，
        不能让下一位顾客对着上一位的收款码扫码。
        """
        try:
            from app.order import expire_stale_orders
            expired = expire_stale_orders()
            if expired:
                sys.stderr.write(f"[screen] expired orders {expired}, back to idle\n")
                set_screen("/idle.png")
        except Exception as e:  # 回收失败不影响正常轮询
            sys.stderr.write(f"[screen] expire_stale failed: {e}\n")

    def do_GET(self):  # noqa: N802
        try:
            clean = self.path.split("?")[0].rstrip("/")

            # 设备轮询：当前该显示什么画面
            if clean == "/next_screen":
                self._expire_stale()
                st = get_screen_state()
                if not st["v"]:
                    body = b'{"url": null, "v": null}'
                else:
                    body = json.dumps({"url": "/raw/current.bin", "v": st["v"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            # 设备拉原始帧（RGB565，设备端直接送显，不用解码 PNG）
            if clean == "/raw/current.bin":
                st = get_screen_state()
                if not st["raw"]:
                    self.send_error(404, "no screen set")
                    return
                body = st["raw"]
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            body = build_page(self.path)
        except Exception as e:  # 渲染失败时不能让设备干等
            self.send_error(500, f"render error: {e}")
            return

        if body is None:
            self.send_error(404, "no such page")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        clean = self.path.split("?")[0].rstrip("/")

        # MCP 工具登记画面：{"path": "/pay/<oid>.png"}
        if clean == "/show":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                path = data.get("path", "")
                ok = set_screen(path)
                body = b"ok" if ok else b"render failed"
                code = 200 if ok else 400
            except Exception as e:
                body = str(e).encode()
                code = 500
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self.path.startswith("/debug_frame"):
            self.send_error(404, "no such endpoint")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            w, h = 160, 120
            Path("/tmp/frame.raw").write_bytes(raw)
            for swap, tag in ((False, "le"), (True, "be")):
                img = _rgb565_to_image(raw, w, h, swap)
                img.resize((320, 240), Image.NEAREST).save(f"/tmp/frame_{tag}.png")
            sys.stderr.write(f"[screen] debug frame {len(raw)}B saved\n")
        except Exception as e:
            self.send_error(500, f"save error: {e}")
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[screen] {self.address_string()} {fmt % args}\n")


def serve_in_thread() -> ThreadingHTTPServer:
    """给别的进程（比如 MCP 服务）内嵌启动用。"""
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    set_screen("/idle.png")  # 服务一起来就登记待客页，设备轮询到就会显示
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="screen-server")
    t.start()
    return srv


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    set_screen("/idle.png")
    print(f"屏幕推图服务已启动: http://<本机局域网IP>:{PORT}/idle.png")
    print(f"页面尺寸 {SCREEN_W}x{SCREEN_H}，Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
