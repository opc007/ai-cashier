#!/usr/bin/env python3
"""复位 ESP32 并抓取完整启动日志。

用法: python3 bootlog.py [秒数] [波特率]
"""

import sys
import time

import serial

PORT = "/dev/cu.usbserial-110"


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

    ser = serial.Serial(PORT, baud, timeout=0.1)
    # 复位：GPIO0 保持高，EN 拉低再释放 -> 正常启动
    ser.dtr = False
    ser.rts = True
    time.sleep(0.15)
    ser.rts = False

    buf = b""
    deadline = time.time() + secs
    while time.time() < deadline:
        chunk = ser.read(8192)
        if chunk:
            buf += chunk
    ser.close()

    text = buf.decode("utf-8", errors="replace")
    # 去掉 ANSI 颜色
    import re
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
