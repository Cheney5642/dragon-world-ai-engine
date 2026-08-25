# Action Execution v0.1 Baseline

## Baseline Status

- Version: Action Execution v0.1
- Status: FROZEN BASELINE
- Evaluation: 8/8 PASS
- Real Runtime Validation: PASS
- Freeze Date: 2026-08-25

## 模块职责

Action Executor 只接收已经通过 World Validation 的 Action Intent，生成可审查的 Execution Plan 和候选 Mutation。它不重新解释玩家输入，不绕过 Validator，也不用叙事文本代替确定性状态变更。

只有候选 Mutation 通过本地校验并获得用户明确确认后，才能原子写入 `data/saves/current_world.json`。

## 支持的 Execution Type

- `movement`：将玩家移动到当前地点直接连接的有效 Location。
- `encounter`：已知 NPC 与玩家处于同一 Location 时，建立交互前置条件；不修改状态，不生成 NPC 回应。
- `speech`：保留说话或自我表达的执行路由；不修改 Player Identity 或其他 World State。
- `unsupported`：对当前 Executor 尚不支持的行动明确返回能力边界，不伪造执行结果。

## 当前 Mutation 白名单

v0.1 唯一允许的 Persistent State Mutation 是：

```text
entity_type: player
field: current_location
```

即只允许在合法 Movement 中更新 `player.current_location`。NPC、Location、Inventory、Relationship、Memory、Global State 和 World Rules 均不在当前写权限内。

## Safety Boundary

- 只有 `allowed` 的 World Validation Result 可以进入 Executor。
- `blocked`、`conditional` 和 `needs_clarification` 不得进入 State Mutation。
- Execution Plan 必须通过 JSON Schema Validation。
- Entity ID、字段、旧值、新 Location 和地点直接连接关系必须使用最新 Save 做确定性校验。
- 每次执行最多提交一个白名单 Mutation，且只有 `movement` 可以包含 Mutation。
- 必须在用户输入 `y` 或 `yes` 明确确认后才能 Commit。
- Commit 通过临时文件、JSON 校验和原子 `replace` 更新 Save。
- `data/world_seed.json` 被显式禁止成为 Commit 目标。
- `--test` 与 `--test-case` 为离线 Read Only Evaluation，不调用 LLM，不修改 Save。

## 8 Case 覆盖范围

1. 合法 Movement 生成 `skeld_village → stormcliff` 的 `player.current_location` Proposal。
2. 在内存中应用合法 Plan 时，只更新 Player Location。
3. 用户取消时不 Commit，Save 不变。
4. `blocked` Action 不能进入 Executor。
5. `conditional` Action 不能进入 Executor。
6. 在同一 Location 寻找 Astrid 生成无 Mutation 的 Encounter。
7. Pure Speech 不生成 Mutation，不改写 Player Identity。
8. Evaluation 保持 Read Only，`world_seed.json` 不变。

Evaluation 结果：**8/8 PASS**。

## 当前不支持的能力

- 偷窃、战斗、杀戮与其他需要独立 Resolver 的复杂行动
- Inventory transfer 与交易
- Relationship 和 Memory Mutation
- NPC consent、NPC Decision 与 NPC Agent
- 驯龙等需要后续世界机制判定的能力
- Dynamic Events 与 Event Engine
- 最终剧情结果或叙事生成
- Frontend 与 Database

## 解冻规则

只有出现新的真实 Failure 时才允许修改此 Baseline，并必须按照以下顺序进行：

```text
Failure Reproduction
→ New Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```

任何单 Case 修复都不得破坏已通过的 Regression Case。
