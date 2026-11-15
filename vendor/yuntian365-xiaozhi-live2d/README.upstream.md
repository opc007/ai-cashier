# 小智 AI 桌面伴侣 · FireBeetle 2 ESP32-P4 + 7″ DSI 触摸屏

把开源 [小智 AI 固件](https://github.com/78/xiaozhi-esp32) v2.5.3 移植到 DFRobot FireBeetle 2 ESP32-P4，
点亮 7 英寸 DSI 触摸屏、接上 I2S 功放，并配一套**原创的会动的角色资源**（深色主题 + 待机/说话状态联动 + 伪 Live2D 肢体动画）。

本仓库是**完整可复现**的：既有已应用全部改动、可直接编译的源码树，也有编译好的固件镜像。clone 下来按下面步骤即可从零编译、烧录。

![项目封面](article/images/00-cover.png)

---

## 一、硬件清单

本项目所有核心硬件均采购自 DFRobot 创客商城：

| 名称 | 货号 | 链接 |
| --- | --- | --- |
| FireBeetle 2 ESP32-P4 AI 开发板 | DFR1172 | https://www.dfrobot.com.cn/goods-4172.html |
| 800×480 TFT 树莓派 DSI 电容触摸屏（7 英寸） | DFR0678 | https://www.dfrobot.com.cn/goods-3005.html |
| MAX98357 I2S 功放模块 | DFR0954 | https://www.dfrobot.com.cn/goods-3573.html |
| 4Ω / 8Ω 喇叭、PH2.0 线、杜邦线、USB-C 数据线 | — | 通用配件 |

关键硬件事实：

- P4 板**板载 PDM 麦克风，但没有 DAC / 功放 / 喇叭**，必须外接 I2S 功放才能出声；
- 板载 ESP32-C6-MINI-1 作 Wi-Fi 从机，经 **SDIO 4-bit 40MHz** 与 P4 通信；
- 屏幕走「免 DSI 命令配置」路径：1-lane DSI、RGB565，桥与 LCD 由屏上 MCU 自行初始化。

接线表、引脚定义见 [`board-overlay/main/boards/dfrobot/firebeetle-2-esp32-p4/README.md`](board-overlay/main/boards/dfrobot/firebeetle-2-esp32-p4/README.md)。

---

## 二、仓库结构

| 目录 | 内容 |
| --- | --- |
| `xiaozhi-esp32/` | **可编译源码树**：上游 v2.5.3 + 本项目全部改动（板型、状态联动、握手、构建补丁）已应用 |
| `board-overlay/` | 上述改动的独立补丁包，方便对照上游或移植到更新版本 |
| `live2d/` | 原创角色资源（21 PNG + 3 GIF）、生成脚本、`assets.bin`、预览页与说明 |
| `firmware/` | **编译好的固件**、分区镜像、C6 从机固件与哈希清单 |
| `article/` | DF 创客社区投稿文章（Markdown）与配图 |
| `docs/` | 编译/烧录详解 `BUILD.md`、原始交接记录 `HANDOFF.md` |

`xiaozhi-esp32/` 中**不含** `build/`、`managed_components/`、`sdkconfig` 等生成物——托管组件会由 ESP-IDF 组件管理器按 `dependencies.lock` 自动拉取。`dependencies.lock` 已特意提交，保证组件版本可复现。

---

## 三、路线 A：直接烧现成固件（最快）

需要 [esptool](https://github.com/espressif/esptool)（`python -m pip install esptool`），Flash 参数 `16MB / dio / 80m`。

```powershell
# 整片烧录（会擦掉 NVS 中的 Wi-Fi 凭据，之后需重新配网）
python -m esptool --chip esp32p4 -p COM4 -b 460800 `
  --before default_reset --after hard_reset write_flash `
  --flash-mode dio --flash-freq 80m --flash-size 16MB `
  0x0 firmware\xiaozhi-p4-dfr0678-zh-CN_live2d_dark_merged_0x0.bin
```

已配网的设备只想更新角色资源时，**只烧 assets 分区**，不动 NVS：

```powershell
python -m esptool --chip esp32p4 -p COM4 -b 460800 write_flash `
  0x800000 firmware\xiaozhi-live2d-assets.bin
```

开机后短按 BOOT 进入配网（热点 `Xiaozhi-XXXX`，配网页 `192.168.4.1`），联网后设备播报 6 位验证码，到 [xiaozhi.me 控制台](https://xiaozhi.me/) 添加设备即可对话。

完整固件清单、SHA256 与分区偏移见 [`firmware/README.md`](firmware/README.md)。

---

## 四、路线 B：从源码编译

### 环境要求

| 组件 | 版本 |
| --- | --- |
| ESP-IDF | **release/v6.1**（v6.1.0，需安装 esp32p4 target；5.x 不支持） |
| Python | 3.11（使用 IDF 自带的虚拟环境） |
| 构建工具 | CMake、Ninja、RISC-V GCC 15.x |
| 系统 | Windows / Linux / macOS 均可；Windows 建议把仓库放在短路径下 |

### 编译步骤

```powershell
# 0) 建议用短路径，避免 Windows 32KB 命令行限制
git clone <本仓库地址> C:\xz\xiaozhi-p4-gitee
cd C:\xz\xiaozhi-p4-gitee\xiaozhi-esp32

# 1) 激活 IDF 环境（按你的实际安装路径）
. "<IDF 路径>\Microsoft.v6.1.PowerShell_profile.ps1"   # Windows / EIM
# source /path/to/esp-idf/export.sh                     # Linux / macOS
$env:PYTHONPATH = ""          # 避免外部注入的 sitecustomize 干扰组件管理器
$env:CCACHE_DISABLE = "1"     # EIM 默认 ccache 在 esp-dsp 汇编目标上偶发挂死

# 2) 生成配置并拉取托管组件（首次会编译到某处报错，属正常，组件已下载）
python scripts/build.py dfrobot/firebeetle-2-esp32-p4 `
  --name firebeetle-2-esp32-p4-rpi7 --language zh-CN

# 3) esp_video 兼容补丁（必须在组件拉取之后、正式编译之前）
python scripts/patch_esp_video_caps.py

# 4) Windows 长路径补丁（短路径可跳过；每次 reconfigure 后要重跑）
python scripts/fix_ninja_long_cmd.py

# 5) 增量续编
ninja -C build -j 4 all
```

> **第 3 步不能省**：`espressif/esp_video` 只凭 `ESP_IDF_VERSION >= 5.5.6` 就开启 CSI event 代码路径，而 release/v6.1 并未提供相关 API，会直接编译失败。本板型没有摄像头，补丁用 `#if 0` 关掉该路径。托管组件被重新下载后会还原，届时重跑脚本。
>
> **第 4 步只在 Windows 长路径下需要**：80+ 托管组件让 `project_elf_src_esp32p4.c.obj` 的 `INCLUDES` 超过 32767 字符。脚本把这条 edge 改写成 GCC response file，其余目标不受影响，不用推倒重来。
>
> 裸跑 `ninja` 需要补齐 `IDF_PATH` / `ESP_IDF_VERSION` / `IDF_TARGET` / `IDF_PYTHON_ENV_PATH` 等环境变量，详见 [`docs/BUILD.md`](docs/BUILD.md)。

产物在 `build/`：`xiaozhi.bin`（app）、`generated_assets.bin`（原始资源包）。若想用本项目的角色资源重新打包：

```powershell
cd ..\live2d
python build_assets_bin.py --base ..\firmware\generated_assets.bin --out xiaozhi-live2d-assets.bin
```

生成合并镜像：

```powershell
python -m esptool --chip esp32p4 merge_bin `
  -o merged_0x0.bin --flash_mode dio --flash_freq 80m --flash_size 16MB `
  0x2000 build\bootloader\bootloader.bin `
  0x8000 build\partition_table\partition-table.bin `
  0xd000 build\ota_data_initial.bin `
  0x20000 build\xiaozhi.bin `
  0x800000 ..\firmware\xiaozhi-live2d-assets.bin
```

### 分区表

| 偏移 | 分区 | 大小 |
| --- | --- | --- |
| `0x2000` | bootloader | — |
| `0x8000` | partition table | — |
| `0xd000` | otadata | — |
| `0xf000` | phy_init | — |
| `0x20000` | ota_0（app） | `0x3f0000` |
| `0x410000` | ota_1 | `0x3f0000` |
| `0x800000` | assets | 8 MB |

---

## 五、本项目相对上游的改动

| 文件 | 改动 |
| --- | --- |
| `main/boards/dfrobot/firebeetle-2-esp32-p4/*` | 新增板型：DSI/DPI 时序、I2C 背光、FT5x06 触摸、PDM + I2S 音频 |
| `main/Kconfig.projbuild`、`main/CMakeLists.txt` | 新增板型选项与 800×480 字体/表情分支 |
| `config.json` | `CONFIG_ESP_HOSTED_MEMPOOL_PREFER_SPIRAM=y` 等 SDIO/P4 rev1.x 配置 |
| `main/application.cc` | 角色状态联动、说话时忽略服务端 emotion、开机单次握手 |
| `main/ota.cc` | `SetupHttp()` 加 15 秒硬超时，避免开机卡死 |
| `main/idf_component.yml` | 锁定 `espressif/esp_video` 为 `~2.4.1` |
| `scripts/patch_esp_video_caps.py`、`fix_ninja_long_cmd.py` | 构建兼容补丁 |

`board-overlay/` 里是同一批改动的独立副本，可直接覆盖到官方上游源码上。

---

## 六、必须知道的两个坑

1. **开机 boot loop**：ESP32-P4 rev1.0 内部 DMA-capable RAM 只有约 84KB，`esp_hosted` 的 SDIO 内存池会分配失败并断言 `sdio_mempool_create`。本板型已通过 `CONFIG_ESP_HOSTED_MEMPOOL_PREFER_SPIRAM=y` 修复，不要删掉这一行。
2. **「无法连接服务」多半是 C6 从机固件过旧**：日志出现 `Version mismatch: Host [2.13.0] > Co-proc [0.0.0]` 时，调 MQTT 超时、恢复版本检查都无效，需要把 ESP-Hosted 从机固件升到 v2.13.1。仓库里已备好镜像，并支持借现有 SDIO 链路做从机 OTA（无需 USB-TTL），步骤见 [`live2d/README.md`](live2d/README.md) 的「ESP32-C6 ESP-Hosted 从机固件升级」章节。

更多排错（白屏、触摸错位、时间警告等）见 [`docs/BUILD.md`](docs/BUILD.md) 与 `board-overlay` 的板型 README。

---

## 七、许可与致谢

- 固件源码基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) v2.5.3，**MIT 协议**，原文见 [`LICENSE`](LICENSE)；本项目新增的板型、脚本、角色资源与文档同样以 MIT 提供。
- 第三方二进制（C6 从机固件、DFRobot 出厂恢复包）来源与用途见 [`NOTICE.md`](NOTICE.md)。
- 硬件资料来自 DFRobot 官方产品维库；项目文章见 [`article/`](article/)。

`board-overlay/` 与 `docs/HANDOFF.md` 中的盘符、COM 口、Wi-Fi 名称属于原开发环境记录，公开版本已做轻度脱敏，实际编译请以本 README 与 `docs/BUILD.md` 为准。
