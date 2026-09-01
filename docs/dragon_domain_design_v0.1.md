# Dragon Domain Design v0.1

## 1. 文档状态与范围

- **阶段**：Step 6.7-A0 — Dragon Domain Design v0.1
- **性质**：Database Schema Design 之前的领域规格说明
- **目标**：把 Dragon 定义为 Dragon World 的 First-class Entity，并固定后续 Schema、Runtime 与数据库必须遵守的边界。
- **本阶段不实现**：JSON Schema、数据实例、数据库、Runtime、Evaluator、API、Frontend、图片或视频生成。

本文只固化产品侧已经确认的 Dragon Domain。未确认的数值、枚举或玩法细节统一列入 Open Questions，不在本阶段擅自补完世界观。

## 2. Product Principles

### 2.1 Dragon 是一等世界实体

Dragon 不是 NPC 台词中的描述，也不是 LLM 每次 Encounter 临时生成的对象。每个个体必须拥有稳定 `dragon_id`，并能够被 Persistent World Resolve。系统未来必须能稳定回答：

- 它属于什么 Archetype，是否是此前遇到的同一条龙；
- 它当前在哪里、正在做什么、是否受伤；
- 它与玩家的 Familiarity、Trust、Fear、Bond 状态；
- 它是否被该玩家驯化、是否允许该玩家骑乘；
- 它是否由某枚 Dragon Egg 孵化。

### 2.2 Free Intent, Grounded Consequence

玩家可以自由描述任何与龙有关的行动。LLM 负责把表达解释为结构化语义，但不能直接决定信任、羁绊、驯化或骑乘结果。只有经过 Runtime 验证、确定性评估和受控 State Mutation 的结果才能成为 World Truth。

### 2.3 Stable Identity, Single Source of Truth

- `dragon_id` 在个体创建后保持稳定。
- Dragon Archetype、Individual Identity、Runtime State、Player Bond 和 Egg 是不同职责的数据边界。
- `current_location` 只由 Dragon Runtime State 持有，不能同时复制到 Archetype 或其他 Profile 数据中。
- `taming_state` 与 `riding_unlocked` 是 Player × Dragon 关系事实，持久化所有权属于 PlayerDragonBond；Dragon 聚合可以显示它们，但不得维护第二份可独立修改的值。

### 2.4 Dragon 与 NPC 使用不同领域模型

NPC v0.1 偏认知型：Profile、Knowledge、Memory、Relationship、Dialogue。Dragon v0.1 偏行为型：Archetype、Individual Identity、Temperament、Runtime State、Behavior、Bond、Taming State。

Dragon 可以与 NPC 共享 Entity ID、Location Resolve、World Event、Grounded Evidence 和 Idempotency 等架构原则，但不能直接复制 NPC Memory 或 Relationship Store。高智慧龙的 Knowledge、Dialogue 或 Memory 是未来扩展，不属于本阶段。

## 3. Domain Entities

### 3.1 DragonArchetype

描述一个龙种稳定、可复用的基础规则，不描述任何个体当前状态。

| Field | 含义 |
| --- | --- |
| `archetype_id` | 稳定龙种 ID |
| `display_name` | 面向玩家的名称 |
| `size_class` | 体型等级；具体枚举待 Schema 阶段确认 |
| `habitats` | 适合出现的环境类型集合 |
| `base_temperament` | 龙种基础行为倾向，不替代个体 Temperament |
| `abilities` | 龙种固有能力集合 |
| `diet` | 食性定义；初始具体值尚待确认 |
| `intelligence_level` | 智力等级；不等于已实现 NPC 级认知 Runtime |
| `rarity` | 稀有度 |
| `taming_difficulty` | 驯化难度配置 |
| `rideable` | 该 Archetype 在身体结构上是否支持骑乘 |
| `taming_milestone` | 达到 `tamed` 前必须完成的龙种专属 Milestone |

