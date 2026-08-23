# Player Commit System v0.1

## 什么是 Commit

Commit 是把已经通过校验、Grounding 和用户确认的 Player Preview 正式写入 Persistent World State。Player Commit 不是 Git commit，也不是重新生成世界；它是一次受权限限制的持久状态变更。

完整流程：

```text
Natural Language
→ LLM
→ Schema
→ Grounding
→ Preview
→ Confirmation
→ Commit
→ data/saves/current_world.json
```

## Preview 与 Commit

Preview 是 AI Interpreter 对玩家描述的结构化、Grounded 解释。它可以被查看、取消或要求澄清，但还不是持续存在的世界事实。

Commit 才会修改当前 Save。AI 输出不能直接无条件修改 World State，因为模型可能误解输入、产生不完整结果，或者需要玩家确认如何处理核心身份冲突。

Player Commit 必须同时满足四个条件：

1. Player Creation Result 通过 Schema Validation；
2. `needs_clarification = false`；
3. `data/saves/current_world.json` 存在且是合法 Save；
4. 用户明确输入 `y` 或 `yes` 确认。

## 为什么 clarification 会阻止 Commit

`needs_clarification = true` 表示角色核心身份尚不能在当前 World Rules 中被可靠 Ground。此时写入 Save 会让系统擅自选择一种解释，把不确定内容变成永久事实。因此系统仍显示 Preview，但不会询问确认，也不会修改 Save。

## Player State Mutation 权限

Character Creation v0.1 只有修改 `player` 的权限。Commit 会保留 Save 中既有的 `player.id`、inventory、relationships 和 memories，只更新 Player Creation Schema 管理的身份字段。

即使玩家背景提到 Bjorn、Astrid 或其他世界实体，也不能由此修改 `npcs`、`world`、`locations`、`global_state` 或 World Rules。个人背景属于 Player State；其他实体的变化需要未来独立的规则和事件系统。

## 为什么不能覆盖已有 Player

当 `current_world.json` 中的 `player.name` 已经不是 `null`，该世界已经拥有 Player。自动覆盖会删除已建立的身份和后续状态，且 v0.1 尚未定义角色切换。

如需创建新角色，应先明确重置世界：

```text
python scripts/init_save.py --reset
```

## 与 Persistent World State 的关系

`world_seed.json` 始终是 New Game 模板。`current_world.json` 是真正运行中的 Persistent World State。Player Commit 采用同目录临时文件写入、JSON 复验和原子替换，以降低写入中断导致 Save 损坏的风险。

Evaluation 模式 `--test` 和 `--test-case` 永远只读，不进入确认或 Commit 流程。
