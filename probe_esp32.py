#!/usr/bin/env python3
"""ESP32 硬件探测脚本。

用法:
    python3 probe_esp32.py            # 只扫描串口
    python3 probe_esp32.py --boot     # 扫描 + 监听 3 秒 UART 启动日志
    python3 probe_esp32.py --chip     # 扫描 + esptool 读取芯片信息
"""

import argparse
import sys
import time

try:
    from serial.tools import list_ports
except ImportError:
    sys.exit("缺少 pyserial，请先执行: python3 -m pip install pyserial")


# 常见 USB 转串口芯片的 VID:PID 及 macOS 设备名特征
KNOWN = {
    ("10C4", "EA60"): ("Silicon Labs CP210x", "ESP32-DevKitC / 多数官方板, 免驱"),
    ("1A86", "7523"): ("WCH CH340/CH341", "需装 WCH 驱动, 廉价款最常见"),
    ("1A86", "55D4"): ("WCH CH9102", "免驱, 较新款"),
    ("0403", "6001"): ("FTDI FT232", "免驱, 老款"),
    ("303A", "1001"): ("Espressif USB-CDC/JTAG", "ESP32-S3/C3/P4 原生 USB, 免驱"),
    ("303A", "0002"): ("Espressif USB-Serial-JTAG", "S3 内置 USB-JTAG"),
}


def classify(port):
    vid = f"{port.vid:04X}" if port.vid else None
    pid = f"{port.pid:04X}" if port.pid else None
    if vid and pid and (vid, pid) in KNOWN:
        return KNOWN[(vid, pid)]
    name = (port.device or "").lower()
    if "wchusbserial" in name or "usbserial-1" in name:
        return ("疑似 CH34x", "设备名特征匹配")
    if "slab" in name:
        return ("疑似 CP210x", "设备名特征匹配")
    if "usbmodem" in name:
        return ("疑似 ESP32 原生 USB 或 CDC", "设备名特征匹配")
    return ("未知", "无匹配")


def scan():
    ports = [p for p in list_ports.comports() if "Bluetooth" not in p.device
             and "debug-console" not in p.device]
    if not ports:
        print("❌ 没有检测到任何 USB 串口设备")
        print()
        print("排查顺序:")
        print("  1. 换一根「数据线」——很多附赠线只有充电针脚，是最常见的原因")
        print("  2. 换一个 USB-C 口 / 换一台电脑交叉验证")
        print("  3. 确认插的是板子的 UART/USB 口，不是只有供电的口")
        print("  4. 若是 CH340 芯片（无 SLAB/wch 设备名），需安装 WCH 驱动")
        print("  5. 按一下板子上的 RST 键，再重跑本脚本")
        return []

    print(f"✅ 检测到 {len(ports)} 个串口设备\n")
    for p in ports:
        chip, note = classify(p)
        vid = f"{p.vid:04X}" if p.vid else "----"
        pid = f"{p.pid:04X}" if p.pid else "----"
        print(f"  {p.device}")
        print(f"    芯片      : {chip}")
        print(f"    VID:PID   : {vid}:{pid}")
        print(f"    描述      : {p.description}")
        if p.serial_number:
            print(f"    序列号    : {p.serial_number}")
        print(f"    备注      : {note}")
        print()
    return ports


def read_boot_log(device, seconds=3, baud=115200):
    import serial
    print(f"--- 监听 {device} @ {baud} 波特率 {seconds}s ---")
    print("（如需看启动日志，现在按一下板子的 RST 键）\n")
    try:
        with serial.Serial(device, baud, timeout=0.2) as ser:
            ser.setDTR(False)
            ser.setRTS(False)  # 避免拉低 EN 脚导致复位循环
            deadline = time.time() + seconds
            buf = b""
            while time.time() < deadline:
                buf += ser.read(4096)
            text = buf.decode("utf-8", errors="replace")
            print(text if text.strip() else "（无数据，可能固件不输出 / 波特率不对）")
    except Exception as e:
        print(f"打开失败: {e}")


def read_chip(device):
    import subprocess
    print(f"--- esptool 读取 {device} 芯片信息 ---\n")
    r = subprocess.run(
        [sys.executable, "-m", "esptool", "--port", device, "--baud", "115200", "chip_id"],
        capture_output=True, text=True, timeout=60,
    )
    print(r.stdout.strip() or r.stderr.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", action="store_true", help="监听 UART 启动日志")
    ap.add_argument("--chip", action="store_true", help="用 esptool 读芯片信息")
    args = ap.parse_args()

    ports = scan()
    if not ports:
        sys.exit(1)

    dev = ports[0].device
    if len(ports) > 1:
        print(f"⚠️  有多个串口，默认使用第一个: {dev}\n")

    if args.boot:
        read_boot_log(dev)
    if args.chip:
        read_chip(dev)


if __name__ == "__main__":
    main()
