# Dragon World — Dragon Bond / Taming Design v0.1

## 0. Status and Scope

本文件定义 D4 的 Dragon Interaction、PlayerDragonBond、Taming 与 Riding
边界。D4-A 是 **Design + Existing Domain Audit Only**：不实现 Runtime、API、
Frontend 或数据库变更。

正式产品原则：

```text
Encountering Dragon != Bond
Bond               != Tamed
Tamed              != Riding Unlocked
Player Claim       != World Truth
```

D4 v0.1 允许玩家继续用自然语言与已经 committed 的 Dragon 互动；D2 解释玩家
尝试，D4 的确定性 Runtime 决定 Dragon Reaction、关系变化和是否满足 Taming
条件。LLM 不拥有 Bond、Taming 或 Riding 的决定权。

## 1. Existing Dragon / Bond Domain Audit

### 1.1 `dragons`

现有 `dragons` 同时保存 Individual Dragon 与当前 Runtime State：

| Field | D4 含义 |
| --- | --- |
| `dragon_id` | 单列 Primary Key，正式 Dragon 身份 |
| `archetype_id` | 宽泛 Runtime Baseline，不是 Species Taxonomy |
| `name` | 玩家可见专名 |
| `age_stage` | `hatchling / juvenile / young_adult / adult` |
| `appearance` | JSONB 玩家可见外观 |
| `temperament_traits` | JSONB Array；叙事性 Temperament Context |
| `current_location` | Dragon 当前正式位置 |
| `health_state` | 当前健康状态 |
| `energy / hunger / alertness` | 当前 Runtime 数值 |
| `behavior_state` | `resting / feeding / wandering / watching / avoiding / threatening / attacking / following / flying` |
| `taming_state` | `wild / tolerant / bonding / tamed` |

`ck_dragons_taming_state` 已约束四个合法状态。当前 Frozen PostgreSQL Schema
采用单玩家 v0.1 决策：`dragons.taming_state` 是正式 Taming State Source of
Truth。D4 不在 `player_dragon_bonds` 再保存一份 Taming State。

### 1.2 `player_dragon_bonds`

当前真实字段：

| Field | Constraint / Meaning |
| --- | --- |
| `player_id` | Composite PK；FK → `players.player_id`，ON DELETE RESTRICT |
| `dragon_id` | Composite PK；FK → `dragons.dragon_id`，ON DELETE RESTRICT |
| `familiarity` | NOT NULL；CHECK `0..5` |
| `trust` | NOT NULL；CHECK `-3..5` |
| `fear` | NOT NULL；CHECK `0..5` |
| `bond` | NOT NULL；CHECK `0..5` |
| `riding_unlocked` | NOT NULL，DEFAULT `false` |
| `last_significant_event_id` | Nullable FK → `dragon_events.event_id`，ON DELETE RESTRICT |

Composite Primary Key `(player_id, dragon_id)` 保证一个 Player 与一条 Dragon
只有一份正式 Bond。除 `riding_unlocked=false` 外，数值没有业务默认值；Runtime
创建 Bond 时必须明确写出所有四个数值。

Riding Authorization 当前唯一存放在
`player_dragon_bonds.riding_unlocked`。现有 `has_rideable_dragon()` 已同时检查：

```text
PlayerDragonBond.riding_unlocked = true
AND dragons.taming_state = tamed
```

### 1.3 `dragon_events`

`dragon_events` 是 append-only Grounded Significant Event History。它已有：

- `event_id` Primary Key；
- Dragon、Player、source Interaction Event 外键；
- `world_day / world_hour / location_id`；
- `milestone_key`；
- JSONB `event_payload`；
- UNIQUE `(dragon_id, source_interaction_event_id, event_type)`。

现有 CHECK 已允许 D4 所需的重要事件：

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

因此 D4 不新增通用 `dragon_interaction` 或 `dragon_bond_changed` Event Type。
普通尝试与 Resolution 写入其既有 source `interaction_events.event_payload`；只有
通过 Grounding 的重大事件才写 `dragon_events`。

