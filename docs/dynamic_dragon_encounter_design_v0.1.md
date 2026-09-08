# D3-A — Dynamic Dragon Encounter Design v0.1

Status: FROZEN
Scope: Design + Existing Dragon Domain Audit Only

## 1. Product Goal

D3 让已经完成 D2 行动判定的玩家探索，有机会产生连续、可追溯的动态龙遭遇：

```text
Player Exploration / Search
→ D2 Structured Action + Grounded Resolution
→ D3 Encounter Eligibility
→ Contextual Encounter Decision
→ Existing Dragon Reuse or New Dragon Candidate
→ Dragon Grounding
→ Controlled PostgreSQL Commit
→ Grounded Encounter Presentation
```

核心原则：

- Player exploration can lead to dynamic dragon encounters.
- Searching for a dragon does not guarantee an encounter.
- LLM-generated Dragon is only a Candidate, not World Truth.
- World Skeleton is Authored; Dragon Variation is AI-generated.
- World continuity takes priority over generating another Dragon.
- PostgreSQL remains the only mutable Runtime Source of Truth.

D3 v0.1 只负责 Dragon Encounter 与 Dragon Existence。它不实现 Bond、Taming、Ownership、Riding Unlock、Combat Outcome、Permanent Dynamic Location 或 World Tick。

## 2. Existing Dragon Domain Audit

### 2.1 PostgreSQL / ORM capability

现有 11-table Schema 已包含四张 Dragon Domain Table。

#### `dragons`

现有字段：

- `dragon_id`
- `archetype_id`
- `name`（nullable）
- `sex`（nullable）
- `age_stage`
- `appearance`（JSONB object）
- `temperament_traits`（JSONB array）
- `current_location`
- `health_state`
- `energy`
- `hunger`
- `alertness`
- `behavior_state`
- `taming_state`

现有 CHECK 已限制：

- `age_stage`: `hatchling / juvenile / young_adult / adult`
- `behavior_state`: `resting / feeding / wandering / watching / avoiding / threatening / attacking / following / flying`
- `taming_state`: `wild / tolerant / bonding / tamed`
- `appearance` 必须是 JSON object
- `temperament_traits` 必须是 JSON array

这些字段足以表达 D3 新发现 Dragon 的稳定身份、外观差异、当前位置和最小行为状态。

#### `dragon_events`

现有字段足以记录 `dragon_first_encounter`，包括：

- stable `event_id`
- `dragon_id`
- optional `player_id`
- optional `source_interaction_event_id`
- world day/hour/location
- optional `milestone_key`
- JSONB `event_payload`
- technical `recorded_at`

`UNIQUE(dragon_id, source_interaction_event_id, event_type)` 可以阻止同一来源行动对同一 Dragon 重复建立同类 Grounded Event。

#### `player_dragon_bonds`

已有 Player × Dragon Composite PK、Bond 数值约束和 `riding_unlocked`。D3 只读取它来避免错误宣称 Ownership/Riding，不在 Encounter 阶段创建或修改 Bond。

#### `dragon_eggs`

已有 Egg Acquisition、Incubation 与 Hatching Link。D3 不处理 Egg 获取或孵化。

### 2.2 Interaction history

`interaction_events.event_type` 不是封闭 Enum，非 NPC Event 可以使用 nullable NPC fields 和 JSONB `event_payload`。因此 D3 可以追加：

```text
event_type = dragon_encounter_decision
event_payload = {
  source_action_event_id,
  outcome,
  context_factors,
  existing_dragon_id,
  requested_new_candidate
}
```

这使没有具体 `dragon_id` 的 evaluated `none` / `trace` 也能形成 Recent Encounter History，而不污染 `dragon_events`。D3 不更新 D2 已经写入的 Event；历史继续保持 Append-only。

### 2.3 Current implementation capability

当前实现状态：

