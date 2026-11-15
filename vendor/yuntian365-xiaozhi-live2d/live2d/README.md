# 小智 Live2D 角色（ESP32-P4 设备端）

原创二次元 AI 少女「小智」：银白长发、青色耳机与 Wi-Fi 天线、白蓝科技制服。
为 FireBeetle 2 ESP32-P4 + DFR0678 800×480 DSI 屏的小智 AI 固件（v2.5.3）制作，
走固件现有的 LVGL 表情通道。表情资源与深色主题都在 `index.json` 里声明，**零 C++ 改动**；
「待机 / 说话自动播放 GIF」的状态联动改了 `main/application.cc`（见下方「状态联动」）。
**当前为 v9 肢体动作版**：动画不再只有整图缩放，头、发梢、双臂与胸腔都有独立的连续运动。

## 效果

- 分层立绘 + 局部图层替换：基础 / 闭眼 / 张嘴三张一致性立绘合成动画
- `idle.gif`：**20 帧 / 90 ms**（1.8 s 循环），头摆 + 发梢飘动 + 双臂反相摆动 + 胸腔呼吸 + 随机眨眼
- `speaking.gif`：**12 帧 / 90 ms**（1.08 s 循环），口型开合叠加同套肢体动作（幅度 ×1.15）
- `happy_anim.gif`：**14 帧 / 90 ms**（1.26 s 循环），幅度 ×1.35 的开心循环
- 21 个情绪静帧：沿用固件原有 emotion 关键字（happy / sad / angry / thinking / winking …），
  叠加眉形、腮红、泪滴、墨镜、爱心、问号、Zzz 等装饰与氛围色调

资源规格：**280×340 RGBA PNG / 透明 GIF**，居中显示（LVGL 按原尺寸渲染），
文件名即 emotion 名，全部 ≤ 31 字节。三组动画共 46 帧。

> 这不是 Cubism `.moc3` / Live2D runtime，而是**伪 Live2D**：在 PC 端用 Python 逐帧生成
> 连续网格变形 GIF，设备端仍走原有 `LvglGif` 播放链路，零额外解码开销、零 SDK 依赖。
> 详见下方「v9 肢体动作」。

## 目录

| 路径 | 说明 |
| --- | --- |
| `preview.html` | 模拟 800×480 P4 屏幕的交互预览，可切换 21 个表情 + 3 个动画 |
| `assets/xiaozhi-live2d/` | 24 个表情资源（21 PNG + 3 GIF）+ `index.json`（31 个条目） |
| `xiaozhi-live2d-assets.bin` | 已合并好的 assets 分区镜像（**7.898 MiB / 8 MiB**），可直接烧录或 OTA |
| `build_assets_bin.py` | 在现有 `generated_assets.bin` 上替换表情条目、注入深色 `skin` 与系统别名，保留字体与语音模型 |
| `make_live2d.py` | 从三张源立绘重新生成全部资源（依赖 `rembg` u2netp、numpy、opencv-python） |
| `source/` | 三张原始 AI 立绘（基础 / 闭眼 / 张嘴） |
| `motion_check.png` | v9 动画逐帧检查图（idle 7 帧 + speaking 6 帧） |
| `speaking_check.png` | 早期口型/睁眼逐帧诊断图（对照 neutral / happy / sleepy） |

## 三种集成方式

### A. 零重编译（推荐，用现成的 `xiaozhi-live2d-assets.bin`）

1. `idf.py menuconfig` → `Xiaozhi Assistant` → `Flash Assets` → 选 **Flash Custom Assets**
2. `CONFIG_CUSTOM_ASSETS_FILE` 指向本目录下的 `xiaozhi-live2d-assets.bin`
3. 重新烧录 assets 分区即可；也可以把该 bin 放服务器走 `Assets::Download()` OTA 下发

该 bin 已包含原固件的 `font_noto_sans_common_30_4.bin`、`srmodels.bin` 与新表情，
checksum 已按官方格式计算并回读校验通过。

### B. 随固件一起编译

```powershell
Copy-Item -Recurse assets\xiaozhi-live2d C:\xz\xiaozhi-esp32\managed_components\78__xiaozhi-fonts\png\xiaozhi-live2d
```

