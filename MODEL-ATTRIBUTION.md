# 本地增强引擎

本机增强配置使用腾讯 HY-MT1.5 7B，作者发布的 Q6_K GGUF 本地模型版本，
通过本机 Ollama 服务运行。此应用目录不包含该模型权重；模型由 Ollama 独立管理。

模型及其许可、模型卡：https://huggingface.co/tencent/HY-MT1.5-7B-GGUF

应用提供 F1 领域说明、
已有用户词表、有限上下文和保留词校验。这不是 F1 专项微调模型，质量需要实际样句验证。

# English - Chinese version 1.9

Authors: Jörg Tiedemann and Santhosh Thottingal
Title: "OPUS-MT — Building open translation services for the World"
Book Title: Proceedings of the 22nd Annual Conference of the European Association for Machine Translation (EAMT)
Year: 2020
Location: Lisbon, Portugal

The original OPUS model from which this packaged model is derived is licensed CC-BY 4.0