- `PostgresPersistenceAdapter` 只有 Dragon/Bond 相关只读方法 `has_rideable_dragon()`。
- 尚无 `get_dragon`、`list_dragons_at_location`、Dragon Candidate Commit 或 Dragon Event insert 等薄层方法。
- 尚无 Dragon Encounter Runtime、Encounter Decision、Dragon Grounding 或 Dragon creation entry。
- 现有 D2 只识别骑龙意图并 route 到 Dragon Domain，不决定 Encounter。
- `/api/world` 当前不公开 Dragon payload。
- 当前没有已实现的 Dragon Rules 模块；可复用的是 Frozen Domain Invariants、ORM CHECK、Location Resolve、Interaction Event、PostgreSQL Transaction 和 D2 Domain Routing 原则。
- 当前 PostgreSQL 数据为：`dragons=0`、`dragon_events=0`、`player_dragon_bonds=0`、`dragon_eggs=0`。

### 2.4 Configuration audit

`world_seed.json` 已提供：

- authored Location ID、name、type、description、connections
- world day/hour/weather
- `dragons_exist=true`
- current global state values

它足以提供 D3 v0.1 的最小 Location narrative/ecology context，但不是 Ecology Engine，也不是 mutable Dragon Store。

当前代码库没有已落地的 Dragon Archetype Registry。由于 `dragons.archetype_id` 为 NOT NULL，D3-C 在允许创建新 Dragon 前，必须先建立或确认一个最小 Git-tracked authored Archetype Registry。Archetype 仍是配置，不是新数据库表；LLM 不得发明无法 Resolve 的 `archetype_id`。

### 2.5 Schema conclusion

D3 v0.1 可以在不修改 Schema 的情况下完成：

- 新 Dragon 写入现有 `dragons`。
- 首次正式遭遇写入现有 `dragon_events`。
- `none` / `trace` 与 Encounter Decision history 写入现有 `interaction_events.event_payload`。
- 来源幂等使用 deterministic decision event ID、Interaction Event PK 和 Dragon Event unique constraint。

D3-B/C 只应按需增加薄层 Persistence 方法和最小静态 Archetype Configuration，不创建 Migration、Table 或新 Persistence Framework。

## 3. Encounter Input

D3-B 的 `EncounterContext` 是瞬时 Value Object，不持久化为新实体。输入只组合已有事实：

- `player_id`
- D2 source `interaction_event_id`
- current PostgreSQL `player_states.current_location`
- complete D2 `structured_action`
- `action_family`
- `target`
- `destination`
- `direction`
- `intent`
- D2 resolution `status / effect_scope / domain_route / reason_code`
- current authored Location `id / type / description / connections`
- existing PostgreSQL Dragons at the relevant Location
- recent `dragon_encounter_decision` Interaction Events
- current world day/hour/weather only when already present in Runtime Context

`world_seed.json` 的 time/weather 在当前版本只是已有上下文；D3 不使其动态化，也不新增 Weather System、Environment State 或 World Tick。

## 4. Eligible Player Actions

### 4.1 Primary eligible families

- `explore`
- `observe_search`

### 4.2 Conditionally eligible families

- `travel`: 只有行动带明确 Dragon-related search/observation intent，且 D2 没有 blocked。
- `interact` / `other`: 只有目标或意图明确与寻找、观察、接近 Dragon 或 Dragon trace 有关；普通 NPC interaction 不触发。

Dragon-related intent 可以包括寻找龙、观察龙、接近龙、寻找龙巢或追踪明确龙迹。骑龙意图本身不是 Encounter Trigger；骑不存在的龙已由 D2 blocked，不能反向生成一条龙。

### 4.3 Ineligible by default

- `rest_wait`
- `create_trade`
- ordinary NPC dialogue
- goal add/remove
- D2 `blocked` 或 `needs_clarification`
- 与 Dragon 无关的普通行动

不符合 Eligibility Gate 的行动直接得到 transient `none`，不调用概率决策、不创建 Dragon，也不需要追加 D3 Decision Event。

## 5. Encounter Outcome

D3 v0.1 只允许四种 Outcome：

| Outcome | Grounded meaning | Dragon persistence |
| --- | --- | --- |
| `none` | 本次合格探索没有龙相关发现 | 不创建 Dragon；已实际评估的结果可记录 Decision Event |
| `trace` | 发现巢痕、脚印、鳞片痕迹、远处叫声等非个体证据 | 不要求且默认不创建 Dragon |
| `sighting` | 玩家看见一条可稳定指认的正式 Dragon | 必须返回已存在或先 Commit 的 `dragon_id` |
| `direct_encounter` | 玩家与一条正式 Dragon 进入可继续交互的同场遭遇 | 必须返回已存在或先 Commit 的 `dragon_id` |

