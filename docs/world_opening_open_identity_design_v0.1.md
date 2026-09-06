# World Opening & Open Identity Design v0.1

## 1. Product Intent

Dragon World 的第一个世界模板是一个北境低魔、人与 Dragon 共存的开放世界。玩家以“在异世界重生”为起点，但游戏不预设其必须成为英雄、驯龙者或任何固定职业。

玩家可以用自然语言自由定义身份、表达目标并尝试行动。Dragon Gameplay 是核心 Systemic Gameplay，后续会为 Encounter、Bond、Taming、Egg / Hatching、Growth 与 Riding 建立明确系统；捕鱼、经商、锻造、参军、旅行、政治等广泛活动优先由 AI Semantic Gameplay 理解，不为每种可能性预先建立一套封闭系统。

本设计只定义开场体验、开放身份语义和未来 Runtime 边界，不实现 Frontend、API、Interpreter、Validation、Persistence Mutation 或 Dragon Runtime。

## 2. Core Principles

### 2.1 World First, Rules Behind

先让玩家看见并感受世界。规则在后台约束事实和后果，不以规则手册、字段表格或审核器姿态阻断想象。

### 2.2 Player can say or attempt anything; the world decides what becomes true

玩家可以说任何话、尝试任何事。表达和意图天然自由；只有经过 World State、World Rules、Grounded Evidence 与受控 Commit 的结果才能成为 World Truth。

### 2.3 Dragon Gameplay is Systemic; Everything Else is Open-ended

Dragon Gameplay 使用稳定领域模型与可验证状态机。其他玩法保持开放，由通用语义链路解释和验证，除非真实产品 Failure 证明需要专门系统。

### 2.4 Player Claim != Objective World Truth

玩家自述可以构成其表达、自我认同或个人背景，但不能仅凭一句话重写 NPC Identity、Relationship、Dragon State 或 World History。

### 2.5 Freedom of Action != Guaranteed Success

自由行动意味着玩家可以提出尝试，不意味着行动必然成功。成功、失败、代价和世界反馈由后续 Runtime 决定。

## 3. World Opening

开场只提供玩家作出第一步所需的最小世界认知：

- 玩家在一个北境低魔世界中重生；
- 人类与 Dragon 共存，Dragon 是世界中最强大、神秘而美丽的生物之一；
- Dragon 不是坐骑道具，它们会恐惧、信任、愤怒，也会记住玩家的行为；
- 玩家从 Skeld 开始，已知附近有 Stormcliff、Whispering Woods 和 Old Ruins；
- 海岸之外还有尚未被当前 World State 注册的未知大陆；
- 玩家可以追寻 Dragon Gameplay，也可以选择完全不同的人生方向。

开场不承诺玩家必定拥有 Dragon、不预告固定主线，也不把未知大陆自动生成为已确立事实。

## 4. Long-form Opening Copy

你在异世界重生了。

当意识重新归来，寒冷的海风正掠过北境群岛。这里是 Dragon World——一个低魔时代的世界。人类在风雪、森林与海洋之间建立村落，而 Dragon 翱翔于峭壁和云层之上。它们强大、神秘，也拥有自己的恐惧、愤怒、信任与记忆。

有人畏惧 Dragon，有人猎杀它们，也有人花上一生尝试理解它们。你可以寻找 Dragon、谨慎接近、赢得信任、建立 Bond，甚至孵化并陪伴一条 Dragon 成长。若世界中的真实经历足以支持，你也可能有一天与它共同飞向未知大陆。但 Dragon 不是任你支配的工具；关系必须由行为与时间建立。

你也不必选择这条道路。你可以捕鱼、经商、锻造、参军、探索遗迹、远行，或追逐任何你愿意承担后果的目标。这里没有强制职业、固定主线或预先授予的英雄身份。

你的旅程从北境渔村 Skeld 开始。Stormcliff 的风暴、Whispering Woods 的幽深林地和建造者未知的 Old Ruins 都在附近；海岸之外，还有这个世界尚未向你证明的一切。

你可以自由描述自己，也可以保持沉默、失去记忆，或请这个世界为你提供一个起点。你说出的身份会被认真理解，但不会因此自动改写别人、历史或世界法则。

