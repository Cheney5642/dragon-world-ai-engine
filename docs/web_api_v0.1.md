# Dragon World Web API v0.1

## 1. Frontend 是什么

Frontend 是玩家直接看到和操作的界面。未来的 Dragon World Frontend 会展示玩家、当前地点和附近 NPC，并让玩家输入自然语言行动。Step 5.4.1 尚未实现 Next.js 或 React 页面。

## 2. Backend 是什么

Backend 是运行在服务器端的程序。它读取 Persistent World State，调用 Dragon World Core，校验请求，并且只在符合安全条件时提交状态变更。当前 Backend 使用 FastAPI。

## 3. API 是什么

API 是 Frontend 与 Backend 之间的结构化交互边界。Frontend 发送 HTTP Request，FastAPI 返回 JSON Response。API 不向 Frontend 暴露 API Key、System Prompt、NPC 隐藏数据或服务器环境变量。

## 4. Client / Server 是什么

- Client：发起请求的一方，例如未来的浏览器页面。
- Server：接收请求、调用核心引擎并返回结果的一方，即当前 FastAPI 应用。

## 5. 为什么 CLI 与 Web 必须复用 Core Logic

Action Interpreter、World Validator 和 Action Executor 不能各自再写一套 Web 版本。否则 CLI 和 Web 会出现不同的 Grounding、Validation 或 Mutation 规则。

`core/action_pipeline.py` 只编排已冻结模块提供的函数：

```text
CLI -------------------↘
                        Dragon World Core Pipeline
FastAPI ---------------↗
```

Core 继续使用现有 Prompt、Schema、LLM Provider、确定性 World Validation 与 Executor Mutation 白名单。Web API 不复制这些规则。

## 6. HTTP Request / Response

HTTP Request 是 Client 发给 Server 的请求，包含路径、方法和可选 JSON Body。HTTP Response 是 Server 返回的状态码与 JSON 结果。

例如：

```text
POST /api/action/preview
Request:  {"input": "我去Stormcliff。"}
Response: {"interpretation": ..., "validation": ..., "execution_plan": ...}
```

## 7. GET 和 POST 的基础区别

- GET 用于读取资源。`GET /health` 读取服务状态，`GET /api/world` 读取世界摘要。
- POST 用于提交输入并请求服务器处理。Action Preview 虽然使用 POST，但它仍然是 Read Only。Action Commit 在所有校验通过后才可能写入 Save。

## 8. 为什么 `/preview` 必须 Read Only

LLM 输出只是候选解释，不是已发生的世界事实。`POST /api/action/preview` 运行：

```text
Action Interpreter
→ World Validator
→ Action Executor Plan
```

它只返回 Interpretation、Validation 和 Execution Plan，不调用 Commit，因此不修改 `current_world.json`。

## 9. 为什么 `/commit` 必须在后端重新验证

Frontend 是不可信输入边界。如果 API 接受 Frontend 传入的 `new_location` 或 `proposed_mutations`，Client 就可以绕过 World Validator 与 Mutation 白名单。

v0.1 Commit Request 只接受原始行动文本：

```json
{
  "input": "我去Stormcliff。"
}
```

Backend 会基于最新 Save 重新运行：

```text
Interpret
→ Validate
→ Build Execution Plan
→ Validate Mutation Allowlist and latest old_value
→ Atomic Commit
```

当前唯一允许的 Mutation 仍然是 `player.current_location`。`needs_clarification`、`blocked`、`conditional`、无效实体、过期 old value 或非直连 Location 都不会 Commit。

## 10. FastAPI 在 Dragon World 架构中的位置

```text
Browser
↓ HTTP
FastAPI
↓
Dragon World Core
↓
Persistent World State
```

FastAPI 是 HTTP Bridge，不是第二套 World Engine。

## 11. API 端点

### `GET /health`

返回服务存活状态：

```json
{
  "status": "ok",
  "service": "dragon-world-api"
}
```

### `GET /api/world`

从 `data/saves/current_world.json` 读取适合 UI 的最小摘要：Player 公开字段、World 时间与天气、当前 Location，以及同地点 NPC 的公开目录信息。它不返回 NPC Memory、Relationship、Knowledge、Prompt 或 Secret。