约束：

- `trace` 不能包含 Dragon name、稳定个体外观或确定数量，除非已有 Dragon State 支持。
- `sighting` 与 `direct_encounter` 不能引用 Candidate ID。
- `direct_encounter` 不表示 Interaction 成功、Dragon 友善、Bond 建立或 Taming 开始。

### 5.1 Provisional and Final Encounter

当一次 Decision 需要尚不存在的新 Dragon 时，D3-B 产生的 `sighting` 或 `direct_encounter` 只能是 **Provisional Encounter Decision**，不能立即成为 Player-visible 结果或 World Truth。

正式顺序：

```text
D3-B provisional sighting / direct_encounter
→ Look up eligible existing Dragon
  → Existing Dragon found
    → Bind committed dragon_id
    → Finalize Encounter
  → No eligible Dragon
    → requires_new_dragon
    → D3-C Candidate Generation
    → Schema Validation
    → Archetype Resolve
    → Location / Domain Grounding
    → Anti-spam / Idempotency
    → Atomic PostgreSQL Commit
    → committed dragon_id Read-back
    → Finalize sighting / direct_encounter
```

在新 Dragon Commit 成功并读回正式 `dragon_id` 前，不得：

- 向玩家叙述具体 Dragon 已出现；
- 写入 `dragon_first_encounter`；
- 产生正式 `sighting` / `direct_encounter` World Truth；
- 将 Candidate name、appearance 或其它个体细节当作已存在事实。

`none` 与 `trace` 不需要具体 `dragon_id`，可以在 D3-B 后直接 Finalize。该 provisional/final 区分是既有 D3-B/D3-C 流程中的状态边界，不新增 Architecture Layer。

## 6. Contextual Encounter Policy

D3-B 使用轻量 `Context Score + Injectable Random Roll`，而不是固定 `random < X`。

### 6.1 Deterministic context factors

Score 必须来自有限、可解释的因素：

- Action Family 是否适合探索/搜索
- 是否明确 Dragon-related intent
- Search specificity：普通“找龙”低于“沿悬崖寻找龙巢”
- Authored Location type/description 是否支持 Dragon narrative context
- 当前 Location 是否已有 Dragon
- Recent Encounter History 是否显示连续重复搜索
- D2 是否已成功或以允许的 narrative-only exploration 完成

Location、Action、Intent 与 Existing Dragon 可以提高对应 Outcome 的机会；重复同一低成本输入应降低新发现机会。

### 6.2 Injectable roll

- Production 由注入的随机源给出有限 roll。
- Tests 传入 deterministic roll，不能依赖真实随机数。
- Score 和 roll 共同选择 `none / trace / sighting / direct_encounter`。
- D3-B 负责冻结具体权重、边界和 Outcome bands；本设计不引入通用 Probability Framework。
- Grounding gate 可以把概率结果降级，例如没有可用 existing Dragon 且不允许生成 Candidate 时，`sighting` 必须降级为 `trace` 或 `none`。

## 7. Existing Dragon Reuse

World continuity 优先于 variation。

### 7.1 Minimum eligibility

Existing Dragon 至少必须：

1. 存在于 PostgreSQL `dragons`；
2. `current_location` 与本次 Authored Location 相同；
3. explicit Dragon target（如果存在）能够 Resolve 到该 Dragon；
4. 对本次 Outcome 可被感知：
   - `sighting` 可以使用同地点 Dragon；
   - `direct_encounter` 不选择明确处于 `avoiding` 或仅远距离 `flying` 状态的 Dragon，除非其他 Grounded Context 支持直接接触。

### 7.2 Selection order

存在多个 eligible Dragon 时使用确定性顺序：

1. explicit resolved Dragon target；
2. Recent Encounter History 中最近与玩家相遇的同地点 Dragon；
3. stable `dragon_id` ordering 作为最终 tie-breaker。

选中 existing Dragon 后：

- 不调用 New Dragon Candidate Generation；
- 不复制 Dragon；
- 返回正式 `dragon_id`；
- 只有真正第一次 encounter 时才创建 `dragon_first_encounter`，重复 sighting 不伪造 first event。