把 `main/CMakeLists.txt:132` 的：

```cmake
set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)
```

改成：

```cmake
set(DEFAULT_EMOJI_COLLECTION xiaozhi-live2d)
```

然后正常 `build.py` 重新编译。注意 `build_default_assets.py` 只扫描 `.png` / `.gif`，
会自动生成 `index.json` 的 `emoji_collection`。

### C. 换一套底包后重新打包

```powershell
python build_assets_bin.py --base C:\xz\xiaozhi-esp32\build\generated_assets.bin --out xiaozhi-live2d-assets.bin
```

切换语言（en-US / zh-CN）会重新生成 `generated_assets.bin`，此时应重跑一次本脚本，
否则语音模型与字体版本会和新固件不一致。

## 深色主题

`build_assets_bin.py` 会在 `index.json` 里写入 `skin`（`assets.cc` 的
`LvglStrategy::Apply()` 消费，`LvglTheme::ParseColor()` 接受 `#RRGGBB`）：

```json
"skin": {
  "light": {"text_color": "#E8F2FF", "background_color": "#101826"},
  "dark":  {"text_color": "#EAF4FF", "background_color": "#0B1220"}
}
```

`light` / `dark` 两套主题都覆盖，不论设备当前用哪套主题，角色都站在深色背景上；
`background_color` 会同时应用到 `chat_background_color`。`preview.html` 已同步为深色配色。

注意：`skin` 由 `assets.Apply()` 在激活流程中应用，**配网模式（未连 Wi-Fi）阶段仍是固件默认主题**，
配网完成后才变成深色。

## v9 肢体动作（已烧录，2026-11-10）

用户反馈「角色有些僵硬，身体只是在大小变化，没有其它动作」。难点不在设备端——
P4 上跑的是 `LvglGif` 逐帧播放，没有骨骼引擎，也不适合引入 Cubism runtime
（要 SDK 授权、额外 RAM 与解码开销）。所以选择在 **PC 端生成**时做「伪 Live2D」：

`make_live2d.py` 新增 `pose_warp(img, phase, amp)`，不做图层硬切（半身立绘没有分层 PSD，
硬切会露接缝），而是构造 2D 高斯权重场后用 `cv2.remap` 对整张 RGBA 做一次连续重采样：

| 部位 | 权重场（280×340 画布实测） | 运动 |
| --- | --- | --- |
| 头部 | `gauss(yy,105,95)` | `sin(p)` 左右摆 + `sin(p+0.4)` 上下微动 |
| 左侧发 / 右侧发 | `gauss(xx,55,48)` / `gauss(xx,225,48)`，随 y 渐强 | `sin(p+1.2)` 反相飘动 |
| 左臂 / 右臂 | `gauss(xx,32,36)` / `gauss(xx,248,36)`，随 y 渐强 | `sin(0.75p+2.1)` 反相摆动 |
| 胸腔 | `gauss(yy,245,55)*gauss(xx,140,85)` | `0.5-0.5cos(p)` 局部呼吸起伏 |

各部位用**不同频率与相位**，避免所有部位同步运动造成机械感；底边 40 px 锚定防止露出透明缝；
`dx/dy` 过 0.12 px 软阈值把远端微小位移归零，保证连续、不产生接缝，同时压小帧间差分。
`compose()` 增加 `pose` / `amp` 参数，静帧不调用 `pose_warp`（保持 21 张 PNG 不变），
三组动画分别用 `amp=1.0 / 1.15 / 1.35`。

**体积是真正的难点**：第一版加了全局 sway，GIF 从 1.35 MB 涨到约 2.17 MB，
直接撑爆 8 MB assets 分区。最终靠三点压回来：

1. 移除全局 sway，只保留局部权重场（静止区域像素完全一致）；
2. `save_gif()` 固定 96 色调色板、`dither=0`、后续帧复用首帧调色板，避免逐帧量化抖动；
3. 帧数从 12/6/8 提到 **20/12/14**（90 ms，比原来 120 ms 更顺），但靠局部差分把
   总 GIF 控制在 880,857 + 527,391 + 613,157 B。

