# Dragon World Engineering Collaboration Guide

本文件定义 Codex 在 Dragon World 仓库中的项目级长期协作规范。目标是保持开发范围、运行进程、验证策略、冻结基线和世界事实边界清晰，同时让每一步工程决策对用户可理解。

## 1. Development Workflow and Scope

Dragon World 采用以下协作流程：

```text
Explain
→ Implement
→ Targeted Validate
→ Review
→ Freeze
```

- 每次只完成用户当前指定 Step，不自动开始下一 Step，不擅自扩大 Scope。
- 避免一次性大范围重构；完成当前工作后先汇报并等待用户确认。
- 用户要求 Audit、Diagnosis 或 Design 时，只读分析，不写代码。
- 用户要求“完成后停止”时必须停止，不提前实现 Roadmap 或顺手重构周边模块。

## 2. Runtime Process Ownership

**The user owns all long-running development servers.**

用户负责长期运行的 Backend 和 Frontend。Codex 负责代码修改、定向验证、验证所需的临时进程，以及清理自己启动的进程。不得留下归属不明的 Server。

### Backend

默认地址：`127.0.0.1:8000`

用户正式启动方式：

```powershell
cd "C:\Users\Chene\Desktop\Dragon World"
.\.venv\Scripts\Activate.ps1
python -m uvicorn api.app:app --env-file .env --host 127.0.0.1 --port 8000
```

Codex 因验证需要临时启动 Backend 时：

1. 先执行 `netstat -ano | findstr :8000`。
2. 如果已有健康 Backend，优先复用，不启动第二个 Uvicorn。
3. 如果由 Codex 临时启动，验证结束后必须终止自己启动的准确进程。
4. 不得自动改用 `8001`、`8002` 等端口绕过冲突，除非用户明确批准。

### Frontend

默认地址：`localhost:3000`

用户正式启动方式：

```powershell
cd "C:\Users\Chene\Desktop\Dragon World\frontend"
npm run dev
```

Codex 启动前必须检查端口 `3000`。已有 Dev Server 时不得重复启动；临时启动的 Frontend 必须在验证完成后清理。

### Process Safety

- 禁止使用 `taskkill /IM python.exe` 或其它会终止所有 Python 进程的宽泛命令。
- 结束进程前必须确认具体 PID 且确认该 PID 属于 Dragon World。
- 只终止准确识别的目标进程，不影响其它 Python、其它项目或系统进程。

## 3. Lean Validation

Dragon World 采用 Lean Validation（精简验证）：

- 开发中优先运行与当前修改直接相关的 Targeted Validation（定向验证）。
- 阶段完成时只验证必要关键路径；Freeze 前根据风险决定回归范围。
- 默认不在每个小改动后运行全部 Test Suite、Web E2E 或真实 LLM Cases。
- 仅当 Frozen Core、Persistent State Contract、核心 World Rules 被修改，用户明确要求，或变更确属高风险时，才扩大回归范围。
- 不随意新增 Test Script、Debug Script、Fixture、Harness 或 Temporary CLI；现有验证入口足够时必须复用。
- 临时测试数据必须清理，不得在 PostgreSQL 留下无意义 Test Data。

## 4. Freeze Baseline

Freeze 不等于“代码看起来完成了”。声明 `FROZEN` 前至少确认：

- 当前 Step 验收 PASS；
- `git diff --check` PASS；
- 相关验证 PASS；
- Git Commit 创建成功；
- Push 成功；
- `main` 与 `origin/main` 同步；
- Working Tree 干净。

不得只完成测试却声称 Git Freeze 已完成。已经 Frozen 的模块默认不得修改；如任务确实需要修改 Frozen Core，必须先停止，向用户说明原因与风险，并等待明确批准。

## 5. Git and Secret Safety

- Commit 只包含当前 Step 的真实相关文件，优先显式执行 `git add <file>`。
- 避免 `git add .` 和 `git add -A`，尤其是在多个 Step 的改动同时存在时。
- 不提交 `.env`、API Key、Secret、Credential、Authorization Header、临时 Runtime Data、无关 Legacy JSON 或个人环境文件。
- 禁止打印、记录或提交 `ARK_API_KEY`、`DATABASE_URL` 中的密码及其它 Credential。
- 诊断 Secret 时只汇报 `present` / `missing` 或经过脱敏的安全错误信息。
- 仅在用户明确要求时执行 Commit、Push 或其它 Git 状态变更。

## 6. Database and Infrastructure Boundary

PostgreSQL 是正式 Runtime Source of Truth（运行时唯一事实来源）。

- 禁止恢复 Legacy JSON Runtime Write、JSON Fallback 或 PostgreSQL + JSON Dual Write。
- 旧 Runtime JSON 仅作为迁移或备份产物。
- Database Infrastructure 当前处于 Infrastructure Freeze。
- 不因局部需求新增 Repository Framework、UnitOfWork Framework、Generic Persistence Framework、Manager Layer、Factory Layer、Storage Factory 或 Data Sync Service。
- 如果真实 Player-facing Feature 确实需要最小 Schema Change，必须先 Audit，说明必要性和风险，取得用户批准后再实现。

## 7. Architecture and Product Direction

顶层架构保持简单：

1. Interaction Layer
2. World Orchestrator
3. World Rules
4. NPC Runtime
5. Dragon Runtime
6. Persistent World / PostgreSQL
7. Presentation Layer

不得擅自扩展为大型 Multi-Agent Framework。

核心产品原则：

> Player can say or attempt anything; the world decides what becomes true.
>
> 玩家可以说任何话、尝试任何事；世界决定什么成为事实、什么能够成功。

- `Player Claim != Objective World Truth`
- `Freedom of Action != Guaranteed Success`
- `Dragon Gameplay is Systemic; Everything Else is Open-ended.`
- 驯龙核心玩法系统化，其它玩法优先通过 AI 进行开放式语义理解。
- 当前基础设施已足够支撑 MVP；后续优先 Player-facing Experience，而不是继续扩建基础设施。

当前主要体验方向包括 Open Identity、Free World Action、Dragon Encounter、Dragon Bond / Taming、World Tick、Multimodal Image、Dragon Riding 和 First-person Riding Video。不得仅因“工程上可以”就提前实现非必要系统。

## 8. World Truth and LLM Boundary

LLM 负责：

- 理解玩家自由输入；
- 生成自然语言表达。

World Engine / Runtime 负责决定：

- 什么是真的；
- 什么状态可以变化；
- 什么行动成功；
- 什么事件可以 Commit。

LLM 不得直接修改 World Truth。必须保持：

- Grounded Evidence
- Anti-Farming
- Idempotency
- Read / Write Separation
- `Trust != Truth`
- `Warm != Romance`
- `Familiarity != Fake History`
- `Player Claim != World Fact`

## 9. Learning-oriented Reporting

用户通过 Dragon World 学习 AI Product、Engineering、Database、State Management 和 Agent / Runtime Architecture。阶段汇报应说明：

- 做了什么；
- 为什么这样做；
- 涉及哪些关键概念；
- 如何验证；
- 是否影响 Frozen Core。

不要只回复“Done”。首次出现的重要英文工程术语应尽量附带简短中文解释。

## 10. Responsibility Summary

User owns:

- long-running Backend；
- long-running Frontend。

Codex owns:

- code modification；
- targeted validation；
- temporary processes required for validation；
- cleanup of processes it starts；
- Git operations when explicitly requested。

Codex must never leave ambiguous server ownership.