### `POST /api/action/preview`

三层 Action Pipeline Preview，永远 Read Only。如果 Intent 需要 clarification，或 Validation 为 blocked / conditional，响应会保留已完成的结构化阶段，未运行的后续阶段为 `null`。

### `POST /api/action/commit`

只接受 `input`，不接受 Client 生成的 Mutation。该 POST 代表用户在 Frontend Preview 后的明确确认。Backend 仍会重新运行完整 Pipeline，并在写入前重读最新 Save。

### `POST /api/npc/interact`

Step 6.6-A 的 NPC Interaction API 只接受：

```json
{
  "npc_id": "npc_astrid",
  "player_id": "player_001",
  "utterance": "Bjorn 是做什么的？"
}
```

API Adapter 依次调用冻结的 `run_npc_interaction()` 与 `prepare_npc_mutation_plan()`，返回：

```text
interaction_available
unavailable_reason
npc_response
interaction_event
mutation_plan
```

`mutation_plan` 中的 Memory Preview、Relationship Preview 与 Commit Availability 均来自 Frozen Mutation Bridge。Interaction API 永远保持 Preview-only，不自动写 Memory、Relationship 或 World State。

Player 与 NPC 不在同一 Location 时，HTTP 仍返回 200，但 `interaction_available=false`，Response、Event 和 Mutation Plan 均为 `null`。该业务结果在 Provider 创建或调用前完成，因此 LLM Call Count 为 0。

### `POST /api/npc/memory/commit`

Request 只接受 Frozen Interaction Event：

```json
{
  "interaction_event": {
    "...": "完整且符合 npc_interaction_event.schema.json 的事件"
  }
}
```

服务器重新校验 Event，并重新调用 Frozen Mutation Bridge 生成当前 Plan。只有 `memory.commit_available=true` 时，才通过 Frozen Memory Commit Path 写入独立 Memory Store。Client 不能提交 `memory_id`、Memory Record 或 Store 内容。

### `POST /api/npc/relationship/commit`

Request 同样只接受 Frozen Interaction Event。服务器基于最新 Persistent Relationship 重新运行 Frozen Relationship Evaluator；只有 `relationship.commit_available=true` 才能提交。Client 不能提交 `trust`、`familiarity`、`attitude` 或 Relationship Record。

两个 Commit Endpoint 都不会调用 LLM，并继续使用原有 `source_event_id` / `applied_event_ids` Idempotency。重复 HTTP Request 返回 Business Rejection，不会产生第二次 Mutation。

### NPC Preview vs Commit

```text
POST /api/npc/interact
→ Unified NPC Runtime（最多一次 LLM）
→ Mutation Plan Preview（Read-only）

POST /api/npc/memory/commit
或 POST /api/npc/relationship/commit
→ Validate Interaction Event
→ Rebuild Frozen Mutation Plan
→ Commit one selected Domain（0 LLM）
```

Memory 与 Relationship 是独立 Persistent Domains。每个 JSON Store 各自 Atomic，但 Step 6.6-A 不声明跨两个 Store 的全局事务。

## 12. 错误与安全边界

- Save 不存在：HTTP 404。
- Player 未创建：HTTP 400。
- 空 Action Input：HTTP 400。
- LLM Provider 请求失败：HTTP 502，不返回密钥或 Prompt。
- Structured Output / Grounding 无效：HTTP 422。
- Mutation Validation 失败：HTTP 409，Save 不变。
- NPC 不存在或 Player ID 不匹配：HTTP 404 Business Rejection。
- NPC 不同地点：HTTP 200，并通过 `interaction_available=false` 表达正常业务不可用。
- NPC Duplicate Event / No Mutation Available：HTTP 409 Business Rejection。
- Client 提交的 Interaction Event 无效：HTTP 422 Business Rejection。
- NPC Provider Failure：HTTP 502 System Error。
- NPC Store Corruption / Mutation System Failure：HTTP 500 System Error。
- 未预期服务器错误：只返回通用信息，不暴露环境变量。

