# API 模型目录 · 2026-10-14 核对

只列文本翻译可使用的模型；包括新旧通用模型与部分可处理文本的编程型号。
不收录已下线、仅音频/图像/嵌入或仅在 ChatGPT/Codex 客户端可用的型号。
目录不是账户授权清单，实际调用仍取决于地域、额度与模型权限。
“省钱/均衡/旗舰”是服务商内的相对定位，不代表跨服务商价格排序或翻译质量实测。
已公布的停用日期到期后自动隐藏，并阻止继续使用该目录选项；未公告的新变更需更新目录。
同一模型的主线别名和日期快照分别列出，别名可能随服务商更新。

| 服务商 | 收录范围 | 核对来源 |
| --- | --- | --- |
| OpenAI | GPT-4o、4.1、o1/o3/o4、GPT-5、5.1、5.2、5.4、5.5、5.6、6/6.1 的仍可用文本型号 | [模型](https://developers.openai.com/api/docs/models)、[停用表](https://developers.openai.com/api/docs/deprecations)；各型号独立页面 |
| Gemini | 2.5 三款、3 系列仍独立提供服务的文本型号、Gemini 4 Argon | [模型](https://ai.google.dev/gemini-api/docs/models)、[生命周期](https://ai.google.dev/gemini-api/docs/deprecations)、[Argon](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon) |
| Claude | 当前 Haiku/Sonnet/Opus/Fable/Mythos 与仍可用的往代型号 | [状态表](https://platform.claude.com/docs/en/about-claude/model-deprecations) |
| DeepSeek | V4.1 Flash、V4 Pro 对应官方 ID | [价格与型号](https://api-docs.deepseek.com/quick_start/pricing/)、[更新](https://api-docs.deepseek.com/zh-cn/updates/) |
| Qwen | 专用 MT Lite/Flash/Plus，3.8/3.7/3.6/3.5、旧 Plus/Max/Flash/Long，仍在目录的日期快照 | [文本型号](https://help.aliyun.com/zh/model-studio/text-generation-model)、[MT](https://help.aliyun.com/zh/model-studio/machine-translation)、[生命周期](https://help.aliyun.com/zh/model-studio/model-depreciation) |
| Kimi | K3、K2.6、K2.7 Code 与 HighSpeed | [当前及停用型号](https://platform.kimi.ai/docs/models)、[接口](https://platform.kimi.ai/docs/overview) |

重要筛选：Kimi K2/K2.5 与 Moonshot v1、DeepSeek 旧 chat/reasoner、Claude 3.x 与 Opus 4/4.1、
Gemini 1.5/2.0、GPT-4.5/o1-mini/o1-preview 均不加入选择列表。
Qwen MT Turbo 已在 2026-10-10 停用，尽管旧版价格页的缓存仍列出价格，也不收录：
[官方停用通知](https://www.alibabacloud.com/en/notice/model_studio_notice_of_retirement_for_selected_legacy_longtail_models_7d4?_p_lc=1)。
Gemini 的 2.5 型号仅限以前使用过的账户，已在界面标明；3.5/3.7 Flash 自动路由别名
不当作可独立选择的旧权重版本。DeepSeek 已不存在官方可单独调用的 V2/V3/R1 原始权重入口，
因此不编造历史模型 ID。Claude Mythos 明确标注受限访问。

## 接口与术语

内置目录自动选择接口：OpenAI 新型号走 Responses，经典 GPT-4 系列走 Chat Completions；
Kimi/DeepSeek/Qwen 通用型号走 Chat Completions；Claude 走 Messages；Gemini 走 generateContent。
自定义服务仍可手动填写型号及选择上述格式。URL 保持可编辑；阿里云需从自己的控制台
复制含地域、业务空间的 Base URL，不能用占位地址直接调用。

普通模型收到字幕翻译指令、当句命中的热词和 0–5 权重；不翻译词汇仍在共同流程中保护。
Qwen MT 使用单条 user 消息和 translation_options，术语映射进入 terms，偏好及权重进入
domains，不发送不支持的 system 消息。API 权重是提示偏好，不等于模型内部概率权重。
DeepSeek、Kimi K2.6、Qwen 混合模式关闭思考；K3 使用 low；GPT-6 按型号选择 none/low。
始终思考或 Pro 型号可能超过现有字幕期限，超时/截断时保留原文，不显示半句或思考内容。

请求格式依据：[OpenAI Responses](https://developers.openai.com/api/docs/guides/text)、
[Claude Messages](https://platform.claude.com/docs/en/api/messages)、
[Gemini 文本](https://ai.google.dev/gemini-api/docs/text-generation)、
[DeepSeek 思考开关](https://api-docs.deepseek.com/guides/thinking_mode/)、
[Kimi K2.6](https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart)。

Gemini 4 Argon 使用 low 思考和官方建议的至少32K输出上限；上限不代表强制生成32K。
实际字幕仍限制3000字符，截断/超时不显示半句。此型号的
[GenerateContent 示例](https://ai.google.dev/gemini-api/docs/generate-content/latest-model) 与
[Gemini 3.8 示例](https://ai.google.dev/gemini-api/docs/generate-content) 已核对。
Kimi 国内地址来自[国内站官方快速开始](https://platform.kimi.com/docs/get-api-key)。

所有自动化调用测试均使用本机模拟服务，不使用用户 Key，不消耗真实 API 额度。
模拟测试证明接口请求、响应提取及异常回退；不代表逐型号真实账户调用或翻译质量验收。