### 1.4 Interaction Events, D2, D3 and API Read Path

- D2 Structured Action 已提供 `action_family / action / target / destination /
  direction / intent / method / explicit_goal / needs_clarification`，足以把 Dragon
  相关自然语言尝试路由到 D4；D4 不创建第二套通用 Action Interpreter。
- D2-C 已用 `domain_route=dragon` 隔离 Dragon Domain Mutation。
- `interaction_events` 是每次 Free World Action 的 source event；其 JSONB
  `event_payload` 可保存 D4 Resolution、处理指纹与 Grounded Commit 结果。
- D3 已提供 committed Dragon 查询、同地点读取、稳定 Dragon Event 来源链和
  PostgreSQL 原子提交范式。
- `/api/world.nearby_dragons` 只读取 PostgreSQL 中与 Player 同 Location 的正式
  Dragon，可作为 D4 Target Grounding 和 Frontend Read-back 的基础。

现有 Persistence Adapter 尚未提供通用 Bond Read/Write 或 D4 Commit；D4-C 只需
增加薄的、具体用途的方法，不需要 Repository、Manager 或新抽象层。

### 1.5 Current World Baseline

只读审计时正式状态为：

```text
Dragon count: 1
Kael dragon_id: dragon_909cf832bd2e5a3599a191bc8cb52edb
Kael location: stormcliff
Kael behavior_state: watching
Kael taming_state: wild
Kael first encounter event: present
PlayerDragonBond rows: 0
```

Kael 是 committed World Truth，但尚未与 Player 建立 Bond。

### 1.6 Schema Decision

**D4 v0.1 不需要 Schema 修改。**

现有三张表足以承载：

- `player_dragon_bonds`：Player × Dragon 当前关系和 Riding Authorization；
- `dragons`：单玩家 v0.1 Taming 与 Dragon Runtime Current State；
- `dragon_events`：重大 Grounded Evidence 与 Idempotency；现有
  `milestone_key` 字段不作为 D4 v0.1 Taming 硬门槛；
- `interaction_events.event_payload`：所有普通 D4 尝试和 Resolution History。

不创建 Dragon Interaction Table、Bond Table v2、Taming Table 或 Event Table。
Multi-player Taming Ownership 继续是 Future Schema Question，不在 D4 v0.1 解决。

## 2. D4 Product Goal and Runtime Flow

目标链路：

```text
Player Natural Language
→ D2 Action Interpreter
→ D2 Structured Action
→ D2-C domain_route = dragon
→ Ground committed Dragon target
→ D4 Deterministic Interaction Resolution
→ Validated Mutation Plan
→ Atomic PostgreSQL Commit
→ Grounded Dragon Reaction Presentation
→ /api/world Read-back
```

D4 读取：Player Action、Dragon State、Archetype、Temperament Context、现有 Bond
和近期 D4 Interaction History。D4 输出 Grounded Reaction 与受控关系效果；长期
合理互动可以逐渐产生 `wild → tolerant → bonding → tamed`。

## 3. Eligible Dragon Interaction and Target Boundary

D4 v0.1 优先支持：

- `observe`
- `approach`
- `wait`
- `retreat`
- `offer`（例如放下食物）
- `touch`
- `threaten`
- `ride_attempt`
- `other`

这些是 D4 对既有 Structured Action 的轻量 deterministic projection，不是新
Interpreter Contract。D4 使用 D2 的 `action_family / action / target / intent /
method` 判断类型；无法安全归类时使用 `other` 并采取保守结果。

目标必须满足：

1. `dragon_id` 对应已 committed 的 PostgreSQL Dragon；
2. 名称 Target 必须唯一 resolve 到正式 Dragon；
3. 需要物理接触的 Action 要求 Player 与 Dragon 位于同一正式 Location；
4. “这条龙”只有在当前位置恰好有一个 eligible Dragon 时才能 resolve；
5. 多个候选或未知名称必须 fail closed；
6. 不凭名称或 Player Claim 创建 Dragon，不自动移动或传送 Dragon。