v0.1 只定义六个初始 Archetype，不动态生成新 Archetype：

| Archetype | 中文名 | Habitat | 已确认特征与驯化方向 |
| --- | --- | --- | --- |
| `stormwing` | 风暴翼龙 | cliff / coast / mountain | 高速飞行、强风适应、领地意识强；强调勇气与尊重边界 |
| `mossdrake` | 苔林龙 | forest | 擅长隐蔽、相对温和；对食物与稳定接触敏感 |
| `emberback` | 烬背龙 | volcanic / wasteland | 火焰、力量、高危险度 |
| `frostfang` | 霜牙龙 | tundra / mountain | 冰霜、高警戒、攻击性较强 |
| `seawing` | 潮翼龙 | coast / islands | 捕鱼、海上移动 |
| `ruin_drake` | 遗迹龙 | ancient ruins | 高警觉、较高智慧；强调探索与信任 |

表中未确认的 `size_class`、`diet`、`intelligence_level`、`rarity`、`taming_difficulty`、`rideable` 和具体 Milestone 不在本阶段虚构。

### 3.2 IndividualDragon

表示一条可持续存在、可被再次识别的具体龙。

| Field | 含义 |
| --- | --- |
| `dragon_id` | 稳定个体 ID，不能用名称或数组位置代替 |
| `archetype_id` | 指向 DragonArchetype |
| `name` | 可为空；名称不是身份主键 |
| `sex` | 个体性别；具体受控值待确认 |
| `age_stage` | `hatchling / juvenile / young_adult / adult` |
| `appearance` | 个体外观差异的简短结构化描述 |
| `temperament_traits` | 个体倾向，对 Archetype 基础倾向作有限差异化 |
| `origin_egg_id` | 可选；由 Dragon Egg 孵化时指向来源 Egg |

从业务聚合角度，Individual Dragon 还会展示当前位置、健康、行为和对当前玩家的驯化状态；这些字段分别由 DragonRuntimeState 与 PlayerDragonBond Resolve，不能复制为第二个持久化 Source of Truth。

### 3.3 DragonRuntimeState

描述“这条龙现在在哪里、身体如何、正在做什么”。

| Field | 含义 |
| --- | --- |
| `dragon_id` | 与 IndividualDragon 一对一 |
| `current_location` | 已注册 Location ID |
| `health` | 当前健康状态或数值；具体量表待确认 |
| `energy` | 当前精力；必须有边界 |
| `hunger` | 当前饥饿程度；必须有边界 |
| `alertness` | 当前警觉程度；必须有边界 |
| `behavior_state` | 当前行为状态 |

`behavior_state` v0.1 基线：

`resting`、`feeding`、`wandering`、`watching`、`avoiding`、`threatening`、`attacking`、`following`、`flying`。

`taming_state` 在 Player Context 中属于 Dragon Runtime View 的一部分，但其持久化所有权在 PlayerDragonBond。这样可以避免同一条龙面对不同玩家时出现全局驯化状态冲突。

### 3.4 PlayerDragonBond

表示一个确定的 Player 与一条确定的 Dragon 之间的长期状态。

| Field | 约束与含义 |
| --- | --- |
| `player_id` | Player Entity ID |
| `dragon_id` | Individual Dragon ID |
| `familiarity` | `0..5`，是否熟悉玩家 |
| `trust` | `-3..5`，是否认为玩家可靠、安全 |
| `fear` | `0..5`，是否害怕玩家 |
| `bond` | `0..5`，长期情感羁绊 |
| `taming_state` | `wild / tolerant / bonding / tamed` |
| `riding_unlocked` | 是否允许该玩家骑乘 |
| `last_significant_event_id` | 最近一次影响该 Bond 的重大事件 |

`(player_id, dragon_id)` 必须唯一。Fear、Trust、Bond 是不同维度：高 Fear 不等于高 Trust，更不等于 Tamed。

### 3.5 DragonEgg

