# Action Interpreter v0.1 Baseline

## 冻结信息

- Version: Action Interpreter v0.1
- Status: FROZEN BASELINE
- Evaluation: 8/8 PASS
- Provider: doubao
- Model: doubao-seed-2-0-lite-260215
- Freeze Date: 2026-08-24

## 模块职责

Action Interpreter 负责把玩家的自然语言输入解释成结构化 Action Intent，并输出只读 Preview。它识别玩家想尝试的动作、目标、目的、方法、Speech 和 Runtime World Fact Claim，但不决定行动结果。

## 当前架构

```text
Player Natural Language
→ Action Interpreter Prompt + Minimal World Context
→ LLM Provider Layer (doubao)
→ Structured Output
→ Local JSON Schema Validation
→ Entity ID Validation
→ Action Interpretation Preview
```

最小 World Context 只包含解释行动所需的 Player 字段、World Rules、有效 Location Directory 和已知 NPC Directory。Evaluation 与普通 Preview 均保持只读。

## Baseline Case 覆盖范围

1. 寻找已知 NPC，并将 Astrid 解析为 `npc_astrid`。
2. 前往未注册的酒馆，不为未知地点伪造 Location ID。
3. 解析寻找 Bjorn 后偷取其锤子的 Compound Action，不生成偷窃结果。
4. 将“我是奥丁！”识别为 Speech 或 Self Expression，而不是身份改写或 World Fact Claim。
5. 将“我现在有一把 AK47”识别为 Runtime World Fact Claim，并要求 World Check。
6. 解析飞往 Stormcliff 的自由行动意图，不提前判断飞行是否可行。
7. 保留“寻找 Astrid，再在条件满足时邀请她”的多步骤与条件关系，不替 NPC 决策。
8. 对“做那个”这类缺少指代信息的输入设置 `needs_clarification=true`。

## Evaluation 结果

当前 Baseline 为 **8/8 PASS**，同时满足：

- Structured Output 通过 JSON Schema Validation。
- 已知实体使用真实 ID，未知实体不伪造 ID。
- Evaluation 为 Read Only。
- Evaluation 未修改 `data/world_seed.json` 或 `data/saves/current_world.json`。

## 已知边界

- 8 个 Case 是当前稳定基线，不代表已经覆盖所有可能的自然语言表达。
- `verb` 保持自由字符串；确定性 Evaluation 只能用轻量语义匹配处理已知等价表达，不能充当完整自然语言 Judge。
- 未出现在最小 World Context 中的实体只能保留名称并使用 `id: null`。
- `claimed_facts` 只记录待校验的 Runtime 主张，不证明主张成立。
- Interpreter 的结构化输出仍需后续 World Validation 才能参与实际世界运行。

## 当前明确不负责

Action Interpreter v0.1 不负责：

- World Validation
- Action Execution
- NPC Decision
- State Mutation

## 解冻与回归纪律

只有出现新的、可复现的真实 Failure 时才解冻修改。每次修改必须先新增对应 Regression Case，完成单 Case 修复，再运行完整 Regression，并确保既有 Baseline Case 不发生退化。
