# ATV subshift 1.0.0

基于 0.1.13 的首次正式发行，为 Apple TV Windows 客户端提供即时英文字幕翻译。

- 默认 **Local 离线英译简中、浅色模式**，内置完整模型，无需首次下载或 API Key。
- 保留“赛车”预设：**50 条热词、192 条不翻译词汇，热词权重 3.0**。
- 通过 Frida 读取经校验的原生字幕输入，将译文交回 Apple TV 原有 CoreText / QuartzCore 字幕路径。
- 保留半句保守翻译、阅读队列、滞后追赶、字幕切换与资源占用管理。
- 开发过程中使用了 **REA（Reverse Engineer Anything）+ Ghidra** 分析相关原生模块与字幕调用路径；REA 无需随软件运行。
- **本软件的项目原创部分完全由 AI 生成**，包括代码、界面、集成脚本、测试、文档和打包流程。第三方库、模型和工具仍属于各自原作者。
- **发布者放弃本人对本软件原创部分一切可依法放弃的权利**，采用 CC0 1.0，并附补充权利放弃声明；第三方许可保持不变。
- 公开文件不包含发布者的 API Key、加密凭据、个人配置或诊断数据。

## 下载

一般使用者下载 **ATV-subshift-1.0.0-win64.zip**，完整解压后双击 `ATV subshift.exe`，保留 `_internal` 文件夹。
源码及离线模型见 **ATV-subshift-1.0.0-source.zip**。使用 **SHA256SUMS.txt** 核对压缩包。

## 兼容性与验证

Windows 11 x64；原生接入针对 **Apple TV 1.1540.23558.0 x64**。
**95/95 项源码测试、31/31 项打包运行检查通过**，含真实离线模型和本机模拟 API。
本次发布未新增真实 Apple TV 长时间播放测试，不保证其他客户端版本或所有节目场景。

权利声明与依赖说明见仓库中的 `LICENSE`、`RIGHTS-WAIVER.zh-CN.md`、`AI-GENERATED.md` 和 `THIRD-PARTY-NOTICES.md`。