告诉这个世界：你是谁？

## 5. Short Opening Copy

你在北境低魔世界中重生了。

人与 Dragon 在这里共存。你可以寻找它们、赢得信任、建立 Bond，也可以成为渔夫、铁匠、商人、士兵、佣兵、流浪者，或者走向任何未被写好的生活。

你的旅程从 Skeld 开始。附近是 Stormcliff、Whispering Woods、Old Ruins，以及海岸之外的未知大陆。

没有固定职业，没有强制主线。你可以自由表达和行动，但只有被世界规则与真实事件支持的结果，才会成为世界事实。

**告诉这个世界：你是谁？**

## 6. Skeld Arrival Scene

潮湿的寒风把海盐气息送进你的呼吸。

你站在 Skeld 边缘。低矮的屋舍沿着海湾铺开，渔船在灰暗晨光中轻轻碰撞码头。远处的云层压在群岛上方，某个巨大的影子从天际一闪而过，很快消失在通往 Stormcliff 的方向。

村里的人各自忙碌，没有人为你的到来停下整个世界。通往 Whispering Woods 与 Old Ruins 的道路就在村外；更远处，海岸之外的大陆还没有向你显露面貌。

你记得多少、相信什么、准备成为谁，都由你开口。

**告诉这个世界：你是谁？**

这段场景只建立感官起点和已知地理，不声明新的 NPC 行为、Dragon 个体、事件结果或任务。

## 7. Open Identity Flow

```text
First Run
→ World Opening
→ 自由自然语言身份输入
→ Identity Interpretation
→ Identity Grounding
→ Hidden Identity Context Preview / Validation
→ 受控 Persistence Commit
→ identity_initialized = true
→ 进入 Skeld

Later Runs
→ 读取 identity_initialized
→ 直接进入当前 Persistent World State
```

玩家只面对一个自由输入入口，不面对 Class Selection、Race Selection、Background Form、Skill Allocation 或固定身份卡片。

界面可以把猎人、铁匠、商人、士兵、佣兵、流浪者、树精灵、哥布林、巨魔、狼人和 Dragon 作为启发性例子，但不能把例子变成选项列表或身份上限。

“我什么都不记得”是有效起点；系统应允许最小身份开始。“帮我随机生成一个角色”也是有效意图，未来 Interpreter 可以提供一个可 Ground 的身份建议，但仍需经过同一 Grounding 与 Commit 边界。

## 8. Identity Model v0.1

Identity Context 是系统内部结构，不由玩家逐字段填写：

| Field | Meaning | Boundary |
| --- | --- | --- |
| `self_description` | 玩家原始自然语言身份描述 | 保留表达，不自动等同 World Truth |
| `display_name` | 对玩家显示的名称；未提供时可为空 | 不允许覆盖其他实体名称或 ID |
| `accepted_facts` | 当前规则与已有状态允许写入的玩家身份事实 | 仅限 Player Identity 权限范围 |
| `unverified_claims` | 可以保留表达、但证据不足或涉及外部世界改写的主张 | 不产生客观 State Mutation |
| `traits` | 从自述中提炼的少量非数值人格倾向 | 不等同能力或成功保证 |
| `capability_hints` | 由普通经历支持的语义能力倾向 | 仅供未来 Action Evaluation 参考 |
| `identity_summary` | 对 Grounded Identity 的简短自然语言总结 | 不引入原输入之外的新事实 |

建议的内部形态：

```json
{
  "self_description": "...",
  "display_name": null,
  "accepted_facts": [],
  "unverified_claims": [],
  "traits": [],
  "capability_hints": [],
  "identity_summary": "..."
}
```

该结构是设计契约，不是本阶段新增的 JSON Schema，也不是新的数据库实体。

## 9. Grounding Rules

### 9.1 Accepted Fact

信息可以进入 `accepted_facts`，前提是：

1. 它主要定义玩家自身，而不是重写外部实体；
2. 它不与当前 World Rules 或已存在的 Objective World State 明确冲突；
3. 它不直接授予必须由 Emergent Event 获得的身份、权力、关系或能力；
4. 它能映射到当前可持久化的 Player Identity，或被明确标注为后续实现所需的兼容字段。

