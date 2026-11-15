# 2D 角色帧动画 + 口型同步（可选模块）

把 [云天 / yuntian365](https://gitee.com/yuntian365) 2026-11 的 FireBeetle 2 ESP32-P4 小智角色方案，接到本仓库的 **xiaozhi-esp32 v2.5.2** 收银固件上。默认关闭，不改变现有收银表情。

| | |
| --- | --- |
| 作者 | 云天 / yuntian365 |
| 仓库 | https://gitee.com/yuntian365/xiaozhi-p4-dfrobot |
| 文章 | https://mc.dfrobot.com.cn/article-387130.html （2026-11-10，DFRobot 社区） |
| 协议 | MIT。本目录 `LICENSE`、`NOTICE.md` 为上游原文 |
| 上游固件 | 78/xiaozhi-esp32 **v2.5.3** + ESP-IDF release/v6.1 |
| 本仓库固件 | 78/xiaozhi-esp32 **v2.5.2** 补丁层，没有整树升级到 2.5.3 |

上游 README 全文在 [`README.upstream.md`](README.upstream.md)。状态机原文摘录在 [`emotion/upstream_application_hooks.cc`](emotion/upstream_application_hooks.cc)（不参与编译）。

## 这个目录里有什么

| 路径 | 说明 |
| --- | --- |
| `live2d/` | 上游角色目录：21 张情绪静帧 + 3 个透明 GIF、`make_live2d.py`、`build_assets_bin.py`、`source/` 三张原画、`preview.html` |
| `live2d/assets/xiaozhi-live2d/index.json` | 31 条 emotion（24 个角色资源 + 7 个系统弹窗别名） |
| `emotion/upstream_application_hooks.cc` | v2.5.3 `SetCharacterEmotion` 与 llm / 状态机挂钩原文 |
| `kconfig.snippet` | 可选的 menuconfig 片段，不要拿它覆盖 `Kconfig.projbuild` |
| `LICENSE` / `NOTICE.md` | 上游许可证与第三方说明原文 |

没有导入：FireBeetle 板级代码、`xiaozhi-esp32/` v2.5.3 整树、`firmware/c6-slave/` 里的 ESP-Hosted / 出厂恢复包。上游那个约 7.9MB 的 `xiaozhi-live2d-assets.bin` 也没有带过来——它把 P4 那次构建的字体和 `esp-sr` 模型打在一起，不是本仓库的编译产物，也不能直接烧到收银板。

设备侧仍然走小智原有的 `LvglGif` / `emoji_collection` / `LcdDisplay::SetEmotion`。这不是 Cubism `.moc3`。

## 状态机

| 状态 | emotion | 画面 |
| --- | --- | --- |
| `idle` / `connecting` / `listening`（以及与 idle 同一分支的 `unknown`） | `idle` | `idle.gif`：呼吸 + 眨眼 |
| `speaking` / `notifying` | `speaking` | `speaking.gif`：口型开合 |
| `DismissAlert()` 回到待机 | `idle` | 恢复待机动画 |
| 资源应用结束（上游 `Activate` 末尾的同一位置） | `idle` | 不再显示 `robot_2` |

`llm` 消息在 `speaking` / `notifying` 时丢掉服务端 emotion，并且**不再调用** `SetEmotion`。否则服务端静帧（`happy.png` / `sleepy.png` 经常是闭眼）会换掉 `speaking.gif`，而且每个分句都会把 GIF 从第 0 帧重开。其它状态仍显示服务端情绪。

`happy_anim.gif` 在资源包里，状态机不会自动播。非说话状态下服务端如果下发 `happy_anim`，会走原来的 `SetEmotion`。

调用入口（任意代码都可以用，不依赖下面的编译开关）：

```cpp
#include "character/character_emotion.h"

SetCharacterEmotion(display, "speaking");
```

`CharacterEmotionNameForState()` / `CharacterEmotionAcceptsServerEmotion()` 是纯逻辑，见 `firmware_patches/main/character/`。

## 怎么打开

开关默认关闭。关闭时开机仍是 `robot_2`，待机/连接/聆听仍是 `neutral`，`llm` emotion 照常显示，说话状态不主动改表情。

1. 按 [firmware_patches/README.md](../../firmware_patches/README.md) 把 `firmware_patches/main/` 覆盖到 v2.5.2 的 `main/`。
2. 配置时加上开关，并把表情目录交给构建（只扫描 `.png` / `.gif`，文件名即 emotion 名）：

```bash
cd /path/to/xiaozhi-esp32
idf.py -DXIAOZHI_LIVE2D_CHARACTER=ON \
  -DXIAOZHI_LIVE2D_ASSET_DIR=/path/to/ai-cashier/vendor/yuntian365-xiaozhi-live2d/live2d/assets/xiaozhi-live2d \
  build
```

这会把集合拷到 `xiaozhi-fonts` 的 `png/xiaozhi-live2d/`，并把 `DEFAULT_EMOJI_COLLECTION` 设成 `xiaozhi-live2d`。这条路径**没有** 7 个系统别名（`warning`、`cancel`、`cloud_off` …），缺名字时仍回退到字体图标。要别名和深色 `skin`，用下面的打包脚本。

也可以不拷进字体组件，只打开状态机，再烧自定义 assets：

```bash
idf.py -DXIAOZHI_LIVE2D_CHARACTER=ON build
```

然后 `menuconfig` → Xiaozhi Assistant → Flash Assets → **Flash Custom Assets**，`CONFIG_CUSTOM_ASSETS_FILE` 指向打包结果。

想进 menuconfig 而不是 CMake `-D`：把 [`kconfig.snippet`](kconfig.snippet) 里的 `config` 块贴进 `main/Kconfig.projbuild`（不要整文件覆盖），再勾选 `XIAOZHI_LIVE2D_CHARACTER`。

## 重新生成资源

在 `live2d/` 下，依赖 Pillow、NumPy、OpenCV，以及 `rembg` 的 `u2netp.onnx`（首次运行自动下载，不随仓库分发）：

```bash
python -m pip install pillow numpy opencv-python "rembg[cpu]"
python make_live2d.py
```

输入是 `live2d/source/` 的三张立绘（基础 / 闭眼 / 张嘴）。输出是 `live2d/assets/xiaozhi-live2d/`：280×340、8-bit RGBA PNG 或透明 GIF。`idle.gif` 20 帧 / 90 ms，`speaking.gif` 12 帧 / 90 ms，`happy_anim.gif` 14 帧 / 90 ms。文件名不超过 31 字节。

## 打包并烧录 emoji_collection

`build_assets_bin.py` 读一次已经生成的 `generated_assets.bin`，换掉里面的表情条目，写入 31 条 `emoji_collection`（含系统别名）和深色 `skin`，字体与语音模型原样保留：

```bash
python live2d/build_assets_bin.py \
  --base /path/to/xiaozhi-esp32/build/generated_assets.bin \
  --out /tmp/xiaozhi-live2d-assets.bin
```

脚本默认基线路径是上游 Windows 机器上的 `C:\xz\xiaozhi-esp32\build\generated_assets.bin`，并且把体积上限写死为 **8MB**（P4 `partitions/v2/16m.csv` 的 assets 分区）。换语言或重新 configure 之后要重跑，否则字体 / `srmodels` 会和新固件不一致。

收银板 `bread-compact-wifi-s3cam` 是 16MB flash。v2 分区表里 16MB 的 assets 同样是 **8MB @ 0x800000**。只烧 assets、不动 NVS：

```bash
python -m esptool --chip esp32s3 -p /dev/ttyUSB0 -b 460800 \
  write_flash 0x800000 /tmp/xiaozhi-live2d-assets.bin
```

先看分区表确认偏移。整片从 `0x0` 烧录会清掉 Wi-Fi。输出超过脚本里的 8MB 会直接失败；分区若比产物小，烧录也会失败，需要先减表情或换更小的字库再打包。

`preview.html` 可在浏览器里预览 21 个表情和 3 个动画，不需要设备。

## v2.5.2 和 v2.5.3 的差异

上游辅助函数是：

```cpp
if (display->SetEmotion(emotion)) {
    ESP_LOGI(TAG, "Character emotion: %s", emotion);
} else {
    display->SetEmotion("neutral");
}
```

v2.5.3 的 `Display::SetEmotion` 返回 `bool`。v2.5.2 的声明是 `virtual void SetEmotion(const char* emotion)`，找不到表情时改画字体图标，没有返回值。直接把 v2.5.3 的 `application.cc` 贴过来不能编。

本仓库没有改 `SetEmotion` 的签名——v2.5.2 树上还有 OLED / 表情屏等其它覆写，改成 `bool` 会让那些文件编不过。加了默认实现的 `Display::SetEmojiEmotion()`：只有 emoji 集合里真有这张 PNG/GIF 时返回 true。`LcdDisplay` 覆写它。`SetCharacterEmotion()` 成功打 `Character emotion: ...`，失败再 `SetEmotion("neutral")`。

因此：

- 没烧角色包就打开开关时，`idle` / `speaking` 会落到 `neutral`，说话过程中服务端 emotion 被丢掉，口型动画不会出现。开关和资源要一起用。
- v2.5.3 的 `SetEmotion` 在「没有图片、但有字体图标」时也返回 true。`idle` / `speaking` 没有对应图标，两边的回退结果一样。这里的 `SetEmojiEmotion` 只认集合里的图，避免把字体图标当成角色资源。
- 角色帧是 **280×340**，为 800×480 的 P4 屏画的。收银屏是 **240×320 ST7789**。开关打开后，`SetEmotion` / `SetEmojiEmotion` 在位图比面板大时按 LVGL scale（256 = 1x）缩小到面板内，支点在图中心。P4 上 280×340 放得下，缩放保持 256，和上游一致。GIF 帧缓冲仍是 ARGB8888，约 280×340×4 ≈ 381KB，S3 需要 PSRAM，不要做成全屏 GIF。
- 收银的常驻收款码（`SetPersistentImage`）仍盖在角色上面。付款页不改成角色动画。
- 上游的开机跳过版本检查、C6 从机、DSI 屏和 I2S 功放没有移植。那些不是这个动画模块要用的。
- `build_default_assets.py` 按文件名生成表情表，不管目录里的 `index.json`。31 条别名只有 `build_assets_bin.py` 会写进去。