表示尚未孵化的持久实体。

| Field | 含义 |
| --- | --- |
| `egg_id` | 稳定 Egg ID |
| `archetype_id` | 可为空或 `unknown`，允许未知品种龙蛋 |
| `acquired_by_player_id` | 当前获得该 Egg 的 Player |
| `incubation_state` | 孵化阶段；具体状态机待确认 |
| `incubation_progress` | 孵化进度；精确量表待确认 |
| `acquired_event_id` | 获得龙蛋的 Grounded Event |
| `hatched_dragon_id` | 孵化后创建的 Individual Dragon；孵化前为空 |
| `hatched_at` | 孵化发生时间；孵化前为空 |

### 3.6 DragonEvent

记录已经被 Runtime 验证、可作为 Dragon State 或 Bond 变化证据的重大事件。它不是玩家自述，也不是 LLM 生成结果。

最小语义包括：稳定 `event_id`、`event_type`、`dragon_id`、可选 `player_id`、`location_id`、发生时间、来源 Interaction/Event ID、Grounded Evidence 引用和可选 `milestone_key`。

v0.1 Significant Event Type：

- `dragon_first_encounter`
- `dragon_accepts_food`
- `dragon_allows_close_presence`
- `dragon_allows_touch`
- `player_heals_dragon`
- `player_rescues_dragon`
- `dragon_rescues_player`
- `shared_danger_survived`
- `dragon_tamed`
- `dragon_accepts_mount`
- `first_shared_flight`

DragonEvent 为 Threshold 之外的进度证据、Audit 和 Idempotency 提供基础，但本阶段不设计完整 Event Sourcing。

### 3.7 StructuredDragonInteraction（瞬时 Value Object）

它是未来 LLM Semantic Interpretation 的结构化输出，不是 Persistent World Fact。示例语义标签包括：

- `sheathe_weapon`
- `offer_food`
- `create_distance`
- `non_threatening`
- `respect_boundary`

该对象只能描述玩家尝试了什么，不能携带 `trust_delta`、`bond_delta`、`taming_state=tamed` 或 `riding_unlocked=true` 等最终结果。

### 3.8 DragonInteractionRecord（轻量处理记录）

未来 Runtime 需要最小的已处理 Interaction 记录，用于 `event_id + player_id + dragon_id` 幂等、Recent History 与 Anti-Farming。它不是完整对话存档，也不是 Dragon Memory Retriever。

## 4. Core Invariants

1. 每条 Dragon 必须拥有稳定且唯一的 `dragon_id`；一次 Encounter 不能重新创造同一个体。
2. 每个 Individual Dragon 必须引用一个已确认 Archetype。未知品种只允许存在于尚未识别或尚未孵化的 Egg；创建 Individual Dragon 时必须 Resolve。
3. `current_location` 只有一个 Runtime Source of Truth，并且必须引用合法 Location ID。
4. `(player_id, dragon_id)` 只能存在一个 PlayerDragonBond。
5. 所有 Bond 数值必须保持在定义范围内，Mutation 必须 Clamp 或拒绝越界。
6. `fear` 高不能推导出 `tamed`；暴力造成的服从不能自动提升 Trust 或 Bond。
7. Threshold 只是必要条件，不是充分条件。没有 Grounded Significant Event 和 Archetype Milestone，不能进入更高 Taming State。
8. `tamed` 不等于 `riding_unlocked`；骑乘必须单独满足 Relationship、Milestone 与 Physical Requirement。
9. `riding_unlocked=true` 时必须同时满足 Archetype `rideable=true`、年龄成熟、`taming_state=tamed`、`bond>=3`、`trust>=4` 和 `dragon_accepts_mount` / `first_mount_acceptance` 证据。
10. Player Claim、Speech、LLM Interpretation 和视觉生成结果都不能直接修改 Dragon、Bond、Egg 或 Event State。
11. 每次 State Mutation 必须追溯到被 Runtime 验证的 World Event 或 Interaction Event。
12. 同一来源 Event 对同一 Player × Dragon 的效果只能应用一次。
13. 重复相同行为不能无限增加 Familiarity、Trust 或 Bond。
14. Egg 只能成功孵化一次；`hatched_dragon_id` 与新 Dragon 的 `origin_egg_id` 必须互相一致。
15. 从 Egg 孵化不自动得到满 Bond、成年或 Riding Unlock。
16. `tamed` 不被设计为永久不可逆；未来 De-taming 可以基于 Grounded Betrayal、Abuse 或长期攻击回退状态。