结果 `xiaozhi-live2d-assets.bin` = **8,282,027 B（0x7e5fab，7.898 MiB）**，
checksum 回读通过，已只烧到 `0x800000`。

> ⚠️ **分区余量只剩 106,581 B（约 104 KiB）**。再加任何资源前必须先压缩：
> 优先降 `colors`（96 → 64）、减 `happy_anim` 帧数，或砍掉不常用的静帧。
> 当前配置不能再增加表情条目。

`motion_check.png` 是逐帧目视检查图，确认头部 / 发梢 / 手臂动作自然、无接缝、
撕裂、透明空洞或变形失真，眼睛与嘴巴正常。

## 状态联动（v2，已编译进固件）

`main/application.cc` 增加了模板辅助函数 `SetCharacterEmotion(display, emotion)`：
`SetEmotion()` 成功则打一条 `Character emotion: xxx` 日志；失败（没有自定义 assets 包）
则回退 `neutral`，保持上游行为。在 `HandleStateChangedEvent()` 里：

| 状态 | emotion | 效果 |
| --- | --- | --- |
| `idle` / `connecting` / `listening` | `idle` | 呼吸 + 眨眼 GIF |
| `speaking` / `notifying` | `speaking` | 口型开合 GIF |
| `DismissAlert()` 回到待机 | `idle` | 恢复待机动画 |
| `Activate()` 末尾 | `idle` | 开机即播动画，不再尝试 `robot_2` |

**v3 修复（用户反馈「说话时角色不动且闭眼」）**：服务端 `"llm"` 消息会在 TTS 流期间
持续下发 `emotion`，原先的异步 `SetEmotion()` 会把 `speaking.gif` 换成静帧
（`happy.png` / `sleepy.png` 都是闭眼图），看起来就是「不动 + 闭眼」。现在 `application.cc`
的 `llm` 分支在 `kDeviceStateSpeaking` / `kDeviceStateNotifying` 状态下忽略服务端 emotion，
并打一条 `Skip server emotion 'xxx' while speaking` 日志；**不重新调用 `SetEmotion`**，
避免每次分句都把 GIF 从第 0 帧重启。非说话状态仍照常显示服务端情绪表情。

`assets/xiaozhi-live2d/speaking.gif` 本身是 12 帧全睁眼、口型开合 + 肢体动作的 90 ms 动画，
`motion_check.png`（v9 肢体动作）与 `speaking_check.png`（早期口型/睁眼诊断）是逐帧检查图。

GIF 由 `LvglRawImage` → `LvglGif` 自动循环播放，切换 emotion 时会停止旧动画。

## 系统弹窗 emotion 别名

固件 `Alert()` 在错误、配网、升级等界面用的是 7 个系统级 emotion 名
（`application.cc` / `wifi_board.cc`）：`warning`、`cancel`、`cloud_download`、
`cloud_off`、`link`、`download`、`gear`。它们不在 21 个角色情绪里，缺失时会
fallback 到 material_symbols 字体图标并打 `Emoji not found: xxx` 警告。
`build_assets_bin.py` / `make_live2d.py` 会把这 7 个名字作为**别名**注入
`emoji_collection`，指向现有静帧（如 `cloud_off → sad.png`、`gear → thinking.png`），
所以任何界面都显示角色。`index.json` 因此是 **31 个条目**（24 个角色 + 7 个别名），
多个 name 指向同一文件，assets 只存一份图片，体积不变。

## 注意事项与限制

- assets 分区 8 MB；当前 v9 包 **7.898 MiB，余量仅 104 KiB**，几乎占满。
  再加资源前先按「v9 肢体动作」里的压缩手段腾空间，否则打包会超限。
- GIF 解码用 ARGB8888 帧缓冲（`w*h*4`），280×340 约 381 KB；不要做全屏 GIF。
  20/12/14 帧 @ 90 ms 在 P4 上实测流畅，LVGL 只做 GIF 帧切换，无额外 CPU 负担。
