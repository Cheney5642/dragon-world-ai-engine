# Natural Language Player Creation Runtime v0.1

## 目标

本阶段首次使用真实 LLM，把玩家自由输入的身份描述转换为符合 `schemas/player_creation.schema.json` 的 Grounded Player Creation Result。当前实现是本地 CLI 预览工具，不包含网页、服务器、NPC Agent 或 Event Engine。

## 完整链路

玩家自然语言
→ Player Creation System Prompt
→ LLM Provider Layer
→ Doubao
→ Structured Output
→ 本地 JSON Schema Validation
→ Grounded Player Preview

1. CLI 从 `.env` 加载 Provider、API Key、Base URL 和模型名称。
2. 运行时读取 `world_seed.json`，只提取当前 World Rules 和有效 Location 的 ID、名称与类型，不发送其他无关世界数据。
3. System Prompt 要求模型区分玩家表达和可写入的世界事实，并遵守 “Never punish imagination; ground consequences.”
4. Provider Layer 通过 OpenAI SDK 兼容的 Responses API 和 Structured Outputs，使用 Player Creation JSON Schema 约束模型返回结构，而不仅依赖 Prompt 要求返回 JSON。
5. 收到结果后，CLI 使用 `jsonschema` 和原始 Schema 再做一次本地校验。
6. 通过校验的结果以格式化 JSON 显示，但只作为 Grounded Player Preview。

Structured Outputs 支持 JSON Schema 的一个子集。运行时尽可能直接复用项目 Schema，仅从发送给 API 的副本中移除本地校验专用或 API 不支持的注解与约束；本地校验仍使用未经删减的原始 Schema。

## 为什么暂不写回 World State

当前目标是验证 AI Interpreter 是否能够稳定理解自由身份描述、遵守世界规则并持续生成符合 Schema 的结果。如果现在直接写回 `world_seed.json`，错误解释、边界案例或异常输出可能污染 Persistent World State。

因此 v0.1 只预览结果。等 Interpreter 和测试行为稳定后，再设计独立的确认、提交和持久化流程。

## 环境准备

在项目根目录安装最小依赖：

```text
python -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，然后只在本地 `.env` 中填写真实 Key：

```text
LLM_PROVIDER=doubao

ARK_API_KEY=your_volcengine_ark_api_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-lite-260215
```

`.env` 已被 `.gitignore` 忽略，不应提交到 Git。当前只实现 `doubao`；设置其他 Provider 不会自动回退，而会明确提示尚未实现。

## 运行

交互式创建预览：

```text
python scripts/create_player.py
```

输入一行或多行角色描述，最后输入空行提交。

运行 6 个现有 LLM 测试案例：

```text
python scripts/create_player.py --test
```

测试模式会显示每个案例的输入、实际结果、Schema 校验状态、关键行为检查以及最终 PASS / FAIL。它不会进行复杂的语义评分，也不会修改任何世界数据。