## 5. Taming State Machine

```text
wild
  ↓
tolerant
  ↓
bonding
  ↓
tamed
```

### Tolerant

- `familiarity >= 2`
- `trust >= 1`
- `fear <= 2`
- 至少一次有依据的和平互动

### Bonding

- `familiarity >= 3`
- `trust >= 2`
- `bond >= 1`
- `fear <= 1`
- 至少一个 `significant_shared_event`

### Tamed

- `familiarity >= 4`
- `trust >= 3`
- `bond >= 2`
- `fear <= 1`
- 已完成该 Archetype 的 `taming_milestone`

状态推进采用 **Threshold + Significant Event + Species-specific Milestone**。Evaluator 未来必须同时检查三类条件，不能仅按数值升级。上述数值是 v0.1 Domain Baseline，未来只能在玩法测试和 Regression 保护下调整。

De-taming 不在 v0.1 实现，但状态机不能被编码为永久单向。未来重大背叛、虐待或长期攻击可以降低 Trust/Bond、提高 Fear、回退 Taming State，甚至产生 `dragon_leaves_player`。

## 6. Bond Rules

### 6.1 维度含义

- **Familiarity**：见过与接触的累积，不表示喜欢、信任或共同历史细节。
- **Trust**：Dragon 是否认为玩家可靠、安全；不能覆盖 World Truth。
- **Fear**：Dragon 是否畏惧玩家；不能作为 Taming 的替代路径。
- **Bond**：长期情感羁绊，必须依赖有意义的共同事件。

### 6.2 Riding Unlock

`tamed != rideable now`。解锁骑乘需要：

- `taming_state = tamed`
- `bond >= 3`
- `trust >= 4`
- 存在 `dragon_accepts_mount` / `first_mount_acceptance`
- `age_stage` 已达到可承载玩家的成熟阶段
- Archetype `rideable = true`

`first_shared_flight` 是骑乘解锁后的独立 Significant Event，不能反向代替 Mount Acceptance。

## 7. Acquisition Routes

### 7.1 Wild Taming

```text
stranger
→ repeated encounter
→ tolerant
→ meaningful shared event
→ bonding
→ species-specific milestone
→ tamed
→ riding milestone
→ riding_unlocked
```

Wild Taming 从陌生与 `wild` 开始，依赖多次 Grounded Interaction、风险与边界判断。玩家可以使用自由自然语言，不要求固定对话顺序；Runtime 只评估结构化语义和真实世界条件。

### 7.2 Egg Raising

```text
Dragon Egg
→ Incubation
→ Hatching Event
→ Create Individual Dragon
→ Create PlayerDragonBond
```

成功孵化后的初始状态固定为：

- `age_stage = hatchling`
- `familiarity = 5`
- `trust = 2`
- `fear = 0`
- `bond = 1`
- `taming_state = bonding`
- `riding_unlocked = false`

Egg Raising 表示从出生起长期熟悉，不等于自动满羁绊、自动成年或自动允许骑乘。孵化必须产生 Grounded Hatching Event，并以同一受控事务创建 Individual Dragon、关联 Egg 和建立初始 Bond；具体数据库事务留到下一阶段设计。

### 7.3 两条路线的区别