- 资源必须是 **8-bit RGBA PNG 或透明 GIF**；`.jpg`、LVGLImage.py 转出的 `.bin` 不被这条链路消费。
- `index.json` 的 `version` 必须为 1；条目不要带 `eaf` 字段（会被跳过）。
- 文件名 ≤ 31 字节（表项 `asset_name[32]` 需留 NUL）。
- 背景抠图用 `rembg` u2netp 语义分割。纯颜色/GrabCut 分割对这张图无效：
  银白头发与白色制服的色值和灰色背景太接近，会把角色内部挖出黑洞。
- 若重新生成：`python -m pip install pillow numpy opencv-python "rembg[cpu]"`，
  首次运行会自动下载 4.7 MB 的 u2netp.onnx 模型。
- **整片烧录 `0x0` 的合并镜像会擦掉 NVS 中的 Wi-Fi 凭据**
  （日志 `SsidManager: NVS namespace wifi doesn't exist`），设备会重新进入配网模式。
  仅更新 app / assets 时建议只烧这两个分区，避免重新配网：
  `esptool ... write_flash 0x20000 xiaozhi.bin 0x800000 xiaozhi-live2d-assets.bin`。

## 与固件编译状态的关系

本资源包基于 `C:\xz\xiaozhi-esp32\build\generated_assets.bin`（zh-CN 构建）生成。
若固件后续重新 configure 或更换语言，按方式 C 重跑一次打包脚本即可。

## 当前已烧录镜像（2026-11-10）

`firmware/xiaozhi-p4-dfr0678-zh-CN_live2d_dark_merged_0x0.bin`
（**v9：肢体动作资源 + 说话修复 + 系统别名 + 单次握手 + C6 从机 v2.13.1**）：
`16,670,635 B = 0xfe5fab`，
SHA256 `96edc1091614ea3f001ddc50ab96f9dfaf9ed3153a5229834308d4fd0590d8a8`。
其中 assets 分区镜像 `xiaozhi-live2d-assets.bin` = `8,282,027 B = 0x7e5fab`，
SHA256 `31a1583bc627df838fce16f23323e39d11a44a9c160bb1e29d9bfa50c26b8cf6`。
整片镜像为 16MB / dio / 80m，从 `0x0` 烧录会擦 NVS（需重新配网）。

**分区更新策略**：v3 / v5 只烧 app（`0x20000`），v4 / v9 只烧 assets（`0x800000`）——
都不动 NVS，设备重启后直接连回 `YOUR_WIFI_SSID`。当前设备里 app 与 v7 相同
（`Compile time: Nov 10 2026 15:30:07`），**v9 只是换了 assets 分区**，所以无需重编译固件。

**v9 实机验证**（`firmware/com4_motion_verified2.log`）：

```
I (2559)  transport: got co-processor transport size: 1536
I (2580)  transport: co-processor transport size matches host transport size: 1536
I (6718)  WifiStation: Got IP: 192.168.1.100
I (6736)  Assets: The assets map size is 8128 KB (partition 8192 KB)
I (7078)  Assets: The checksum calculation time is 335 ms
I (7083)  Assets: Refreshing display theme...
I (7142)  Application: Character emotion: idle
I (8409)  Application: Boot config handshake ok (firmware version check disabled)
I (9402)  MQTT: Connected to endpoint
I (9402)  Application: Activation done
I (9487)  Application: Character emotion: idle
```

`assets map size` 从 v7 的 7488 KB 变为 **8128 KB**，证明新资源包已生效；
全日志无 `Emoji not found`、无 GIF 解码错误、无 `Version mismatch`。
剩余 3 条启动告警（I2S DMA 对齐、`0 mac type is incorrect`、SDIO 复位从机）
均为已知无害项，与表情资源无关。

另有一次开机出现 `WifiStation: WiFi disconnected, reason: 2` 两次、37 秒才拿到 IP，
随后 443/8883 超时（`com4_motion_verified.log`）；同网络 PC 测两个端口均通，
重启一次即恢复。这是偶发 Wi-Fi 认证超时，不是资源或 C6 固件回退。

回退镜像：

- `firmware/xiaozhi-p4-dfr0678-zh-CN_live2d_merged_0x0.bin`（角色资源，无深色、无联动）
- `firmware/xiaozhi-p4-dfr0678-zh-CN_newpc_merged_0x0.bin`（原版表情，无角色）