## 8. New Dragon Candidate Boundary

只有同时满足以下条件，D3-B 才能请求 D3-C 生成新 Candidate：

1. Action 通过 Eligibility Gate；
2. Encounter Decision 需要 `sighting` 或 `direct_encounter`；
3. 当前 Location 没有适合该 Outcome 的 eligible existing Dragon；
4. Recent History / anti-spam 没有阻止新个体发现；
5. Location Context 允许 Dragon encounter；
6. 至少一个 authored Dragon Archetype 可以 Resolve。

Candidate 应映射现有 `dragons` 字段：

- `archetype_id` 必须来自 authored registry；
- `name`、`sex` 可以为 null；
- `age_stage`、`appearance`、`temperament_traits` 必须通过 Schema/Domain Validation；
- `current_location` 由 Grounded Encounter Context 设置，不能由模型任意选择；
- `health_state / energy / hunger / alertness` 使用 D3-C 明确的受控初始 policy，不接受任意模型数值；
- `behavior_state` 必须属于现有 CHECK；
- `taming_state` 对 wild discovery 固定为 `wild`。

LLM Candidate 不得包含 Bond、Ownership、Trust Delta、Taming Success、Riding Unlock 或 Encounter Outcome authority。

### 8.1 Minimal Authored Dragon Archetype Registry

D3-C 必须使用一个很小的、Git-tracked 的 Authored Dragon Archetype Registry，以满足 `dragons.archetype_id` 的 NOT NULL 约束并提供稳定的 Runtime behavior / baseline template。

该 Registry 明确不是：

- Dragon Species Enum；
- Dragon Species Taxonomy；
- Dragon Type Ontology；
- 数十种固定龙种目录。

Archetype 只提供底层运行规则与基线模板。多个在 name、appearance、personality、temperament 与 ecological flavor 上叙事完全不同的 Dragon，可以共享同一个 Archetype。LLM 可以在既有 Schema、Archetype 和 Location constraints 内自由生成这些个体 variation，但不得生成 Registry 中不存在的 `archetype_id`。

Archetype Resolution 由 Runtime / Grounding 决定，不由 LLM 获得最终 authority。

## 9. Location / Ecology Constraint

Location 只提供最小 authored constraint：

- `whispering_woods`: forest context，可支持足迹、林间痕迹与林地 Dragon variation；
- `stormcliff`: cliff/wind context，可支持高处巢穴、远距离 sighting 与强风环境；
- `old_ruins`: ruins/ancient context，可支持古老痕迹与遗迹相关 variation；
- `skeld_village`: settlement context，普通休息默认不触发 wild encounter。

这些不是固定 Dragon Species Enum。Archetype 负责稳定规则，LLM 只在已选 Archetype 与 Location constraints 内生成个体 variation。

D3 不建立 Ecology Engine、Population Simulation、Spawn Lifecycle 或动态天气规则。

## 10. Open Exploration Integration

D2 Open Exploration 不改变 Location：

```text
“我沿北边森林继续探索找龙”
→ D2 explore + direction + intent
→ current_location remains authored Location
→ D3 reads direction/intent as Encounter Context
→ none / trace / sighting / direct_encounter
```

D3 的 Encounter 仍归属当前 authored `current_location`。Direction 只影响叙事与 Context Score，不写入 `player_states.current_location`，也不创建永久 Dynamic Location。永久 Location Candidate 留给 D5 Controlled Discovery Lite。

## 11. Dragon World Truth Boundary

正式边界：

```text
Provisional Encounter Decision
→ LLM Dragon Candidate
→ Schema Validation
→ Authored Archetype Resolve
→ Location / Domain Grounding
→ Anti-spam + Idempotency Revalidation
→ Controlled PostgreSQL Transaction
→ Read-back
→ Dragon becomes World Truth
→ Finalize sighting / direct_encounter
```

明确：

- `LLM Candidate != Dragon`
- `Provisional Encounter != Final Encounter`

在 Controlled Commit 之前：

- Candidate 不得出现在 `/api/world`；
- Narrative 不得使用它的 name 或 `dragon_id` 当作已存在事实；
- Candidate 不得创建 DragonEvent、Bond、Ownership 或 Riding State；
- Provider failure 或 validation failure 必须 fail closed。