普通出身、职业经历、喜好、恐惧与个人目标通常拥有较高 Self-Background Authority。

### 9.2 Unverified Claim

以下信息进入 `unverified_claims`，并保留为玩家自述，而不是被拒绝：

- 声称拥有未被事件支持的王位、神性、超能力或 Dragon 支配权；
- 声称 NPC 已与玩家存在婚姻、亲属、爱情或其他关系；
- 声称世界历史已经发生某事；
- 声称某个 Dragon、组织或地区已经服从玩家；
- 任何需要修改 NPC、Relationship、Dragon State 或 World History 才能成立的内容。

Grounding 不是简单 ALLOW / REJECT。系统接受可成立部分，保留其余主张，并让世界在后续互动中自然回应。

### 9.3 Facts require authority

- Player Identity Commit 只能修改 Player Identity 与相应 Player Runtime Context。
- NPC Relationship 必须来自 Relationship Runtime 的 Grounded Event。
- Dragon Bond、Taming、Riding 与 Emergent Title 必须来自对应 Domain Event。
- 玩家说“我已经做到”不能替代事件证据。

## 10. Example Cases

| Case | Input | Grounded handling |
| --- | --- | --- |
| 1 | “我是 Skeld 的年轻渔夫。” | 接受普通本地身份、职业与背景；不额外授予捕鱼成功率。 |
| 2 | “我是一个哥布林商人。” | Narrative Identity 可以接受并保留在 Identity Context / Narrative Layer；当前数据库 `players.species` 仅允许 `human/dragon`，因此实现前必须解决最小持久化映射，不能偷偷改写为 human。 |
| 3 | “我是一条年轻的 Dragon。” | Identity Accepted；可写为 Player Species `dragon`。这不自动解锁飞行、战斗、技能树、Dragon Bond 或任何未实现玩法。 |
| 4 | “我是南方失踪的王子。” | 可以接受其自我描述与可成立的个人背景部分；“失踪王子”的血统和政治地位作为 Unverified Claim，等待世界证据。 |
| 5 | “Astrid 从小就深爱我。” | 不修改 Astrid 或 Relationship；该陈述进入 Unverified Claim。 |
| 6 | “所有 Dragon 都已经臣服于我。” | 不修改 Dragon State 或 Bond；该陈述进入 Unverified Claim。 |
| 7 | “我什么都不记得。” | 接受失忆作为起始自我背景，允许以最小 Identity 进入 Skeld，不强迫补表。 |
| 8 | “帮我随机生成一个角色。” | 未来允许 AI 提议一个最小、可 Ground 的身份；提议仍需经过相同 Grounding 和 Commit，不获得特殊权限。 |

## 11. Capability Hint Rules

Capability Hint 是非数值、非保证性的语义倾向：

- “从小跟父亲捕鱼”可以产生 `fishing_experience`、`comfortable_at_sea`；
- “在铁匠铺当过学徒”可以产生 `basic_blacksmithing_experience`；
- “经常独自在森林采药”可以产生 `forest_foraging_experience`。

规则：

1. Hint 必须能从 Accepted Background 合理推出；
2. Hint 不使用 `Fishing = 80` 或 `Sailing = 65` 一类数值；
3. Hint 不能绕过 Inventory、Location、World Rules 或现实可行性检查；
4. Hint 只作为未来 World Action Evaluation 的一项 Context，不直接决定成功；
5. 未验证的神性、王权、支配权或超能力不能转化为 Capability Hint；
6. 保持少量、可解释，避免把 Identity Context 变成传统 Skill System。

## 12. Identity Evolution

Identity 分为两层：

### Origin Identity

角色创建时被 Ground 的起始身份，例如 fisherman、merchant、wanderer 或 young dragon。它描述玩家从哪里开始，不锁死未来玩法。

### Emergent Identity

游戏过程中由 Grounded Event 与 Persistent State 支持的身份，例如 dragon rider、commander 或 lord。