CORS 仅允许开发环境的 `http://localhost:3000` 和 `http://127.0.0.1:3000`，不允许任意 Origin。

## 13. 运行与 Smoke Test

先在项目根目录安装已列出的依赖，并确保 `.env` 已配置 Doubao：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn api.app:app --reload --env-file .env
```

`--env-file .env` 让 Uvicorn Worker 在创建 Provider 前加载项目根目录的 Doubao 配置。`.env` 仍受 `.gitignore` 保护，不会通过 API 或 Git 暴露。Swagger UI 使用 UTF-8 正常显示中文；Windows PowerShell 5.1 的控制台乱码属于终端编码显示问题，不代表 Backend Response 编码错误。

访问：

- Health：`http://127.0.0.1:8000/health`
- World Summary：`http://127.0.0.1:8000/api/world`
- FastAPI Docs：`http://127.0.0.1:8000/docs`

第一次真实 Preview 可在 `/docs` 中调用 `POST /api/action/preview`，Request Body：

```json
{
  "input": "我去Skeld。"
}
```

Action Preview 的目标 Location 应根据当前 Save 选择；先检查三层 Preview，本阶段不需要立即调用 Commit。

第一条 NPC API 人工测试可在 Eirik 与 Astrid 同处 `skeld_village` 时运行：

```powershell
$body = @{
  npc_id = "npc_astrid"
  player_id = "player_001"
  utterance = "Bjorn 是做什么的？"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/npc/interact" `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) |
  ConvertTo-Json -Depth 20
```

## 14. 当前不负责

Step 6.6-A 只实现 NPC API Adapter。它没有修改 Web UI，也没有实现自动 Memory/Relationship Commit、跨 Store Transaction、Dynamic NPC、NPC Autonomous Action、Quest、Dynamic Event、Multimodal、3D 或 Database。

## Step 6.6-A — NPC API Integration v0.1 Frozen Baseline

- **Version**: NPC API Integration v0.1
- **Status**: FROZEN BASELINE
- **Freeze Date**: 2026-08-31
- **NPC API Targeted Tests**: 18/18 PASS
- **Full Offline Regression**: 199/199 PASS
- **Python Syntax**: PASS
- **JSON Validation**: 40/40 PASS
- **JSON Schema Validation**: 18/18 PASS
- **Protected Hash Check**: 16/16 PASS
- **Secret Scan**: PASS
- **Freeze Regression LLM Calls**: 0

人工验收已确认：

- Knowledge Question：FastAPI → Doubao → Unified NPC Runtime 正常返回 Grounded Knowledge Response。
- Memory Candidate：Interaction Event 与 Memory Preview 正确生成，Interaction API 本身不自动 Commit。
- Different Location：Same-location Guard 返回 `interaction_available=false`，Response、Event 与 Mutation Plan 均为空，LLM Call Count 为 0。
- FastAPI 通过 Uvicorn `--env-file .env` 加载与 CLI 相同的 Provider 配置。
- Swagger UI 的 UTF-8 中文 Response 正常。

冻结能力包括：

- `POST /api/npc/interact` 对 Unified NPC Interaction Runtime 与 Mutation Bridge 的薄适配。
- Structured NPC Response、Interaction Event 与 Mutation Plan Preview。
- Precondition Failure 作为 HTTP 200 Business Result 返回。
- 独立 Memory Commit 与 Relationship Commit Endpoint。
- Commit 时重新进行 Event Validation 与 Frozen Mutation Plan 构建。
- Memory / Relationship Idempotency。
- Commit API 0 LLM、Preview 不写 Persistent State。
- Business Rejection 与 System Error 的明确区分。
- Temporary Store API Test Isolation。
- Existing World API、Action API 与 Frontend Contract 兼容。

API Adapter 只负责协议转换与错误映射，不重新实现 NPC Context、Memory Retrieval、Relationship、Response、Interaction Event、Mutation 或 Idempotency 规则。冻结后只有可复现的真实 Failure 才允许修改，并必须遵循：

```text
Failure Reproduction
→ Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```

Step 6.6-B 尚未开始。