| 维度 | Wild Taming | Egg Raising |
| --- | --- | --- |
| 初始关系 | 陌生、`wild` | 出生即熟悉、`bonding` |
| 核心证据 | 多次遭遇、共享事件、龙种 Milestone | 获得、照料、孵化事件 |
| 初始 Fear | 由 Encounter 决定 | `0` |
| 初始 Familiarity | 低 | `5` |
| 是否自动 Tamed | 否 | 否 |
| 是否自动可骑乘 | 否 | 否 |

## 8. Growth Boundary

v0.1 只预留：

```text
hatchling → juvenile → young_adult → adult
```

Growth 是 Dragon Physical State，不由 Bond 数值直接推进。Riding Unlock 必须同时满足 Relationship Requirement 和 Physical Requirement。年龄推进时间、条件、体型变化与成长事件尚未定义；本阶段不实现复杂成长系统。

## 9. AI vs Runtime Responsibility

未来标准链路：

```text
Player Free-form Input
→ LLM Semantic Interpretation
→ StructuredDragonInteraction
→ Deterministic Dragon Interaction Evaluator
→ Validated Dragon / Bond Mutation Plan
→ Safe Commit
→ LLM Natural Response
```

### LLM 可以负责

- 理解玩家自由表达中的行动、顺序、对象、方式与态度；
- 产生结构化语义，例如 Offer Food、Create Distance、Respect Boundary；
- 在 Runtime 已决定结果后生成自然语言或未来视觉描述。

### LLM 不得负责

- 直接输出或写入 Trust/Bond/Fear 数值变化；
- 宣布 Dragon 已被驯化或允许骑乘；
- 创建不存在的 Individual Dragon、Egg、Archetype 或 Significant Event；
- 把 Player Claim 当作 Grounded Evidence；
- 绕过 Threshold、Milestone、Anti-Farming、Idempotency 或 State Mutation Allowlist。

## 10. Grounded Evidence Boundary

以下表达本身不是 World Fact：

- “这条龙已经完全信任我。”
- “它愿意让我骑。”
- “我刚才已经救了它。”

它们可以被解释为 Speech、Claim 或 Intent，但不能直接设置 `trust=5`、`riding_unlocked=true` 或创建 `player_rescues_dragon`。状态变化只接受：

1. 已存在的 World State；
2. 已经执行并验证的玩家行为；
3. 被 Runtime 确认的 Dragon 行为；
4. Schema-valid 且具有来源的 DragonEvent。

DragonEvent 记录“系统确认发生了什么”，StructuredDragonInteraction 只记录“玩家试图做什么”，两者不得混用。

## 11. Anti-Farming and Idempotency

重复 `offer_food` 不能每次固定增加 Trust。未来 Evaluator 至少需要遵循：

```text
first meaningful occurrence → full effect
short-term repetition       → reduced effect
excessive repetition        → no meaningful effect
```

判断输入包括：`event_id`、`player_id`、`dragon_id`、行为语义、Recent History、当前 Hunger/Behavior 和此前是否已经应用同类效果。

- 同一来源 Event 必须由唯一键拒绝重复应用。
- Recent History 只服务于效果衰减与行为上下文，不等同于完整 Dragon Memory。
- Species-specific 行为可以影响效果，但必须由 Archetype 配置和确定性 Evaluator 决定。
- Anti-Farming 不能通过客户端或 LLM 提交 Delta 绕过。

具体时间窗口、衰减曲线和相同行为 Fingerprint 留到 Evaluator Design。

## 12. Existing Architecture Compatibility

### World State

兼容。Dragon 使用现有 Location ID 与 World Truth 原则；未来必须明确 Dragon Runtime State 在数据库中的 Source of Truth，不能同时让旧 JSON 和数据库独立可写。

### NPC Profile / Knowledge / Memory

兼容但不复用模型。NPC Knowledge 表示认知边界，NPC Memory 表示带认识论状态的主观经历；Dragon v0.1 不实现这两套认知能力。DragonEvent 或 Interaction Record 不能伪装成 NPC/Dragon Memory。