编译注意：只改 `application.cc` 时不要走 `idf.py reconfigure`，直接 `ninja -C build -j 4 all`
增量编译即可；裸 ninja 需补 `IDF_PATH` / `ESP_IDF_VERSION=6.1.0` / `IDF_TARGET=esp32p4`，
否则 `ldgen.py` 解析 Kconfig 时 `$(ESP_IDF_VERSION)` 展开为空而失败。

## 错误排查：检查新版本失败 / 无法连接服务

串口里可能出现：

```
E HttpClient: Wait for HTTP headers receive timeout
E Ota: Failed to read HTTP status / Failed to open HTTP connection
W Application: Alert [cloud_off] 错误: 检查新版本失败，将在 10 秒后重试…
E MQTT: Failed to connect to endpoint: Connection timed out
W Application: Alert [cancel] 错误: 无法连接服务，请稍后再试
```

这些是 `api.tenclass.net` 连接超时，**不是角色资源或固件缺陷**：同一网络下 PC 测试
443 / 8883 均可达（DNS `47.112.110.152` 与设备一致），设备有的轮次
`Ota: Current is the latest version` / MQTT 连接成功；`CheckNewVersion()` 会
按 10 秒起、指数退避自动重试 10 次。

最可疑的根因是日志里长期存在的 `Version mismatch: Host [2.13.0] > Co-proc [0.0.0]`：
ESP32-C6 的 ESP-Hosted 从机固件过旧，TLS 握手偶发慢到 5.8~8.8 秒。
建议顺序：观察是否自愈 → 重启设备 / 靠近路由器 → 按 DFRobot wiki 升级 C6 从机固件。

注意：禁用开机版本检查后，`检查新版本失败` 这条错误会彻底消失；
`无法连接服务，请稍后再试` 是 **MQTT 8883 连接失败**，与版本检查无关。
该问题在 2026-11-10 升级 C6 从机固件后已根治，目前只在偶发 Wi-Fi 认证超时
（`WifiStation: WiFi disconnected, reason: 2`）导致拿不到 IP 时短暂出现，重启即恢复。

进一步排查（2026-11-10）：本机连 `api.tenclass.net:8883` TCP 0.08 s、TLS 握手 0.14 s、
证书 CN=api.tenclass.net，服务端与宽带完全正常；设备侧则是
`esp-tls: [sock=54] delayed connect error: Software caused connection abort` /
`ESP_ERR_ESP_TLS_FAILED_CONNECT_TO_HOST`，即 **TCP connect 阶段被中止**。
把 `MQTT_CONNECT_TIMEOUT_MS` 与 `esp_mqtt_client_config_t.network.timeout_ms`
从 10 s 放宽到 40 s 做过实验，错误只是从「超时」变成「连接中止」，**无效，已回退**。
根因是 ESP32-C6 ESP-Hosted 从机固件过旧（日志长期
`Version mismatch: Host [2.13.0] > Co-proc [0.0.0]`）——**已通过升级从机固件解决，见下节**。

跳过 `CheckVersion()` 时曾出现 `Display: System time not set (tm_year=70)` 每 10 秒刷屏
（丢了 `server_time`）；现在单次握手成功会写入服务器时间，该警告已消失
（`CONFIG_MBEDTLS_HAVE_TIME_DATE is not set`，TLS 不受影响）。

## 开机不再检查新版本（v7：单次握手）

`main/application.cc` 顶部开关（`0` = 恢复上游完整版本检查）：

```cpp
#define SKIP_BOOT_VERSION_CHECK 1
```

`CheckVersion()` 不只是查版本，还下发 MQTT/WebSocket 凭据、激活数据与 `server_time`。
完全跳过会让凭据无法刷新、系统时间停在 1970；保留原流程又会弹「检查新版本失败」。
因此改成：

- 开机只做**一次** `CheckVersion()` 握手：不显示「检查新版本」状态、不比较版本、
  不 OTA、不重试、失败静默沿用 NVS 缓存；
- 打 `Boot config handshake ok/failed` 日志，仍保留激活码流程与
  `MarkCurrentVersionValid()`（OTA 回滚标记）；
