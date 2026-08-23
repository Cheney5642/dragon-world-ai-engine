# Natural Language Action Interpreter v0.1

## 1. 什么是 Action Interpreter

Action Interpreter 是玩家自然语言与世界运行系统之间的“意图翻译层”。它把“我想做什么”整理成符合 JSON Schema 的 Action Intent，供后续系统检查和处理。

它只做理解和 Preview，不执行动作，也不生成剧情结果。

## 2. Interpreter 与 Executor 的区别

- **Interpreter** 识别玩家想尝试的动作、目标、目的、方法、说话内容以及声明的事实。
- **Executor** 将来才会根据 Persistent World State、World Rules、角色能力、物品、位置和实际事件判断动作如何发生。

例如“我要偷 Bjorn 的锤子”可以被解释为 `steal`，但 Interpreter 不能说玩家已经拿到锤子。成功、失败或其他结果都属于后续执行阶段。

## 3. 为什么不能直接从玩家输入生成结果

玩家输入表达的是自由意图，不是对世界状态的直接写权限。如果模型边理解边生成结果，就可能凭一句话给玩家增加物品、移动位置、改写 NPC 状态，甚至让尚未验证的行动自动成功。

因此 v0.1 遵循：**Free Intent, Grounded Consequence.** 玩家可以尝试任何事，但后果必须以后由 World State、World Rules 和实际事件共同决定。

## 4. 什么是 Action Intent

Action Intent 是结构化的“尝试描述”，主要包含：

- 原始输入 `raw_input`
- 粗粒度路由 `action_kind`
- 一个或多个 `steps`
- 明确说出的话 `speech`
- 试图声明的世界事实 `claimed_facts`
- 是否需要世界校验 `requires_world_check`
- 输入本身是否需要澄清 `needs_clarification`

每个 step 的 `verb` 使用自由字符串，因为开放世界无法预先枚举玩家所有可能动作。`target` 能匹配已知实体时使用真实 ID；不能确认时保留普通名称并使用 `id: null`，不得伪造 Entity ID。

## 5. 什么是 Compound Action

Compound Action 表示一次输入里包含多个有顺序或条件关系的步骤。例如：

> 我先去找 Astrid，如果她有空，就邀请她晚上去海边。

Interpreter 可以保留“find Astrid”和“invite Astrid”两个步骤，也可以保留“如果她有空”这个条件，但不能提前判断 Astrid 是否有空，更不能替她决定是否接受邀请。

## 6. Speech 与 World Fact Mutation 的区别

“我是奥丁！”作为角色说出的话，是 Speech 或 Self Expression。它不会自动把 `player.species` 改成神，也不会证明这句话为真。

“我现在有一把 AK47”是在 Runtime 中试图声明 World Fact。Interpreter 会把它记入 `claimed_facts` 并要求世界检查，但不会把 AK47 加入 Inventory。声明能否成立由下一阶段判断。

## 7. 为什么 Step 5.1 必须保持 Read Only

这一阶段正在验证“理解玩家意图”的稳定性。解释结果仍可能存在歧义或需要校验，因此不能直接污染 Persistent World State。

`scripts/interpret_action.py` 只读取 `data/saves/current_world.json` 来构建最小上下文，输出 Action Interpretation Preview，不包含 Save 写入、Entity Mutation 或 Commit 流程。测试模式同样只读。

## 8. 下一阶段 World Validation 负责什么

World Validation 将根据玩家状态、Inventory、当前位置、NPC 状态、World Rules 和现实可行性检查 Action Intent。它会区分“玩家可以尝试”与“世界允许产生什么后果”，但仍不应把玩家的自由表达视为错误。

整体链路为：

```text
Natural Language
→ Action Interpreter
→ Structured Intent
→ Future World Validation
→ Future Agent Response
→ Future State Mutation
```

Step 5.1 只实现前三项中的 Preview，不执行后续环节。

## Baseline Freeze

- Version: Action Interpreter v0.1
- Status: FROZEN BASELINE
- Evaluation: 8/8 PASS
- Provider: doubao
- Model: doubao-seed-2-0-lite-260215
- Freeze Date: 2026-08-24

此版本作为 Step 5.1 的稳定基线。后续只有出现新的真实 Failure 时，才允许修改 Prompt、Evaluation 或 Schema。

如果需要修改，必须遵循以下回归纪律：

- 新增与真实 Failure 对应的 Regression Case。
- 先针对单个 Case 修复并验证。
- 单 Case 通过后再运行完整 Regression。
- 不允许为了单个 Case 破坏已经通过的旧 Case。
