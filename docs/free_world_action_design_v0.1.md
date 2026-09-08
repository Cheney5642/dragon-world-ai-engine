# Free World Action Design v0.1

## 1. Version and Status

- Version: D2-A — Free World Action Design v0.1
- Status: FROZEN DESIGN BASELINE (Design Only)
- Implementation: Not started
- Runtime, Prompt, Schema, Database and Frontend changes: None in D2-A

本文件定义 D2 的产品边界、运行语义和后续 Domain Routing（领域路由）。它不是实现说明，也不表示本文中的 Contract 已经写入现有 Schema。

## 2. Product Principle

### World Skeleton is Authored; Discoveries are AI-generated

**世界骨架由我们定义，未知内容通过玩家探索由 AI 生成。**

稳定的区域结构、已注册 Location、核心 World Rules、NPC 与 Dragon 领域规则由项目明确维护。玩家不受已注册内容限制，可以自由朝未知方向行动；未来由 AI 生成的 Discovery 只能先成为 Candidate，不能仅凭叙述直接进入 Persistent World。

这条原则同时保护两件事：

- 世界不是完全预写死的地图，玩家能够发现设计时没有逐项枚举的内容；
- AI 不是 World Truth 的直接写入者，永久事实仍须经过规则接受与受控持久化。

### Free Intent, Grounded Consequence

玩家可以表达或尝试任何行动。Structured Action 只描述玩家意图；行动是否成立、产生什么后果、哪些字段能够修改，必须由 World Validation、对应 Domain Runtime 和 Commit Boundary 决定。

```text
Player Intent != Executed Action
Player Claim != Objective World Truth
LLM Output != Persistent World Truth
Freedom of Action != Guaranteed Success
```

## 3. D2 Scope

D2 只实现 **Free World Action**：理解开放行动、区分行动类型、使用既有 World Rules 判断通用行动，并在有限白名单内形成安全结果。

D2 明确不实现：

- Dynamic Dragon Generation
- Dragon Encounter Resolution
- Permanent Dynamic Location Creation
- World Tick

D2 也不把尚未实现的 Domain Outcome 包装成已完成结果。遇到 Dragon、NPC、Ownership 或动态发现语义时，D2 只保留并路由意图。

## 4. Runtime Flow

D2 的 Runtime Flow 为：

```text
Player Natural Language
→ Action Interpreter
→ Structured Action
→ Existing World Validation / Rules
→ Known Travel / Open Exploration / Domain Routing / Narrative-only
→ Controlled Mutation
→ PostgreSQL
→ Interaction Event
```

Action Interpreter 是 D2 的轻量业务职责。它可以复用 `llm/client.py` 与 Structured Outputs infrastructure，但不得复用 Identity Interpreter Prompt、Identity Interpreter Schema 或 Identity Interpreter Business Logic。

上述分类表示运行链路中的职责分派，不新增 Architecture Layer、`Action Manager`、Router Framework 或其它独立基础设施。Controlled Mutation 仅在存在经过规则验证的合法变更时进入 PostgreSQL Commit；Interaction Event 仍须通过正式事件持久化路径记录。

没有合法 Mutation 的 Action 仍可产生 Narrative-only Result（仅叙事结果）或 `requires_further_resolution`，但不得伪造成功、Entity 或 Persistent State。

## 5. Structured Action Contract

D2 的目标 Contract 保留既有 Action Interpretation 顶层字段，并为每个行动步骤明确区分已知目的地与开放方向：

```ts
type EntityReference = {
  type: string;
  id: string | null;
  name: string | null;
};

type DestinationReference = {
  id: string;
  name: string;
};

type ActionStep = {
  verb: string;
  target: EntityReference | null;
  destination: DestinationReference | null;
  direction: string | null;
  goal: string | null;
  method: string | null;
};

type StructuredAction = {
  raw_input: string;
  action_kind:
    | "speech"
    | "movement"
    | "interaction"
    | "observation"
    | "wait"
    | "self_expression"
    | "compound"
    | "other";
  steps: ActionStep[];
  speech: string | null;
  claimed_facts: string[];
  requires_world_check: boolean;
  needs_clarification: boolean;
};
```

