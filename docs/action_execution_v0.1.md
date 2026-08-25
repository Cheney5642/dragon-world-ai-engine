# Action Execution System v0.1

## 1. Interpreter、Validator 与 Executor

- **Action Interpreter** 将玩家自然语言转换为 Structured Action Intent，回答“玩家想尝试什么”。
- **World Validator** 使用 Persistent World State 与 World Rules 检查前置事实，回答“这个 Intent 是否具备继续处理的条件”。
- **Action Executor** 只接收 `overall_status=allowed` 的结果，在有限白名单内生成 Execution Plan 和候选 State Mutation。

三层职责分离，防止模型把玩家表达、行动意图或 Validation Preview 直接当成已经发生的世界事实。

## 2. State Mutation

State Mutation 是对 Persistent World State 的实际字段修改。Step 5.3 是首次允许 Mutation 的阶段，但 v0.1 只开放：

```text
player.current_location
```

Player ID、species、occupation、inventory、relationships、memories、goals，以及 NPC、Location、Global State 和 World Rules 都不在 Mutation 白名单内。

## 3. Mutation Proposal

Execution Plan 中的 `proposed_mutations` 只是候选变更。例如合法移动可以提出：

```text
player.current_location: skeld_village → stormcliff
```

Proposal 不会直接写入 Save。它必须先通过本地 Mutation Validation，再获得用户明确确认。

## 4. Mutation Validation

Python 代码在 Commit 前确定性检查：

1. World Validation 必须为 `allowed`。
2. 行动不能依赖 NPC Decision。
3. 不能存在 unresolved requirement。
4. Mutation 的 entity 与 entity_id 必须真实存在。
5. field 必须在 Mutation 白名单。
6. old_value 必须等于当前 Save 的真实值。
7. new_value 必须是当前世界中的合法 Location ID。

确定性校验不会让 LLM 直接选择任意 JSON 路径，也不会让模型扩大写权限。

## 5. Commit

只有存在合法 Mutation 时才询问：

```text
Commit this action to the current Dragon World save? [y/N]:
```

只有 `y` 或 `yes` 会触发 Commit。写入继续使用：

```text
read
→ modify in memory
→ write temporary file
→ validate JSON
→ atomic os.replace
```

Commit 只写入 `data/saves/current_world.json`，永远不修改 `data/world_seed.json`。

## 6. allowed 不等于 succeeded

`allowed` 只说明 World Validator 允许 Intent 进入 Executor。只有 Executor 生成白名单内的 Mutation、Mutation Validation 通过、用户确认并完成 Commit 后，对应字段才成为新的 Persistent World Fact。

没有 Mutation 的行动也不会被叙述为“成功”。例如找到同地点的 Astrid 只表示具备进入未来 NPC Interaction 的条件，不表示 Astrid 已经回应玩家。

## 7. v0.1 支持范围

- 合法直接连接的 Movement
- 与同地点已知 NPC 建立 Encounter 条件
- Pure Speech / Self Expression

当前不执行偷窃、战斗、Inventory transfer、交易、Relationship change、NPC consent、驯龙、杀戮或 Dynamic Events。这些行动需要未来独立 Resolver 或 Agent。

## 8. Read / Write Boundary

普通交互模式只有在合法 Movement Mutation 获得用户明确确认后才能写入 Save。

`--test` 和 `--test-case` 使用离线确定性 fixture，只在内存中验证 Proposal 与 Mutation，不调用 LLM，也不修改 Persistent Save。

完整流程：

```text
Natural Language
→ Action Interpreter
→ Structured Intent
→ World Validator
→ Validation Result
→ Action Executor
→ Proposed State Mutations
→ Mutation Validation
→ User Confirmation
→ Commit
→ current_world.json
```

## Baseline Freeze

- Version: Action Execution v0.1
- Status: FROZEN BASELINE
- Evaluation: 8/8 PASS
- Real Runtime Validation: PASS
- Freeze Date: 2026-08-25

此版本作为 Step 5.3 Action Execution System 的稳定基线。真实 Runtime 已验证 Eirik 能够从 `skeld_village` 移动到 `stormcliff`，Persistent Save 写入正常；Evaluation 模式保持 Read Only，且 `world_seed.json` 未被修改。

后续只有发现新的真实 Failure 时才允许解冻修改。任何修改必须遵循：

```text
Failure Reproduction
→ New Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```

不得为了修复单个 Failure 而破坏已经通过的旧 Case。
