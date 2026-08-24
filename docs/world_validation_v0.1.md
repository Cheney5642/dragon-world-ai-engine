# World Validation v0.1

## 1. 什么是 World Validation

World Validation 是 Structured Action Intent 与 Persistent World State 之间的只读校验层。它回答的是：“按照当前已知事实和规则，这个行动是否具备进入后续处理的条件？”

它不执行行动、不计算随机成功率、不生成剧情，也不修改存档。

## 2. Interpreter 与 Validator 的区别

- **Action Interpreter** 理解玩家想尝试做什么，并输出 Structured Action Intent。
- **World Validator** 使用当前 Player、相关 NPC、相关 Location、Inventory 和 World Rules，检查这个 Intent 的事实基础与前置条件。

Interpreter 保留自由意图；Validator 负责把后续可能产生的后果 Ground 到世界事实中。

## 3. Supported / Contradicted / Unknown

- **SUPPORTED**：提供的 World State 或 World Rules 明确支持该事实。
- **CONTRADICTED**：提供的状态或规则明确与该事实冲突。
- **UNKNOWN**：当前上下文没有足够证据判断。

三值判断避免模型把“没有数据”误当成“事实为假”，也避免凭常识补写世界。

## 4. 为什么 Unknown 不等于 False

如果存档只说明 Bjorn 是位于 Skeld 的铁匠，却没有记录他的物品，那么“Bjorn 拥有一把锤子”只能是 UNKNOWN。铁匠可能拥有锤子，但职业常识不是当前 Persistent World State 中的物品事实。

因此 Validator 既不能假设锤子存在，也不能断言锤子不存在，而应要求后续 Object Resolution 或更多状态证据。

## 5. allowed 不等于 succeeded

`allowed` 只表示当前没有明确阻碍，而且已有足够条件把 Intent 交给未来执行层。它不表示玩家已经移动、找到 NPC、取得物品或完成目标。

例如 Skeld 与 Stormcliff 存在连接时，“我去 Stormcliff”可以是 `allowed`，但 Player 的 `current_location` 仍不会在 Step 5.2 中改变。

## 6. Validator 为什么不能替 NPC 做决定

NPC 是否同意邀请、是否相信玩家、是否交出物品，属于 NPC 自主决策。Validator 只能确认 NPC 是否存在、位置是否相容，以及结果是否依赖 NPC 选择，并设置 `requires_npc_decision=true`。

## 7. Deterministic Checks 与 LLM Validation 的分工

代码优先验证明确结构化事实：

- Entity ID 是否存在
- Player 与 NPC 当前 Location
- Inventory 是否包含声明的物品
- Location 是否存在直接连接
- World Rules 是否明确禁止某项能力或技术

这些确定性结果作为权威证据传给 LLM，并在模型返回后再次合并到最终 Preview、进行本地一致性检查。这样即使模型遗漏或改写某条确定性证据，代码仍会保留权威的 fact/status、缺失条件与阻断级别。LLM 负责开放语义、多步骤意图和多个条件之间的综合说明，但不能覆盖或反转确定性证据。

v0.1 不引入数据库或复杂 Rule Engine。

## 8. 为什么 Step 5.2 仍然必须 Read Only

Validation Preview 仍是执行前判断。行动尚未经历 Action Execution、NPC Decision 或事件结算，因此没有任何 State Mutation 权限。

`scripts/validate_action.py` 只读取 `data/saves/current_world.json`，不会修改 Player、NPC、Inventory、Relationship、Memory、Global State 或任何其他世界数据。Evaluation 模式同样只读。

整体架构：

```text
Natural Language
→ Action Interpreter
→ Structured Intent
→ World Validator
→ Validation Preview
→ Future Action Execution / NPC Decision
```

Step 5.2 到 Validation Preview 为止，最后一项尚未实现。

## Baseline Freeze

- Version: World Validator v0.1
- Status: FROZEN BASELINE
- Evaluation: 8/8 PASS
- Provider: doubao
- Model: doubao-seed-2-0-lite-260215
- Freeze Date: 2026-08-24

此版本作为 Step 5.2 World Validation 的稳定基线。未来只有出现新的、可复现的真实 Failure 时，才允许修改 World Validator 的 Prompt、Schema、Deterministic Validation、Evaluation 或业务逻辑。

任何解冻修改都必须遵循以下回归纪律：

1. 为真实 Failure 新增对应的 Regression Case。
2. 先运行并通过该 Case 的 Targeted Regression。
3. 再运行完整 Full Regression，确认所有既有 Baseline Case 继续通过。

不允许为了修复单个 Case 破坏已经冻结的旧 Case。