字段语义：

- `destination`：已经由当前 Authored World Skeleton 解析的明确 Location。`id` 必须是真实 Stable Domain ID，不得由 LLM 编造。
- `direction: string | null`：玩家表达的开放探索方向，例如 `north`、`along the northern coast`、`deeper into the forest`。它不是 Location ID，也不证明该方向存在某个具体地点。
- `target`：非旅行目标，或行动所针对的 NPC、Dragon、Object、Location 名称；无法匹配时允许 `id = null`。
- `goal`：玩家希望达到的目的，不表示目的已经完成。
- `claimed_facts`：玩家主张，不是事实写入入口。

对 Movement / Exploration Step 采用以下不变量：

- Known Destination Travel：`destination != null`，`direction = null`。
- Open Exploration：`destination = null`，`direction != null`。
- 非移动步骤：二者通常均为 `null`。
- 不得为了填充 `destination` 而给未知地点伪造 ID。
- 同一步骤不得同时用 `destination` 与 `direction` 表达两套相互竞争的移动目标；已知目的地优先保留为 `destination`，路线描述可放入 `method`。

当前 Frozen Action Schema 不在 D2-A 修改。上述增量 Contract 留待后续实现阶段以最小版本化方式落地。

## 6. Known Destination Travel vs Open Exploration

### Known Destination Travel

Known Destination Travel 指玩家明确前往 Authored World Skeleton 中已注册、可解析的 Location，例如 Whispering Woods。

```text
destination.id = whispering_woods
direction = null
```

World Validation 仍须检查当前位置、连接关系和其它前置条件。只有 Validation 允许、Mutation Proposal 合法并完成 Controlled Commit 后，`player_states.current_location` 才能改变。

### Open Exploration

Open Exploration 指玩家沿方向、地貌或未知边界探索，而没有一个当前可解析的已知 Location，例如“沿北海岸探索”或“往北一直走”。

```text
destination = null
direction = "along the northern coast"
```

D2 对此必须遵循：

- 不得仅因为 Registry 中没有目的地而返回 `Invalid Location`；
- 保留自由探索意图；
- 可以返回 Narrative-only / `requires_further_resolution`；
- 不得自动创建永久 Location、Location ID、连接关系或地图事实；
- 在 Location 尚未通过未来 Discovery Pipeline 接受前，不修改 `player_states.current_location`。

Unknown 不等于 Illegal，但 Unknown 也不等于已经发现或已经抵达。

## 7. Dragon Domain Routing

D2 可以理解以下 Dragon-related Intent：

- 寻龙
- 观察龙
- 接近龙
- 骑龙

理解意图不授予 D2 生成以下事实的权限：

- Dragon Existence
- Dragon State
- Dragon Ownership
- Dragon Bond
- Dragon Encounter Outcome

这些内容必须 Route to Dragon Runtime。D2 可以验证通用移动部分、保留 Dragon Intent，并说明需要 Dragon Domain Resolution；不得直接声称出现了一条龙、玩家拥有龙、成功接近龙或已经骑乘。

### Future D3: Dynamic Dragon Encounter

未来 D3 Encounter Resolution 的输入概念包括：

- Player Context
- Current Location
- Resolved Action
- Player Intent
- Environment
- Existing Dragons
- Encounter History

D2 不实现 Encounter Director，也不计算或提交 Dragon Encounter Outcome。

### Dragon Candidate Boundary

未来即使 LLM 生成 Dragon Candidate，该 Candidate 仍不是 World Truth：

```text
LLM Dragon Candidate
→ Dragon Rules
→ World Engine Acceptance
→ PostgreSQL Commit
→ Dragon becomes World Truth
```

在完成最后一步之前，不得创建正式 Dragon ID、Runtime State、Ownership 或 Bond。