### NPC Relationship

不能直接复用。NPC Relationship 目前关注 Familiarity、Trust、Attitude；Dragon Bond 还必须表达 Fear、Bond、Taming State、Riding Unlock、Physical Requirement 和 Species Milestone。两者可以共享 Grounded Evidence、Anti-Farming、Bounds、Idempotency 与 Read/Write Separation 原则，但必须保持独立 Contract 和 Store/Table。

### Interaction Event

可以复用稳定 Event ID、来源归属、Grounded Evidence 和幂等思想，但不能直接把 NPC Dialogue Event 当作 Dragon Interaction Contract。Dragon 需要行为语义、Dragon ID、环境条件、物品/距离/威胁信息和 Dragon 当前行为；未来应建立独立、最小的 Dragon Interaction Event。

### Persistent Mutation

兼容现有 `Interpret → Validate → Preview/Plan → Commit` 安全思想。Dragon Runtime 未来可以隐藏普通玩家不需要看到的内部评估，但服务端仍必须重新验证并控制 Mutation Allowlist。

本设计没有要求修改任何现有 Frozen NPC、Memory、Relationship、Action、API 或 Frontend Contract。

## 13. Database Implications

Domain Entity 是业务概念边界，不代表下一阶段必须与 Database Table 进行 1:1 映射。Database Schema Design 可以在不破坏领域职责、唯一性、证据链和 Source of Truth 的前提下合并或拆分持久化结构。

`StructuredDragonInteraction` 是一次解释过程中的瞬时 Value Object，默认不视为必须持久化的实体。`DragonInteractionRecord` 是否需要独立持久化，必须在下一阶段根据 Idempotency、Anti-Farming 与 Audit 的实际查询需求判断；如果 `DragonEvent` 已能完整承担这些职责，就不应重复建模。

下一阶段 Database Schema 至少需要支持以下领域数据边界；列表中的名称是候选持久化边界，不是已经确定的 Table 清单：

1. **dragon_archetypes**：DragonArchetype 规则与龙种 Milestone 配置。
2. **dragons**：IndividualDragon 稳定身份，外键指向 Archetype，可选关联来源 Egg。
3. **dragon_runtime_states**：与 Dragon 一对一的 Location、Health、Energy、Hunger、Alertness、Behavior。
4. **player_dragon_bonds**：Player × Dragon 唯一关系、Taming State、Riding Unlock 和最近重大事件。
5. **dragon_eggs**：获得、孵化状态、未知 Archetype 和孵化后 Dragon 关联。
6. **dragon_events**：Grounded Significant Event、Milestone Evidence 与 Audit。
7. **Dragon Interaction Processing Data（待定）**：如果 DragonEvent 不足以支持幂等与 Anti-Farming Recent History，再评估独立 `dragon_interaction_records`；它不等同完整 Event Sourcing 或 Memory Store。

必须预留的关键约束：

- `dragons.dragon_id`、`dragon_archetypes.archetype_id`、`dragon_eggs.egg_id`、`dragon_events.event_id` 唯一。
- `dragon_runtime_states.dragon_id` 一对一且引用现有 Dragon。
- `UNIQUE(player_id, dragon_id)` 用于 PlayerDragonBond。
- Bond 数值范围使用数据库 Check Constraint 与 Domain Validation 双重保护。
- `origin_egg_id` 与 `hatched_dragon_id` 必须一对一一致。
- Event 的来源幂等键必须阻止同一 Interaction 重复应用。
- 外键必须连接 Player、Location、Dragon、Archetype 和 Grounded Event。
- Hatching 涉及 Egg、Dragon、Runtime State、Bond 与 Event 的多实体一致性，数据库阶段必须定义事务边界。

本节只描述数据库必须支持的领域事实，不选择 PostgreSQL、ORM、Migration Tool、JSON Column 或具体索引方案。

