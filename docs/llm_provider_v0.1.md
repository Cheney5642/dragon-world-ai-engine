# LLM Provider Layer v0.1

## 什么是 LLM Provider

LLM Provider 是提供大模型推理服务的供应商，例如 Doubao、DeepSeek 或 OpenAI。Player Creation 只负责提出“请把玩家自然语言转换为 Player Creation Result”，不需要知道请求最终发给哪一家服务。

当前调用链是：

Player Creation
→ LLM Provider Layer
→ Doubao

未来可以在 Provider Layer 后增加 DeepSeek 或 OpenAI，但 v0.1 只实现 Doubao，不提前设计复杂的插件或路由系统。

## Provider 配置中的概念

- **API Key**：供应商用于识别和授权调用者的秘密凭证。真实 Key 只能放在本地 `.env` 中，不能写入代码、文档或提交到 Git。
- **Base URL**：SDK 发送请求的 API 服务地址。Doubao 当前使用 `https://ark.cn-beijing.volces.com/api/v3`。
- **Model ID**：供应商用来指定具体模型的标识。当前使用 `doubao-seed-2-0-lite-260215`。

Provider Layer 负责读取 API Key、Base URL、Model ID，并使用对应的模型服务完成请求。当前火山方舟接口兼容 OpenAI Python SDK，因此无需引入新的大型 SDK。

## 为什么 Player Creation 不绑定供应商

World State、Player Schema、Grounding Rules 和 Player Creation Prompt 都属于 Dragon World 自己的产品规则，而不是某一家模型供应商的规则。如果业务逻辑直接创建某个供应商的 Client、更换模型就会迫使核心逻辑一起修改，也更容易意外改变角色创建行为。

通过 `llm/client.py`，Player Creation 只提交 System Prompt、任务上下文和 Schema，并接收结构化结果。供应商差异被限制在一个很小的边界内。

## 当前为什么先使用 Doubao

v0.1 先使用 Doubao-Seed-2.0-lite 验证中文自然语言 Player Creation 的完整链路。当前只实现一个 Provider，能保持原型简单，并让真实请求出现的 Structured Output 兼容性问题更容易定位。

如果火山方舟对现有 Structured Output 参数返回不兼容错误，Provider Layer 会明确显示请求错误。系统不会静默切换模型、绕过 Schema，或修改 Grounding 规则。

## 未来切换模型时什么保持不变

以下内容不需要改变：

- World State
- Player Schema
- Grounding Rules
- Player Creation Prompt

只有 `.env` 中的 Provider 配置和 `llm/client.py` 中少量供应商适配代码需要变化。设置尚未实现的 Provider（例如 `deepseek`）会直接提示尚未实现，不会自动回退到 Doubao 或其他模型。

## 当前环境变量

```text
LLM_PROVIDER=doubao

ARK_API_KEY=your_volcengine_ark_api_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-lite-260215
```

真实 `ARK_API_KEY` 应填写在项目根目录 `.env` 中；仓库中的 `.env.example` 只保留空值模板。
