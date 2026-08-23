# Player Creation System v0.1

## Player Creation System 是什么

Player Creation System（玩家创建系统）负责把玩家对身份的自然语言描述转换为结构化 Player 数据。它提取姓名、物种、职业、背景、特征、初始地点和目标，并在结果写入 World State 前进行 Grounding：保留能够成立的角色事实，同时把尚未被世界支持或与规则冲突的部分留在事实层之外。

核心产品原则是：**Never punish imagination; ground consequences.** 系统不审核玩家是否“应该这样想”，只校验哪些内容能够成为持续存在的世界事实。

## 为什么玩家可以自由描述身份

开放世界应允许玩家用自然语言表达想扮演的角色，而不必先理解固定表单或职业列表。玩家可以自称奥丁、想开法拉利，也可以提出当前看似不可能的行动。姓名可以暂缺，职业保持开放字符串，背景、特征和目标从玩家自己的描述中提取。v0.1 仅将准备写入 Player State 的物种和初始地点限制在当前 Demo 已支持的范围内。

## Expression、Intent 与 World Fact

- **Expression（表达）**：玩家说出、想象或相信的内容，例如“我是奥丁”。表达本身不是错误，也不应自动改变世界。
- **Intent（意图）**：玩家真正想尝试做的事，例如“我要飞去 Stormcliff”或“我要找 Astrid”。意图可以自由提出，能否成功由角色条件、World State、World Rules 和实际事件决定。
- **World Fact（世界事实）**：准备持久写入 World State 的数据，例如 `player.species`、背包物品或飞行能力。只有这一层必须经过规则校验。

Player Creation 属于创建 World Fact，因此需要 Grounding；但 Grounding 的目标不是拒绝想象，而是从自由描述中提取能够成立的角色，并避免未经支持的说法直接变成事实。

## 为什么“自由”不等于玩家说什么都成为世界事实

玩家的描述是创建角色的输入，不是对世界事实的直接修改。如果玩家说“我是 Skeld 的铁匠，但我天生会飞”，系统应创建可成立的 human blacksmith，并保留其飞行主张，但不能写入 `player.can_fly = true`。如果玩家自称奥丁，系统可以把这视为角色的自我认同、信念、传闻或潜在线索，却不能仅凭一句自述写入 `player.species = god`。

因此，系统应优先保留可以成立的身份，指出不能写入 World State 的部分，并尽量生成一个 Grounded Player。只有角色最核心的身份严重依赖当前规则之外的设定，且无法合理解释时，才需要玩家澄清。

## 输出中的校验信息

- **assumptions**：记录 AI 为补足缺失信息所做的轻量假设，例如未说明地点时默认从 `skeld_village` 开始。
- **conflicts**：记录与当前 World State 或 World Rules 明确冲突、无法直接写入的数据，并说明适用的规则。
- **unsupported_claims**：保留玩家可以表达、但当前世界没有证据支持为真实事实的主张。它不是对玩家表达的否定。
- **grounded_interpretation**：用一句简短自然语言说明系统最终如何理解角色，包括哪些部分成立、哪些部分仍只是角色的主张。
- **needs_clarification**：表示角色的核心身份是否无法在当前世界中合理 Grounding。局部能力或说法不成立时通常仍为 `false`。

`unsupported_claims` 与 `conflicts` 可以描述同一内容的不同侧面：前者保存“玩家声称自己能自然飞行”，后者说明“人类不能自然飞行”这一明确规则。仅仅缺少世界证据、但没有规则明确否定的说法，可以只进入 `unsupported_claims`。

## 未来处理流程

玩家自然语言
→ AI 理解
→ Schema 结构化
→ World Rules 校验
→ Player 写入 World State

Schema 负责保证输出形状和基础取值合法；World Rules 负责判断内容是否能在当前世界中成立。只有通过这两层检查的数据才能更新持续存在的世界状态。

当前 v0.1 不允许 Player Creation 根据玩家的一次身份描述自动修改或扩展 World Rules。如果角色的核心设定必须依赖新世界规则，系统应设置 `needs_clarification = true`，确认玩家希望创建一个符合 Dragon World 规则的类似角色，还是另行修改世界设定。

## 未来 Runtime 原则

玩家进入世界后，Natural Language Action System 必须继续区分：

- **Speech / Thought**：玩家说“我是奥丁！”只是言语或想法，不触发 Player State 改写。
- **Intent**：玩家说“我要飞去 Stormcliff”是在尝试行动，Engine 应检查当前是否具备飞行条件，再决定结果。
- **World Fact Mutation**：玩家说“我现在拥有一把 AK47”是在试图声明世界事实，Engine 不能只凭这句话把物品写入 inventory。

最终原则是：**Free Intent, Grounded Consequence.**

玩家可以自由表达和尝试，但世界事实只能由 World State、World Rules 和实际事件共同决定。