Emergent Identity 不能通过一句 Player Claim 直接获得。它需要对应领域提供证据：Dragon Riding 需要 Bond / Taming / Riding Event；指挥权或领主地位需要未来政治或世界事件。Identity Context 可以在受控 Mutation 后更新 summary 或 accepted facts，但历史起点应可追溯，不应静默覆写 Origin Identity。

## 13. Runtime Context Boundary

Identity Context 是后续 Runtime 的输入之一，不是新的中心化规则引擎：

- Action Interpreter 可读取 `self_description` 与 `identity_summary` 理解表达；
- World Validator 可读取 `accepted_facts` 与 `capability_hints` 评估可行性；
- NPC Runtime 可以看到必要的 Grounded Player Identity，但不应看到全部隐藏内部字段；
- Dragon Runtime 只使用与 Encounter、Bond 或 Riding 相关的最小 Context；
- `unverified_claims` 不得被下游当作 World Truth；
- 所有 State Mutation 仍走既有 Preview / Validation / Commit Authority。

普通 UI 不展示 Accepted Fact、Unverified Claim、Grounding Score、Identity JSON 或 Capability Hints。玩家看到的是自然语言世界反馈，而不是审核面板。

## 14. Persistence Mapping

D1 v0.1 默认不新增 Table、Column 或 Alembic Revision。现有 PostgreSQL 字段的真实映射如下：

| Identity concept | Existing persistence mapping | Status |
| --- | --- | --- |
| Stable Player ID | `players.player_id` | 复用 `player_001`，不因显示身份改 ID |
| `display_name` | `players.name` | 字段名不同，但语义可直接映射 |
| Canonical species | `players.species` | 当前 CHECK 仅允许 `human/dragon` |
| Occupation / background / traits | `players.occupation/background/traits` | 可承载已 Ground 的最小 Player Profile |
| Current location / inventory / goals | `player_states.current_location/inventory/goals` | 继续作为现有 Runtime State |
| `identity_initialized` | 当前没有专用字段 | 本阶段只记录需求，不伪造映射 |
| Full Identity Context | 当前 `player_states` 没有 metadata/context JSONB | 本阶段只记录需求，不占用 `inventory` 或 `goals` |

`world_state_entries` 当前设计职责是 World / Global Runtime Truth，不应未经实现审查就被当作 Player metadata 容器。后续实现阶段必须在“不改 Schema 的最小映射”与“一次明确、受审查的 Schema Extension”之间作出决定；D1-A 不预先修改数据库。

### 14.1 Species Boundary

玩家的 Narrative Identity 可以自由表达为 human、dragon、goblin、elf、troll、werewolf，或其他合理的北境低魔身份。Narrative Identity 不要求当前 Database Core Species Field 立即支持全部种族。

Frozen `players.species` CHECK 当前仅允许 `human/dragon`。其他 Species Identity 可以先存在于 Identity Context、Claim 或 Narrative Layer；它们在产品语义上不应被强制改写或拒绝，也不能为了通过数据库约束而偷偷改写为 human。

具体 Persistence Mapping 留到 D1-B 在读取真实 Runtime 与 ORM 后作最小实现决策。本阶段不扩展完整 Race System，也不修改数据库约束。

### 14.2 Persistence Decision Boundary

`players.traits` 是现有 JSONB 字段之一，但它已有 Player Traits 语义，只能视为待评估候选，不能在 D1-A 中直接宣布承载完整 Identity Context。D1-B 必须先检查其真实 Runtime 用途和 Frozen Contract，再决定是否能够安全复用。

如果 D1-B 证明没有合理现有字段可以保存 `identity_initialized` 与完整 Identity Context，而该持久化又是开场生命周期不可缺少的能力，可以提出一次“最小必要 Schema Change”。该变更必须先汇报并接受审查，不得由实现阶段自动执行。

## 15. UX Principles