## 12. Dragon Persistence Boundary

D3-C 只增加明确、薄层 Persistence 操作，例如：

- `get_dragon(dragon_id)`
- `list_dragons_at_location(location_id)`
- `list_recent_dragon_encounter_decisions(player_id, ...)`
- `commit_new_dragon_encounter(...)`
- `insert_dragon_encounter_event(...)`

不引入 Generic Repository、UnitOfWork Framework 或 Dragon Manager。

### 12.1 Decision history

对真正进入 Contextual Decision 的 eligible action，追加一条 `dragon_encounter_decision` Interaction Event。它引用原 D2 source action event ID 于 `event_payload`，保存最小 outcome/audit 信息。其 ID 应由 source action event ID 确定性派生，使同一 D2 Event 只能处理一次。

### 12.2 Existing Dragon encounter

Encounter Decision Event 与必要的 `dragon_first_encounter` 使用现有 Event tables。不得修改 Dragon current state，除非本阶段有独立 Grounded Rule 明确批准；D3 v0.1 默认只记录 Encounter。

### 12.3 New Dragon transaction

新 Dragon 成为正式 sighting/direct encounter 时，至少在一个受控 PostgreSQL Transaction 中：

1. Revalidate source D2 Interaction Event；
2. Revalidate no eligible existing Dragon / anti-spam policy；
3. Validate Candidate and authored Archetype；
4. INSERT `dragons`；
5. INSERT deterministic Encounter Decision Event；
6. INSERT `dragon_first_encounter` referencing the grounded source Interaction Event；
7. Read back the committed Dragon.

任一步失败全部 Rollback。不得 JSON fallback、Dual Write 或部分创建。

## 13. Anti-spam and Idempotency

- 同一 D2 source Interaction Event 只能产生一次 Encounter Decision。
- 同一 source event 不能创建两条 Dragon。
- `dragon_first_encounter` 利用现有 unique constraint 防止重复。
- Recent History 使用最近有限条 `dragon_encounter_decision`，不建立完整 Population Simulation。
- 连续重复“我找龙”降低新 sighting/direct 倾向，允许 `none` 或 `trace`。
- 已有 eligible Dragon 时优先复用，禁止为相同地点和相同连续搜索不断创建个体。
- 不使用 World Tick 不存在的时间推进来伪造 cooldown。

## 14. Bond / Taming Boundary

D3 可以创建：

- Individual Dragon；
- Encounter Decision；
- `dragon_first_encounter` Grounded Event。

D3 不创建或修改：

- `player_dragon_bonds`
- familiarity / trust / fear / bond
- `taming_state` progression（新 wild Dragon 仅初始化为 `wild`）
- ownership
- `riding_unlocked`
- feeding/touch/healing/rescue milestones

Seeing a Dragon does not mean owning it. Encountering a Dragon does not mean bonding with it. 所有后续 Dragon Interaction、Bond 与 Taming 进入 D4。

## 15. Narrative Safety

Presentation 只能描述 D3 已经 Ground/Commit 的 Outcome：

- `none`: 不暗示必然存在附近 Dragon；
- `trace`: 描述非个体痕迹，不生成名字、性别、精确外观或友善态度；
- `sighting`: 必须基于正式 `dragon_id` 的 Grounded projection；
- `direct_encounter`: 可以描述当下接触场景，但不能宣布攻击结果、服从、Bond、Taming 或 Ownership。

LLM 可以生成候选外观或最终自然语言，但不能改变 Outcome、选择未经验证的 Dragon，或把叙事反向写成 World Truth。

## 16. Initial 12 Cases