## 14. Multimodal Compatibility

未来 Dragon Encounter / Riding Event 可以成为 Visual Trigger：

```text
Grounded Dragon State
+ Location
+ Weather
+ Player POV
+ Validated Event
→ Visual Prompt Builder
→ Image Provider
```

视觉内容只能消费 Grounded State，不能反向创建或修改 Dragon、Bond、Location、Weather 或 Event。生成图片不是 World Truth，也不能作为 Trust、Taming 或 Riding 的证据，除非未来有独立受控验证流程。

本阶段不实现 Visual Prompt、Image Provider、视频、骑龙动画或多模态存储。

## 15. Explicit Non-goals

v0.1 明确不设计或实现：

- 龙繁殖与遗传；
- 龙技能树、装备与经济；
- 复杂战斗与复杂死亡机制；
- 完整 Dragon Agent；
- 完整 Dragon Knowledge、Dialogue 或 Memory Retriever；
- Dynamic Dragon Archetype Generation；
- 图片、视频与骑龙动画；
- 完整 Growth Runtime；
- 完整 De-taming Runtime；
- Database、ORM、Migration、API、Frontend 或 Evaluator 实现。

## 16. Demo Boundary

Dragon v0.1 的主要垂直 Demo 目标保持为：

```text
Player enters Stormcliff
→ encounters Stormwing #001
→ peaceful / dangerous interactions
→ familiarity / trust / fear evolve
→ tolerant
→ significant shared event
→ bonding
→ Stormwing-specific milestone
→ tamed
→ dragon accepts mount
→ riding_unlocked
→ player rides Stormwing
→ future first-person visual generation
```

本设计只为这条链路提供稳定 Entity、Evidence 与 State Boundary，不表示上述 Runtime 已经实现。

## 17. Open Questions

以下问题必须在 Database Schema 或后续 Runtime Design 前确认：

1. `archetype_id`、`dragon_id` 与 `egg_id` 的最终 ID 命名规范是什么？Demo 中 “Stormwing #001” 是显示名还是稳定 ID？
2. 六个初始 Archetype 的 `size_class`、`diet`、`intelligence_level`、`rarity`、`taming_difficulty`、`rideable` 和具体 Taming Milestone 分别是什么？
3. `health`、`energy`、`hunger`、`alertness` 使用什么量表、边界和恢复/衰减规则？
4. `sex` 是否允许 `unknown`，最终受控枚举是什么？
5. Age Stage 的推进依据是世界时间、事件、照料条件还是组合规则？每个 Archetype 是否有不同成熟速度？
6. 多玩家场景中，一条 Dragon 是否能同时拥有多个 Bond、多个 Tamed 关系或多个 Riding Authorization？冲突如何处理？
7. Species-specific Milestone 使用统一 Event Type + `milestone_key`，还是独立受控 Milestone 表？
8. Anti-Farming 的短期窗口、衰减级别和 Interaction Fingerprint 如何定义？
9. De-taming 的回退阈值、重大背叛证据和 `dragon_leaves_player` 行为由哪个 Runtime 负责？
10. Dragon Egg 的 Incubation State、Progress 量表、环境要求、失败策略和未知 Archetype 鉴定时点是什么？
11. 数据库成为 Source of Truth 后，现有 JSON World State 如何只读迁移或同步，避免 Dragon Location 出现双写？
12. Wild Dragon 首次 Encounter 时由哪个受控系统创建或 Resolve Individual Identity，如何避免重复生成同一条 Dragon？
13. Dragon Interaction Evaluator 的 Mutation Allowlist、Evidence Contract 和服务端 Revalidation 边界如何定义？
14. Visual Trigger 只保存 Event Reference，还是需要保存可复现的 Grounded Visual Snapshot？

这些问题未确认前，不应进入完整 Dragon Runtime 或 Database Schema 实现。