远距离 `observe` 仍必须基于当前 World Context 中可见的 committed Dragon；跨
Location 的 approach、offer、touch、threaten 和 ride 均 blocked。

## 4. Dragon Interaction Resolution Contract

D4-B 最小内部 Contract：

```json
{
  "source_interaction_event_id": "...",
  "dragon_id": "...",
  "status": "success | partial | blocked",
  "interaction_type": "observe | approach | wait | retreat | offer | touch | threaten | ride_attempt | other",
  "dragon_reaction": "calm | curious | wary | defensive | accepting | retreating",
  "relationship_effect": "positive | neutral | negative",
  "reason_code": "...",
  "state_changes": {
    "player_dragon_bond": null,
    "dragon": null
  },
  "significant_event": null
}
```

当存在 Mutation 时，`state_changes` 只保存服务端计算出的 before/after 值：

```json
{
  "player_dragon_bond": {
    "before": null,
    "after": {
      "familiarity": 1,
      "trust": 1,
      "fear": 0,
      "bond": 0,
      "riding_unlocked": false
    }
  },
  "dragon": {
    "taming_state": {"from": "wild", "to": "tolerant"}
  }
}
```

`significant_event` 仅能引用现有受控 Event Type。Frontend 不提交 delta、
after state、Taming State 或 Event；
这些均由服务端重新计算。数值变化默认属于 hidden Runtime / Developer 信息，
普通玩家只看到 Grounded Reaction，不直接看到刷分数字。

## 5. Deterministic Resolution and Personality Use

正式状态变化必须 deterministic。判定优先级：

1. Target / Location / committed Dragon gate；
2. Dragon `taming_state` 与现有 PlayerDragonBond；
3. Dragon `behavior_state`、health、energy、hunger、alertness；
4. Authored `archetype_id` baseline；
5. D2 Interaction Type、intent 和 method；
6. 近期 D4 Resolution History 与 Anti-Farming；
7. 数值 Threshold + 不同 Grounded Positive Interaction Categories。

Personality 的最小使用方式：

- `watching / avoiding`：快速靠近、强行触碰倾向 wary/retreating；保持距离、等待
  或放下食物后退更可能 neutral/positive；
- `threatening / attacking`：approach、touch、ride fail closed，通常 defensive；
- `feeding / resting`：是否接受 offer/approach 仍受 Familiarity、Trust 和方法约束；
- Archetype 只提供宽泛行为 baseline，不定义固定 Species 性格；
- `temperament_traits` 是 committed Narrative Context，可影响安全模板措辞，但
  v0.1 不对自由文本做关键词 NLP，也不让它直接产生数值 delta。

因此 Kael 的 `watching + wild + no bond` 足以确定：突然冲近是 defensive 倾向，
保持距离放下食物是更安全的 positive 候选。无需 Personality Framework、Trait
Ontology 或第二个 LLM Judge。

## 6. Bond Progression

### 6.1 Dimension Semantics

- Familiarity：是否逐渐熟悉 Player，不等于喜欢或信任；
- Trust：是否认为 Player 可靠且安全；
- Fear：是否畏惧 Player，不能替代 Trust；
- Bond：长期情感羁绊，只能由多次不同类别且 Grounded 的正向互动推进。

所有值在 Runtime 计算后必须通过 Domain Bounds，并由数据库 CHECK 二次保护。
越界时 clamp 到合法边界或 fail closed；客户端不能提交数值。

### 6.2 Grounded Positive Interaction Categories

D4 v0.1 只使用以下五类确定性正向证据：

| Category | Existing grounded semantics |
| --- | --- |
| `food` | `dragon_accepts_food` |
| `close_presence` | `dragon_allows_close_presence` |
| `touch` | `dragon_allows_touch` |
| `care_rescue` | `player_heals_dragon` 或 `player_rescues_dragon` |
| `shared_danger` | `shared_danger_survived` |

