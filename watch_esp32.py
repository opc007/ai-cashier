#!/usr/bin/env python3
"""USB 热插拔监听：等待 ESP32 串口出现。

用法: python3 watch_esp32.py [超时秒数]
"""

import sys
import time

from serial.tools import list_ports

IGNORE = ("Bluetooth", "debug-console")


def current():
    return {p.device: p for p in list_ports.comports() if not any(k in p.device for k in IGNORE)}


def main():
    timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    print(f"开始监听 {timeout}s，等待串口设备...", flush=True)
    print("（此时拔下 USB，换口重插）\n", flush=True)

    seen = set(current())
    if seen:
        print(f"初始已存在: {sorted(seen)}\n", flush=True)

    deadline = time.time() + timeout
    found = False
    while time.time() < deadline:
        now = current()
        for dev, p in now.items():
            if dev not in seen:
                vid = f"{p.vid:04X}" if p.vid else "----"
                pid = f"{p.pid:04X}" if p.pid else "----"
                print(f"✅ [{time.strftime('%H:%M:%S')}] 设备接入: {dev}", flush=True)
                print(f"   VID:PID = {vid}:{pid}", flush=True)
                print(f"   描述    = {p.description}", flush=True)
                print(f"   序列号  = {p.serial_number}", flush=True)
                found = True
        for dev in list(seen):
            if dev not in now:
                print(f"⚠️  [{time.strftime('%H:%M:%S')}] 设备移除: {dev}", flush=True)
        seen = set(now)
        time.sleep(0.5)

    if not found:
        print("\n❌ 超时仍无设备出现。", flush=True)
        return 1
    print("\n✅ 监听结束，设备已就位。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
