# 许可与第三方来源说明

## 源码

- `xiaozhi-esp32/` 基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) **v2.5.3**，
  使用 **MIT 协议**，许可证原文见仓库根目录 [`LICENSE`](LICENSE)。
- 本仓库新增的板型适配、构建脚本、角色资源、文档与文章，除下文另有说明外，
  同样按 MIT 协议提供。

## 随仓库提供的第三方二进制

以下文件**不是本项目编译产物**，版权归各自原作者/厂商所有。放在仓库里只是为了让
「下载后能完整复现」更方便；不需要时可直接删除，不影响源码编译。

| 文件 | 来源 | SHA256 |
| --- | --- | --- |
| `firmware/c6-slave/network_adapter_esp32c6_v2.13.1.bin` | pioarduino 预编译 ESP-Hosted 从机固件 v2.13.1，<br>https://pioarduino.github.io/esp-hosted-mcu-firmware/v2.13.1/ | `644a8a22f4073d4f289a47fff1b7b1cfb8e4f6992bb548e8087dcaf4acec937d` |
| `firmware/c6-slave/c6_factory.zip` | DFRobot 官方 C6 出厂恢复包（内含 `C6_v14_eco2_0022.bin`），<br>见 DFR1172 产品维库第 9 章 | `c3e5d3609e9a213264bfc84da870f72c5ee7e45f3a4cca351e35c2ffe9fb76b0` |

如果只想用官方原版，请到上述地址自行下载后核对哈希，再替换仓库内副本。

## 原创角色资源

`live2d/` 与 `article/images/` 中的角色立绘、表情静帧与动画 GIF 由本项目生成并加工，
随仓库一并提供用于本项目演示与二次开发。`live2d/source/` 是三张原始立绘，
`live2d/make_live2d.py` 依赖 `rembg` 的 `u2netp.onnx` 模型（首次运行自动下载，
**不随仓库分发**）。

## 其他

- 编译产物 `firmware/parts/`、`firmware/generated_assets.bin` 中的字体与语音模型
  来自上游 `78/xiaozhi-fonts`、`espressif/esp-sr` 等托管组件，各自遵循其原协议。
- 硬件资料与商品链接来自 DFRobot 创客商城及其官方产品维库。
