"""摄像头迎宾。

店里开着，每 0.4 秒看一帧画面：有人站在台前就打招呼，然后闭嘴等一会儿，
别对同一个顾客连喊三遍「欢迎光临」。

用法：
    python3 app/vision.py                    # 用本机摄像头常驻
    python3 app/vision.py --image a.jpg      # 只对一张图跑检测，用来验证算法
    python3 app/vision.py --dry-run          # 检测到人只打日志、不出声

为什么用 Haar 人脸而不是"画面有变化就触发"：
店里灯会闪、窗外有人走过、风扇在转，帧差法会疯掉。人脸框必须够大
（占画面宽度 12% 以上）才算"站在台前"，这个门槛把远处路过的人挡掉了。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import cv2

# OpenCV 5 移除了 Haar 级联，改用 YuNet 神经网络人脸检测。
# 顺带的好处是它对侧脸、逆光、戴帽子都更稳，老板不用正襟危坐地站在机器前。
MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "models" / "face_detection_yunet.onnx"

DEFAULT_GREETINGS = [
    "欢迎光临，老板需要点什么？",
    "欢迎光临，随便看看，需要什么喊我一声。",
    "来了老板，今天想买点啥？",
]


class Greeter:
    def __init__(
        self,
        camera_index: int = 0,
        min_face_ratio: float = 0.12,
        need_hits: int = 3,
        cooldown: float = 45.0,
        voice: str = "Tingting",
        greeting: str | None = None,
        dry_run: bool = False,
        window: int = 5,
    ):
        self.camera_index = camera_index
        self.min_face_ratio = min_face_ratio
        self.need_hits = need_hits  # 连续命中几帧才认
        self.cooldown = cooldown  # 打完招呼多久内不再打
        self.voice = voice
        self.greeting = greeting
        self.dry_run = dry_run
        self.recent = deque(maxlen=window)  # 最近若干帧的结果，做防抖
        self.last_greet = 0.0
        if not MODEL_PATH.exists():
            raise RuntimeError(
                f"缺少人脸模型: {MODEL_PATH}\n"
                "下载地址（约 227KB）：\n"
                "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
                "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
            )
        self.detector = cv2.FaceDetectorYN.create(
            str(MODEL_PATH), "", (320, 320), 0.75, 0.3, 5000
        )

    # ── 检测 ──

    def detect(self, frame) -> list[tuple[int, int, int, int]]:
        """返回画面里够大的人脸框。太小的忽略——那是远处路过的人。"""
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        min_side = w * self.min_face_ratio
        out = []
        for f in faces:
            x, y, fw, fh = (int(v) for v in f[:4])
            if fw >= min_side and fh >= min_side:
                out.append((x, y, fw, fh))
        return out

    def feed(self, has_person: bool) -> bool:
        """喂一次结果，返回这一帧是否应该触发招呼。"""
        self.recent.append(1 if has_person else 0)
        if len(self.recent) < self.recent.maxlen:
            return False
        if sum(self.recent) < self.need_hits:
            return False
        now = time.monotonic()
        if now - self.last_greet < self.cooldown:
            return False
        self.last_greet = now
        self.recent.clear()
        return True

    # ── 动作 ──

    def greet(self) -> str:
        text = self.greeting or DEFAULT_GREETINGS[0]
        print(f"[迎宾] {time.strftime('%H:%M:%S')} 检测到顾客 → 播报：{text}", flush=True)
        if not self.dry_run:
            try:
                # say 是阻塞的，扔后台跑，别卡住检测循环
                subprocess.Popen(
                    ["say", "-v", self.voice, text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[迎宾] 播报失败: {e}", file=sys.stderr, flush=True)
        return text

    # ── 主循环 ──

    def run(self, show: bool = False) -> None:
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError(
                f"打不开摄像头 {self.camera_index}。"
                "如果是 macOS，去 系统设置 → 隐私与安全性 → 摄像头，"
                "给终端/Python 授权后重试。"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        print(f"[迎宾] 摄像头已开，开始值守。冷却 {self.cooldown:.0f} 秒，Ctrl+C 退出", flush=True)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.2)
                    continue
                faces = self.detect(frame)

                if show:
                    for x, y, w, h in faces:
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
                    cv2.imshow("vision", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break

                if self.feed(bool(faces)):
                    self.greet()

                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\n[迎宾] 已停止", flush=True)
        finally:
            cap.release()
            if show:
                cv2.destroyAllWindows()


def test_image(path: str, min_face_ratio: float = 0.12) -> int:
    """对单张图跑检测，用来验证算法本身对不对（不需要摄像头权限）。"""
    img = cv2.imread(path)
    if img is None:
        print(f"读不到图片: {path}", file=sys.stderr)
        return 2
    h, w = img.shape[:2]
    g = Greeter(min_face_ratio=min_face_ratio)
    faces = g.detect(img)
    print(f"图片 {Path(path).name}  {w}x{h}")
    print(f"检出人脸 {len(faces)} 个")
    for i, (x, y, fw, fh) in enumerate(faces, 1):
        print(f"  #{i}  位置({x},{y})  尺寸{fw}x{fh}  占画面宽 {fw / w:.1%}")
    print("判定：" + ("有人站在台前，会打招呼" if faces else "没达到触发门槛，不打招呼"))
    return 0 if faces else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="摄像头迎宾")
    ap.add_argument("--camera", type=int, default=0, help="摄像头序号，默认 0")
    ap.add_argument("--image", help="只检测一张图，验证算法用")
    ap.add_argument("--dry-run", action="store_true", help="只打日志不出声")
    ap.add_argument("--show", action="store_true", help="弹出窗口显示检测框")
    ap.add_argument("--cooldown", type=float, default=45.0, help="两次招呼之间的最小间隔（秒）")
    ap.add_argument("--min-ratio", type=float, default=0.12, help="人脸占画面宽的最小比例")
    ap.add_argument("--voice", default="Tingting", help="say 的发音人")
    ap.add_argument("--greeting", help="自定义欢迎语")
    args = ap.parse_args()

    if args.image:
        return test_image(args.image, args.min_ratio)

    g = Greeter(
        camera_index=args.camera,
        min_face_ratio=args.min_ratio,
        cooldown=args.cooldown,
        voice=args.voice,
        greeting=args.greeting,
        dry_run=args.dry_run,
    )
    try:
        g.run(show=args.show)
    except RuntimeError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