Category 由 Runtime 根据已验证的 `interaction_type`、Dragon Reaction 和正式
Dragon Event Type 确定。LLM 不得输出或决定“这是重大事件/正向类别”，玩家叙述
也不能直接计入 Category。同一 source Interaction 最多贡献一次对应 Category。

### 6.3 Initial Bond

- 无 Bond 的 neutral observe/wait 不创建 Row；
- 第一次被 Dragon 接受的 Grounded Positive Interaction 可以原子创建：
  `familiarity=1, trust=1, fear=0, bond=0, riding_unlocked=false`；
- 第一次 Grounded Threat/Forced Contact 可以为保留真实后果创建负向关系状态，
  但具体初始 delta 由 D4-B 决定；
- Player Claim、被 blocked 的跨地点 Action、纯叙述愿望均不创建 Bond。

### 6.4 Effect Baseline

| Interaction | Grounded Result | Typical Effect |
| --- | --- | --- |
| 远距离 observe / wait | calm/wary | neutral；通常不改数值 |
| respect boundary / retreat | calm/retreating | neutral；不凭空增加 Bond |
| accepted offer | accepting | Familiarity +1、Trust +1；Bond 不直接增加 |
| accepted careful approach | curious/accepting | Familiarity +1；满足条件时 Trust +1 |
| accepted touch | accepting | 仅在已有容忍证据时允许；可 Trust +1、Bond +1 |
| heal / rescue / shared danger | Grounded significant event | 可 Trust +1、Bond +1 |
| threaten / rush / forced touch | defensive/retreating | Trust 可降低、Fear 可增加、已有 Bond 可降低；具体 delta 留给 D4-B |
| ride attempt without authorization | blocked | 不授予 Riding，不因声明改变状态 |

表中是 v0.1 最大单次效果，不是每次保证值。Runtime 必须先检查 Dragon 当前
行为、方法、历史和前置证据。

所有 Negative Effect 必须 clamp 在现有 Schema 合法范围：Familiarity `0..5`、
Trust `-3..5`、Fear `0..5`、Bond `0..5`。D4-A 不冻结具体负向 delta。

### 6.5 Anti-Farming and Idempotency

每次 D4 处理使用：

```text
source_interaction_event_id + player_id + dragon_id
```

作为幂等来源。同一 source retry 返回同一 Resolution，不重复 Mutation。

不使用时间 Cooldown。连续重复链由以下键确定：

```text
player_id + dragon_id + consecutive same interaction_type
```

Positive Interaction 的正式衰减：

```text
first meaningful occurrence → full eligible effect
second consecutive same type → at most Familiarity-only effect
third and later same type     → zero positive relationship gain
```

一旦发生另一种有效 Interaction Type，连续重复链结束；之后再次执行原类型可作为
新的连续链评估。第二次和后续重复不再写同类 Significant Event。Anti-Farming
防止刷 Bond，不抹除威胁行为的真实负面后果，也不建立 Timer、Cooldown 或
Anti-Farm Framework。

## 7. Taming State Machine

沿用 Frozen 四态：

```text
wild → tolerant → bonding → tamed
```

### 7.1 `tolerant`

必须同时满足：

- Familiarity ≥ 2；
- Trust ≥ 1；
- Fear ≤ 2；
- 至少 1 类 Grounded Positive Interaction Category。

### 7.2 `bonding`

必须同时满足：

- Familiarity ≥ 3；
- Trust ≥ 2；
- Bond ≥ 1；
- Fear ≤ 1；
- 至少 2 类不同的 Grounded Positive Interaction Category。

### 7.3 `tamed`

必须同时满足：

- Familiarity ≥ 4；
- Trust ≥ 3；
- Bond ≥ 2；
- Fear ≤ 1；
- 至少 3 类不同的 Grounded Positive Interaction Category；
- 本次 transition 原子写入 `dragon_tamed` Event。

D4 v0.1 明确不把 Archetype Milestone 作为 Taming Gate。当前三个 Archetype
没有正式 Milestone Contract，也不新增 Milestone Registry、Taming Config 或
Archetype Taming Framework。Archetype 只影响 approach、threat、offer food、
touch 等 Interaction Resolution 的安全性和 reaction tendency。