## 8. Controlled Discovery Lite Boundary

未来 D5 负责最小的永久动态发现链路：

```text
explore
→ Location Candidate
→ World Rules
→ PostgreSQL
→ New World Truth
```

D2 只识别 `explore` 与 `direction`，不执行 Location Candidate Generation，也不提交永久 Location。D2 可以叙述探索动作本身，但不得把具体新地点、巨大脚印或其它生成内容写成已接受的世界事实。

未来 Dynamic Encounter 与 Discovery 应采用 **Contextual Probability（上下文概率）**，而不是简单固定 RNG。概率可以受以下因素影响：

- location
- environment
- player action
- intent
- encounter history

D2 v0.1 不实现概率系统，不保存概率状态，也不通过随机数决定发现或遭遇。

## 9. Narrative-only Action Boundary

Narrative-only Action 是开放世界的工程降复杂机制，不是失败兜底或虚假成功包装。

适用情形包括：

- 行动可以被理解，但当前没有需要持久化的通用 State Mutation；
- 结果属于尚未实现的 NPC、Dragon、Combat、Ownership 或 Discovery Domain；
- 未预定义的奇怪行动可以安全描述“尝试”，但不能形成受保护的事实；
- 开放探索方向尚未解析为永久 Location。

Narrative-only 可以表达玩家做出的动作、可观察到的既有环境反应，或当前无法完成解析；不得表达未经 Domain Runtime 接受的死亡、所有权、Dragon Encounter、永久发现、物品获得或位置变化。

如果叙事内容会改变未来判断，它就不再是纯 Narrative-only，必须进入对应 Domain Runtime 或 Controlled Discovery Pipeline。

## 10. State Mutation Boundary

D2 通用 State Mutation 默认只允许：

```text
player_states.current_location
player_states.inventory
player_states.goals
interaction_events
```

### Implementation Scope Note

上述四项是 D2 General Action Runtime 的最大 Mutation Boundary。为了 MVP / Lean Implementation，D2-B～D2-E 第一版优先实际实现：

- `player_states.current_location`
- `player_states.goals`
- `interaction_events`

`player_states.inventory` 保留在允许边界内，但没有真实 Player-facing Case 需要时，不主动扩展 Inventory Runtime。允许边界不代表第一版必须实现全部写入能力。

约束如下：

- `current_location`：只接受已知 Location、通过 World Validation 的合法移动。
- `inventory`：只接受已有规则能够证明来源、转移与数量的通用变更；不得由叙事凭空生成物品。
- `goals`：只接受玩家明确提出的 Goal 增删，并保持幂等与去重；Goal 不是已完成 World Fact。
- `interaction_events`：记录经过正式 Runtime 形成的事件，不把玩家声明升级为客观事实。

以下状态不属于 D2 通用写权限：

- NPC State、NPC Memory、NPC Relationship
- Dragon、Dragon State、Dragon Bond、Dragon Ownership、Dragon Event
- Ownership 与其它 Domain-specific State
- 永久动态 Location 与地图连接

它们必须 Route to 对应 Domain Runtime。D2 不得借由通用字段或自由 JSON 绕过领域规则。

## 11. Initial Design Cases