1. 开场先呈现世界氛围，再提出身份问题；
2. 唯一主要输入是自由自然语言，不展示固定 Race/Class 选择；
3. 示例用于激发想象，不形成白名单；
4. 不用“非法角色”“规则错误”等语言惩罚想象；
5. Grounding 结果通过自然语言解释世界如何理解玩家，而不是展示内部 JSON；
6. 身份未提供姓名或完整背景时允许继续；
7. 核心身份无法在现有持久化或规则下无损 Ground 时，应请求最小澄清，不替玩家重写角色；
8. First Run 完成后不重复开场；重置或新世界流程必须显式触发；
9. Dragon 身份不承诺尚未实现的 Dragon Gameplay 能力；
10. 开场不生成固定任务、NPC 好感、Dragon 个体或剧情结果。

## 16. Non-goals

D1 v0.1 不设计或实现：

- 完整职业、种族、技能树、等级或 Stats 系统；
- 固定 Character Creator 或复杂 Appearance Creator；
- Player Dragon Skill Tree、完整飞行或战斗系统；
- 经济、政治、任务或主线系统；
- Dragon Runtime、Encounter、Bond、Taming、Egg、Growth 或 Riding 实现；
- Multimodal / Image / Video Generation；
- Identity LLM Interpreter、Validation、API、Frontend 或 Persistence Commit；
- Generic Claim Engine、Identity Manager Framework 或复杂 Rule Engine；
- 数据库 Table、Column、ORM 或 Migration 变更。

## 17. Compatibility with D2–D8

| Future stage | Identity Context contribution | Boundary |
| --- | --- | --- |
| D2 Free World Action Runtime | 提供 Grounded Background、Traits 与 Capability Hints | 不替代 Action Validation，不保证成功 |
| D3 Dragon Encounter Runtime | 提供 Player Species、既有经历与表达倾向 | 不自动生成 Dragon 或 Encounter 结果 |
| D4 Dragon Bond / Taming Runtime | 提供可验证的 Player Context | Bond/Taming 只能由 Grounded Dragon Events 改变 |
| D5 World Tick | 提供稳定 Player Identity 供事件 Resolve | Tick 不应凭身份文本授予结果 |
| D6 Image Generation | 提供必要的可视身份描述 | Visual Output 不反向成为 World Truth |
| D7 Dragon Riding | 提供 Player Context 与 Emergent Identity 展示 | Riding Unlock 仍由 Bond State 决定 |
| D8 First-person Riding Video | 提供视角与必要外观语义 | 视频是表现层，不修改 Persistent State |

Identity Context 保持小而稳定：它是多个 Runtime 的 Context，不成为取代各领域规则的万能系统。

## 18. Open Questions

1. 在不新增 Schema 的前提下，`identity_initialized` 与完整 Identity Context 应持久化到哪里？现有 `player_states` 没有 metadata JSONB，且不应滥用 `inventory/goals`。
2. 开放 Species 如何与当前 `players.species IN ('human', 'dragon')` 兼容？是后续扩展 CHECK、采用 canonical category + self-described identity，还是另有最小策略？
3. “树精灵、哥布林、巨魔、狼人”在北境低魔模板中被接受后，哪些只是 Player Origin Identity，哪些需要新的稳定 World Rules？
4. `accepted_facts` 与 `unverified_claims` 是否需要独立 versioned schema，还是作为 Identity Interpreter 的 Structured Output 即可？
5. Origin Identity 如何保留历史，同时让 Emergent Identity 更新当前 summary，且不引入完整 Identity Event Sourcing？
6. “随机生成角色”的确认体验应采用单次建议、可编辑预览，还是直接回填自然语言？
7. 失忆开局的最小 `display_name`、species 与 background 允许为空到什么程度？
8. Player-as-Dragon 在 D2 开放行动阶段如何处理基础移动语义，同时不提前实现 D3/D4/D7 的完整 Dragon Runtime？
9. NPC Runtime 应看到哪些 Identity Context 字段，才能自然回应且不泄露隐藏 Grounding 信息？
10. 开场中的“海岸之外未知大陆”何时从开放探索方向升级为注册 Location / World Truth，且如何遵守 No Silent Generation？

这些问题不阻止 D1-A 设计成立，但必须在相关实现阶段以真实 Contract 和产品体验为依据解决，不能通过隐式字段复用或未经审查的世界观扩写规避。
