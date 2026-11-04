# ATV subshift 1.1.1-local

- **适配了最新版的 Apple TV**：支持 Windows **1.1792.39684.0 x64**，恢复原生字幕翻译，并保留 1.1540.23558.0 的适配。
- **增强了本地模型**：新增 HY-MT1.5 7B（Q6_K）本地增强引擎，结合 F1 语境、赛车术语、上下文和车手名保护进行翻译。

下载 **ATV-subshift-1.1.1-local-win64.zip**，完整解压后运行 `ATV subshift.exe`，保留 `_internal` 文件夹。

原版轻量模型随包提供；增强模型需要另行安装 Ollama 和 HY-MT1.5 7B。安装方法见 [README](https://github.com/shusheng055/ATV-subshift#启用本地增强模型)。现有设置、词表和加密凭据继续沿用；公开包不含个人配置或密钥。

验证：110 项源码测试、31 项打包运行检查通过，增强模型已完成实际推理检查。新版 CEA-608 字幕做过短时实播，仍可能偶发漏译；WebVTT 尚未完成实播验证，不保证其他 Apple TV 版本或所有节目场景。

源码和轻量模型见 **ATV-subshift-1.1.1-local-source.zip**；校验值见 **SHA256SUMS.txt**。该历史发布包的原创部分按发布时的 CC0 许可提供。当前仓库原创部分已改用 [MIT License](LICENSE)，详见 [许可变更说明](RIGHTS-WAIVER.zh-CN.md)；第三方模型与依赖遵循各自许可。
