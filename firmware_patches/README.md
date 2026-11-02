# 固件补丁覆盖层

本项目不直接 fork 整个 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)
源码树（800MB+），只提交我们在其上修改的文件，按原路径摆放。

## 基线版本

- **xiaozhi-esp32 v2.5.2**（`PROJECT_VER "2.5.2"`）
- 板型：`bread-compact-wifi-s3cam`（ESP32-S3 + OV3660 摄像头 + 240x320 ST7789）

## 应用方法

```bash
git clone https://github.com/78/xiaozhi-esp32.git
cd xiaozhi-esp32
git checkout v2.5.2          # 或与你的版本对应，改动都是局部覆盖，其他版本大概率也能用

# 把本目录的 main/ 覆盖过去
cp -r /path/to/ai-cashier/firmware_patches/main/* main/
```

## 改动清单

| 文件 | 改动 |
|---|---|
| `main/greeter/`（新增） | 摄像头迎宾：本地人脸检测（ESP-SR MSR 模型），检测到顾客自动唤醒 AI；待机态能量 VAD，喊一嗓子也能唤醒；**会话守护**：顾客 30 秒没人声自动挂断，迎宾立即重新武装，解决顾客进进出出的轮换问题 |
| `main/screen_poller/`（新增） | 每 1.5s 轮询 Mac 上的屏幕服务，有新画面就拉 RGB565 原始帧全屏常驻显示（收款二维码常驻不掉）。服务地址存 NVS `cashier/server_url`，默认 `http://<Mac 局域网IP>:8801` |
| `main/display/display.h` `lcd_display.{h,cc}` | 新增 `SetPersistentImage`：全屏常驻显示（原 `SetPreviewImage` 5 秒自动隐藏，收款码留不住） |
| `main/application.cc` | 启动 Greeter / ScreenPoller；状态机回调接迎宾；VAD 事件接声音迎宾 |
| `main/CMakeLists.txt` | 注册新组件 |

## 已知的坑（都在代码里处理了）

1. **中文路径编译崩溃**：xtensa-gcc 读中文路径的 specs 会失败，源码树放英文路径
2. **lwIP mbox 断言重启环**：轮询任务若在网络就绪前发 HTTP，开机即崩。ScreenPoller 首轮会等设备进入 Idle 态
3. **RGB565 字节序**：ESP32 摄像头帧是大端，检测前要 `bswap16`；LVGL 显示用小端
4. **greeter.cc 里的调试帧上传**（UploadDebugFrame）是开发期工具，正式部署可删

## 编译烧录

```bash
source ~/esp-idf/export.sh
python3 scripts/build.py bread-compact-wifi-s3cam
python -m esptool --chip esp32s3 -p /dev/cu.usbserial-xxx -b 460800 \
  write-flash --flash-mode qio --flash-size 16MB 0x20000 build/xiaozhi.bin
```

烧录后首次需要配网（小智配套 App / AP 模式），并让设备与 Mac 在同一局域网。