数值 Threshold 与类别数量必须同时成立，因此一次喂食永远不能直接从 wild
进入 tamed。玩家或 LLM 声称某类别已发生，也不能替代 Grounded Evidence。

D4 v0.1 不实现完整 De-taming；但负向 Interaction 仍可以降低当前 Bond 数值。
未来状态回退需要独立 Player-facing 需求和受控设计，不能顺手加入。

## 8. Riding Boundary

Riding 与 Taming 分离。任一条件不满足，`ride_attempt` 都 blocked：

- `dragons.taming_state = tamed`；
- `player_dragon_bonds.bond >= 3`；
- `trust >= 4`；
- `fear <= 1`；
- 成熟 `age_stage`；
- Grounded `dragon_accepts_mount` Event；
- Authored Archetype Physical Eligibility。

当前 Riding Authorization 没有充分的 Grounded Runtime Rule，因此 D4 v0.1
主闭环止于 Dragon Tamed，并对 Riding Unlock **fail closed**：
`riding_unlocked` 默认且始终保持 `false`。这不是 Bond/Taming 的 Schema
Blocker。D4 不修改 Archetype Registry、Schema 或 Riding Contract，也不因
Player 说“我要骑 Kael”、Dragon 已 tamed 或数值达标而自动解锁 Riding。

Riding Unlock 留给后续独立设计；上面的条件仅是既有安全边界，不是 D4 v0.1
要实现的授权流程。

`first_shared_flight` 只能发生在 Riding 已正式授权之后，不能反向作为授权证据。

## 9. Dragon Event and Atomic Persistence Strategy

每次正式 D4 Action 先已有一个 D2 source Interaction Event。建议原子流程：

```text
Lock source Interaction Event
→ verify Player / Dragon / Location
→ read and lock PlayerDragonBond if present
→ recompute D4 Resolution server-side
→ update source event payload with D4 Resolution
→ insert/update PlayerDragonBond when allowed
→ update dragons.behavior_state / taming_state when allowed
→ append Significant DragonEvent when warranted
→ set last_significant_event_id
→ read-back
→ commit
```

任一步失败全部 Rollback。Retry 先按 source event 检查已提交 Resolution，并返回
原结果。不得发生 Partial Commit、JSON Write 或 PostgreSQL + JSON Dual Write。

所有普通互动保存在 Interaction Event payload；DragonEvent 只记录既有 CHECK
允许的重大事实。`last_significant_event_id` 只指向本次真正创建/复用的正式
DragonEvent，不指向普通尝试。

## 10. World Truth and Narrative Boundary

以下内容都不是 World Truth：

- “Kael 已经被我驯服了”；
- “Kael 完全信任我”；
- “我以前救过它”；
- LLM 生成的 Reaction；
- Frontend 提交的 Bond 数字或状态。

只有 committed Dragon、现有 Bond、真实 Location、被 Runtime 验证的本次行为与
Grounded DragonEvent 可以参与正式 Mutation。

Presentation 在 Resolution 之后可以使用安全模板，例如：

> Kael 没有靠近，只是警惕地观察你。

模板只能叙述已确定的 `dragon_reaction`，不能自行增加 Bond、伤害、Taming、
Ownership 或 Riding。未来若加入 LLM Reaction Narration，也只能消费 committed
Resolution，不能反向决定状态。

## 11. Initial 12 Cases