| # | Player Action | Classification | D2 v0.1 Expected Boundary |
|---|---|---|---|
| 1 | 去 Whispering Woods | Known Destination Travel | 将 `whispering_woods` 作为 `destination`；经连接与前置条件验证后，才可提出 `current_location` Mutation。 |
| 2 | 去森林找龙 | Known Travel + Dragon-related Intent | 森林若明确指 Whispering Woods，可验证旅行；“找龙”路由 Dragon Runtime。D2 不生成 Dragon 或 Encounter Outcome。 |
| 3 | 沿北海岸探索 | Open Exploration | `destination = null`，`direction = along the northern coast`；不得返回 Invalid Location，不创建永久 Location。 |
| 4 | 酒馆喝酒 | Unknown Target / Narrative-only | 未注册酒馆不得获得伪造 ID；可以保留前往、饮酒意图，不凭空扣除物品或写入酒馆事实。 |
| 5 | 骑自己的龙 | Dragon + Ownership Claim | 路由 Dragon Runtime；验证 Ownership、Bond 与 Riding Unlock 前，不承认“自己的龙”或骑乘成功。 |
| 6 | 回自己的豪宅 | Unknown Location + Ownership Claim | 不创建豪宅或 Ownership；保留玩家主张，返回 Narrative-only / requires further resolution。 |
| 7 | 添加找龙蛋 Goal | Generic Goal Mutation | 可提出幂等的 `player_states.goals` 添加；只记录目标，不生成龙蛋或位置线索。 |
| 8 | 删除找龙蛋 Goal | Generic Goal Mutation | 仅在目标存在且匹配时提出删除；缺失时为 no mutation，不影响其它 Goals。 |
| 9 | 杀 Astrid | NPC / Combat Domain | 可以理解攻击意图，但不得直接修改 Astrid、Relationship 或死亡事实；路由相应 Domain Runtime，当前可 Narrative-only / unresolved。 |
| 10 | 未预定义奇怪行动 | Open-ended Other Action | 使用自由 `verb` / `other` 保留意图；不因未枚举而拒绝，也不伪造结果或状态。 |
| 11 | 往北一直走 | Open Exploration | `direction = north`；不要求已知目的地，不返回 Invalid Location，不提交新的 `current_location`。 |
| 12 | 森林寻找巨大脚印 | Observation / Search + Discovery Boundary | 可以在已知森林中表达搜索；D2 不证明巨大脚印存在，也不生成或持久化 Discovery Candidate。 |

这些 Case 是 D2 设计验收输入，不表示 D2-A 新增测试、Fixture 或实现。

## 12. Responsibility Split: D2, D3 and D5

| Stage | Owns | Does Not Own |
|---|---|---|
| D2 — Free World Action | 自由行动理解、Known Travel、Open Exploration 语义、通用 Mutation 白名单、Domain Routing、Narrative-only Boundary | Dragon 遭遇结果、动态 Dragon、永久新 Location、概率系统 |
| D3 — Dynamic Dragon Encounter | 基于上下文形成与解析 Dragon Encounter，并依照 Dragon Rules 接受 Candidate | 通用自由行动框架、永久动态地点发现、Dragon Bond / Taming |
| D5 — Controlled Discovery Lite | Location Candidate、World Rules Acceptance、永久 Location 的 PostgreSQL Commit | 通用 Action Interpretation、Dragon Encounter、World Tick |

D2 为 D3 提供 Resolved Action 与 Player Intent，为 D5 提供 Open Exploration 语义；D2 本身不提前执行 D3 或 D5 的职责。

## 13. Roadmap

```text
D2 — Free World Action
D3 — Dynamic Dragon Encounter
D4 — Dragon Bond / Taming
D5 — Controlled Discovery Lite
D6 — World Tick
D7 — Multimodal Image
D8 — Dragon Riding
D9 — First-person Riding Video
```

Roadmap 只表达责任顺序，不代表后续阶段已经实现或其 Contract 已冻结。

## 14. Complexity Budget

D2 不新增：

- Action Manager
- Generic Rule Engine
- Event Bus
- Workflow Engine
- LangGraph
- Multi-Agent
- Quest System
- Dynamic Map Framework

D2 的 Action Interpreter 保持轻量，并复用现有 LLM / Structured Outputs 基础设施、World Validation / Rules、Executor、Domain Runtime 与 PostgreSQL Persistence 边界。需要开放性时，优先使用自由动词、明确路由和 Narrative-only Action，而不是扩建通用框架。

## 15. D2-A Non-goals and Handoff

D2-A 只完成设计。后续实现必须先根据本文件检查现有 Frozen Contract，再提出最小改动；不得把本文当作修改 Frozen Core 的自动授权。

D2-A 完成后停止，不开始 D2-B。