| Case | Input / Context | Expected design result |
| --- | --- | --- |
| 1 | Skeld 普通休息或喝酒 | Eligibility fail → `none`; no D3 persistence and no Dragon |
| 2 | Whispering Woods：“我寻找巨大的脚印” | 可以得到 `trace`; no Dragon required |
| 3 | Whispering Woods：“我深入森林寻找龙” | 进入 contextual score + injectable roll；不保证 encounter |
| 4 | Stormcliff 主动寻找龙巢 | Search specificity/location context 高于普通行动，但仍不保证成功 |
| 5 | 当前 Location 已有 eligible Dragon | 优先复用 existing `dragon_id`; no Candidate generation |
| 6 | 无 eligible Dragon，Decision 需要 direct encounter | 请求 D3-C Candidate；Ground/Commit 后才返回正式 encounter |
| 7 | 连续三次“我找龙” | Recent-history penalty；不得每次创建新 Dragon |
| 8 | D2 blocked：骑不存在的龙 | 不进入 D3 Decision；不得生成 Dragon |
| 9 | “我沿北边继续探索寻找龙” | 可产生四类 Outcome；current_location 不变且不创建 Location |
| 10 | `trace` outcome | Decision history 可记录；`dragons` 和 `dragon_events` 不新增个体事实 |
| 11 | existing Dragon sighting/direct encounter | Response 必须携带正式 `dragon_id`; first event 只创建一次 |
| 12 | New Dragon Candidate | Validation/Commit 前不可查询、不可叙述为 World Truth；失败必须无残留 |

所有概率相关测试必须注入 deterministic roll。所有写入测试必须使用临时测试实体并清理，不污染正式 Dragon World。

## 17. Complexity Budget

D3 最多新增三个轻量业务职责：

1. Encounter Decision
2. Dragon Candidate Generation
3. Dragon Grounding + Controlled Commit

禁止新增：

- Encounter Manager / Encounter Agent
- Spawn Framework
- Ecology Engine
- Dragon Population Simulator
- Multi-Agent / LangGraph
- Event Bus / Workflow Engine
- Generic Probability Framework
- Dynamic Map Framework
- Repository Framework / UnitOfWork Framework
- 第二套 Dragon Store

顶层七层架构保持不变；D3 进入既有 World Orchestrator、Dragon Runtime 与 PostgreSQL 边界。

## 18. D3-B / C / D / E Responsibility

### D3-B — Encounter Decision

- 构建 EncounterContext；
- Eligibility Gate；
- Context Score + injectable roll；
- 查询/选择 eligible existing Dragon；
- `none` / `trace` 可以直接输出 Final Outcome；
- `sighting` / `direct_encounter` 先输出 Provisional Encounter Decision；
- existing Dragon path 绑定正式 `dragon_id` 后 Finalize；无 eligible Dragon 时输出 `requires_new_dragon`；
- 不调用 Dragon Candidate LLM，不写数据库。

### D3-C — Candidate Generation + Grounding + Controlled Commit

- 建立/确认最小 authored Archetype Registry；
- 只在 D3-B 明确请求时调用一次 Candidate Provider；
- Candidate Schema validation；
- Archetype/Location/Runtime Grounding；
- Anti-spam / Idempotency revalidation；
- 加入薄层 Dragon Persistence 操作；
- Atomic insert Dragon + Decision Event + first encounter event；
- Read back committed `dragon_id` 后 Finalize `sighting` / `direct_encounter`；
- existing Dragon path 不生成新 Candidate。

### D3-D — Runtime / Frontend Integration

- 在 D2 commit 之后消费 source action event；
- 不复制 D2 Interpreter/Resolver；
- 为 `/api/action/execute` 增加最小 encounter result projection，或由同一 World Orchestrator 返回；
- `/api/world` 只有在真实 UI continuity 需要时才最小增加 Grounded nearby Dragon projection；
- 展示 `none/trace/sighting/direct_encounter`，不让 narrative 超过 committed state。

### D3-E — E2E + Final Freeze

- deterministic targeted regression；
- real Provider Case 只做最少必要验证；
- PostgreSQL restart/read-back；
- idempotency、anti-spam、existing reuse 与 no-Dragon-on-trace verification；
- protected state/hash/schema check；
- Final Review and Freeze。

推荐实现顺序严格为 D3-B → D3-C → D3-D → D3-E。不得提前进入 D4 Bond/Taming。

## 19. Explicit Non-goals

D3 v0.1 不实现：

- Dragon Bond / Taming / Ownership / Riding
- Dragon Combat or damage resolution
- Dynamic Location creation
- World Tick or dynamic weather
- Egg acquisition / raising / hatching
- Dragon population, migration or ecology simulation
- high-intelligence Dragon dialogue/memory
- multimodal image/video generation
- Schema Migration or new Database Table