- `main/ota.cc` 的 `SetupHttp()` 加 `http->SetTimeout(15000)` 硬超时——
  实测无超时时该请求会挂起 60 秒以上，把开机流程卡死；
- `InitializeProtocol()` 的协议选择同时参考 NVS 缓存。

`CheckAssetsVersion()` 不动（只做本地 `assets.Apply()`）；`self.upgrade_firmware`
走 `UpgradeFirmware(url)`，手动升级不受影响。

**当时的实测结论（已被后续 C6 升级推翻，保留作排查记录）**：升级从机固件之前，
这台设备连 443 与 8883 都失败（`HttpClient: TCP connection failed` /
`esp-tls: Software caused connection abort`），而同一网络下 PC 测两个端口 TCP+TLS
均在 0.22 秒内完成，因此握手失败、MQTT 连不上、`tm_year=70` 都会出现。
日志：`firmware/com4_boot_handshake_timeout.log`。
**最终根因与解法见下节**：升级 ESP32-C6 ESP-Hosted 从机固件到 v2.13.1 后，
`Boot config handshake ok` / `MQTT: Connected to endpoint` / `Activation done`
全部恢复，开机约 9.4 秒完成激活。

`CONFIG_MBEDTLS_HAVE_TIME_DATE is not set`，时间未同步不会导致 TLS 证书校验失败。

## ESP32-C6 ESP-Hosted 从机固件升级（已完成，网络问题根治）

**根因**：P4 host 用 `esp-hosted-mcu 2.13.0`，板载 C6 出厂旧固件不报告版本
（`Co-proc [0.0.0]`、`Co-processor fw did not report transport size`），
协议不匹配导致设备侧 443/8883 连接全部异常。之前所有软件层改动（放宽超时、
恢复握手）都只是绕开表象。

**目标固件**：`network_adapter_esp32c6.bin` **v2.13.1**
（pioarduino 预编译 `https://pioarduino.github.io/esp-hosted-mcu-firmware/v2.13.1/`；
`App version: 2.13.1`、ESP-IDF v5.5.5、1,228,160 B、
SHA256 `644a8a22f4073d4f289a47fff1b7b1cfb8e4f6992bb548e8087dcaf4acec937d`），
满足 slave >= host。网页安装器内置的 `2.0.17` 实际 `App version: 1`，比 host 更旧，未采用。

**升级方式：SDIO OTA**（无需 USB-TTL、无需浏览器），复用项目自身已验证的 SDIO 配置：

1. 从机镜像烧到 P4 空闲的 `ota_1` 分区 `0x410000`（4 MB，足够）；
2. 临时固件在 `ActivationTask()` 开头一次性调用
   `esp_hosted_slave_ota_begin()` → `write()`（1480 B/块，共 830 块）→ `end()`；
   从 `ota_1` 读取镜像，按 ESP32 镜像头算出长度；旧 slave 不支持
   `GetCoprocessorFwVersion` 与显式 `activate`，按官方示例跳过即可；
3. 成功后擦掉 `ota_1` 前 4 KB 防重复执行，`esp_restart()` 让 P4/C6 重新同步；
4. 移除一次性代码 → 编译烧回正式 app → `esptool erase-region 0x410000 0x3f0000` 清场。

NVS 配网与 assets 分区全程未动；C6 采用双 OTA 分区，写入校验通过才激活，失败会保留原固件。

**升级后验证**（`firmware/com4_c6_slave_ota.log` / `com4_final_verified.log`）：

```
I (2559) transport: got co-processor transport size: 1536
I (2580) transport: co-processor transport size matches host transport size: 1536
I (8628) Ota: Current is the latest version
I (8629) Application: Boot config handshake ok
I (9635) MQTT: Connected to endpoint
I (9636) Application: Activation done
```

`Version mismatch` 警告、`无法连接服务`、`tm_year=70` 全部消失，开机约 9.7 秒完成激活。

**恢复镜像**（万一以后需要 USB-TTL 直烧）：`firmware/c6_factory.zip`
内 `C6_v14_eco2_0022.bin`，DFRobot wiki 第 9 章有 C6 测试点接线图；
源码 `https://github.com/espressif/esp-hosted-mcu/tree/main/slave`。