| Case | Initial State / Input | Expected D4 Result |
| --- | --- | --- |
| 1 | Kael wild/no bond；“我远远观察 Kael。” | allowed；wary/calm；neutral；不创建 Bond |
| 2 | “我慢慢靠近 Kael。” | cautious partial；根据 watching/wild 保持距离或允许有限靠近，不保证正向变化 |
| 3 | “我把食物放下，然后后退。” | reasonable positive；accepting 候选；可创建初始 Bond 与 `dragon_accepts_food` |
| 4 | “我突然冲过去抱住 Kael。” | defensive/retreating；negative；Trust/Fear 受控变化，不自动触碰成功 |
| 5 | wild Kael；“我要骑 Kael。” | blocked；`dragon_riding_not_unlocked`；无 Riding/Taming Mutation |
| 6 | 连续重复同一喂食动作 | full → reduced → zero positive effect；不得无限刷 Bond/Event |
| 7 | 第一次 Grounded Positive Interaction | 原子创建 `(player_001, Kael)` Bond：`1/1/0/0/false` |
| 8 | 多次不同且合理成功互动 | Familiarity/Trust/Bond 按规则渐进；可进入 tolerant/bonding，不跳级 |
| 9 | “Kael 已经被我驯服了。” | Player Claim；neutral/blocked；不得改变 Bond 或 Taming State |
| 10 | bonding 状态下数值与至少三类 Grounded Positive Interaction 全部满足 | `bonding → tamed`；原子写 `dragon_tamed` |
| 11 | tamed 但 Riding Evidence/Authorization 不满足 | ride blocked；`riding_unlocked` 保持 false |
| 12 | Player 不在 Stormcliff，却尝试靠近/触碰 Kael | blocked；`dragon_not_at_player_location`；零 Mutation |

## 12. Persistence and Mutation Allowlist

D4 v0.1 唯一允许写入：

- `interaction_events.event_payload` 中本次 D4 Resolution；
- `player_dragon_bonds` 四维关系、`riding_unlocked`（当前 fail closed）及
  `last_significant_event_id`；
- `dragons.behavior_state` 与 `dragons.taming_state`；
- append-only `dragon_events` 既有受控 Event Type。

D4 不修改 Player Location/Goals/Inventory、NPC/Memory/Relationship、Dragon
Identity/Appearance/Archetype、Ownership 或 Egg。PostgreSQL 继续是唯一 Mutable
Runtime Source of Truth。

## 13. Complexity Budget and Explicit Non-goals

D4 v0.1 不新增：

- Dragon Agent / Multi-Agent / LangGraph；
- Emotion Engine / Behavior Tree Framework；
- Dragon Manager / Relationship Manager / Bond Manager；
- Taming Framework / Pet System / Training Skill Tree；
- Combat System / Quest System / Event Bus；
- Dragon Interaction Table / Bond Store v2；
- Repository / UnitOfWork / Workflow Framework；
- Translation Runtime 或第二个 LLM Judge。

顶层架构仍是既有 Interaction、World Orchestration、World Rules、NPC Runtime、
Dragon Runtime、PostgreSQL 与 Presentation 七层。D4 只增加一个轻量 Dragon
Domain Resolver 和必要的薄 Persistence 方法，不增加 Architecture Layer。

## 14. D4-B to D4-E Responsibilities

### D4-B — Dragon Interaction Resolution

- 复用 D2 Structured Action；
- Ground committed Dragon 与 Location；
- deterministic interaction type / reaction / relationship effect；
- Threshold、Grounded Category、Personality Context、Anti-Farming 与 Taming plan；
- read-only Resolution / Mutation Plan；
- 不写数据库。

### D4-C — Bond / Taming Persistence

- 增加最小具体 Persistence Read/Commit 方法；
- source Interaction Event 幂等；
- Bond 创建/更新、Dragon state、Significant Event 同事务；
- Rollback、Read-back、Retry；
- 不新增 Schema 或抽象框架。

### D4-D — Browser Runtime Integration

- 把 D2 `domain_route=dragon` 接入 D4-B/C；
- 复用 `/api/action/execute`、现有 nearby Dragon UI 与 `/api/world` Read-back；
- 展示 Grounded Reaction；
- 不暴露可伪造 delta，不创建 Button-only Gameplay。

### D4-E — E2E + Final Freeze

- 验证 Kael Target/Location、正向/负向/重复行为、Bond 渐进、Taming Gate、
  Riding Block、Restart Persistence；
- 确认无 NPC/Player/World 意外 Mutation；
- 完成 D4 v0.1 Final Freeze。
