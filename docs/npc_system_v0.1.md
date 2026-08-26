# Generic NPC System v0.1

## 1. Generic NPC Model 是什么

Generic NPC Model 是 Astrid、Bjorn、Haldor 以及未来 Dynamic NPC 共用的数据契约。每个 NPC 都是同一份 `npc_profile.schema.json` 的数据实例，而不是一套独立代码或专用 Agent。

Step 6.1 只建立 NPC Profile 数据层，不调用 LLM，不生成对话，不执行 NPC Decision，也不修改 Persistent World State。

## 2. 为什么 NPC 不是一人一套代码

如果每个角色都拥有专用代码，角色数量会直接扩大实现和测试成本，安全边界也容易不一致。统一模型让通用 Runtime 可以按 Entity ID 加载任意 Profile，并用相同的 Schema Validation、World State Resolution、Knowledge Boundary 和 Memory Policy 处理所有角色。

角色差异来自 Profile Data，例如背景、性格、价值、说话方式、目标和已知信息，而不是不同的运行时代码分支。

## 3. Profile 与 Runtime State

**NPC Profile** 保存相对稳定的长期信息：

- `id`、`name`、`species`、`occupation`
- `background`
- `personality.traits`、`values`、`speaking_style`
- `goals`
- stable `knowledge`
- `relationship_defaults`
- `memory_policy`

**NPC Runtime State** 保存当前世界中的可变事实，例如：

- `current_location`
- `current_activity`
- `mood`
- temporary status
- 实际 Relationship 与 Memory 记录

Profile 不包含这些动态字段。未来 Runtime 必须通过 NPC `id` 到 Persistent World State Resolve 当前状态，不能在 Profile 中维护第二个 `current_location` Source of Truth。

现有 Frozen World Seed 中的 NPC 字段保持不变；Step 6.1 不进行迁移或 Runtime 接线。新增 Anchor Profile 是下一阶段通用 Runtime 的受 Schema 约束输入。

## 4. World Truth 与 NPC Knowledge

World State 是客观 World Truth；`profile.knowledge` 只表示某个 NPC 稳定知道的实体、地点和事实。两者不能等同。

一个事实存在于 World State，不代表每个 NPC 都知道它。反过来，NPC 的说法或理解也不能自动改写 World Truth。未来 NPC Runtime 只能基于该 NPC 可访问的 Knowledge 与 Perception 作出回应，不能把完整 Save 当作角色的全知上下文。

## 5. Knowledge 与 Memory

**Knowledge** 是 NPC 相对稳定的已知信息，例如 Bjorn 懂金属加工、Haldor 了解龙的行为。它描述角色可用于推理的知识边界。

**Memory** 是运行过程中产生的具体经历，例如玩家曾与 NPC 交谈、做出承诺或参与重大事件。Step 6.1 只定义 `memory_policy`，说明未来是否保留玩家互动、重大事件以及近期记忆上限；它不创建 Memory Storage，也不实现写入、检索、摘要或遗忘。

## 6. Anchor NPC 与 Dynamic NPC

**Anchor NPC** 是当前世界预先确立并拥有稳定 Entity ID 的角色。v0.1 包含：

- `npc_astrid`
- `npc_bjorn`
- `npc_haldor`

**Dynamic NPC** 是未来通过受控 World Expansion 创建的角色。Dynamic NPC 必须复用同一 Generic NPC Profile Schema，并在成为 World Truth 前完成 Entity ID 分配、Schema Validation 和明确的 Persistent State Mutation。Step 6.1 不实现 Dynamic NPC Generation。

## 7. Anchor NPC 的最小方向

- **Astrid**：来自 Skeld 渔夫家庭，直接、好奇、独立，重视家庭与探索。
- **Bjorn**：Skeld 铁匠与 Eirik 的打铁导师，务实而严厉，重视手艺和责任。
- **Haldor**：经验更丰富的 Dragon Tamer，沉稳谨慎，重视证据，不轻易认可未经证明的说法。

这些信息提供后续 Runtime 的差异化起点，不是固定剧情，也不会锁死角色发展。

## 8. Relationship Defaults

`relationship_defaults` 只提供未来首次建立 Runtime Relationship 时的最小初始态度和熟悉度。玩家与 NPC 之后形成的信任、冲突、承诺或关系变化必须写入 Persistent Runtime State，不能反向覆盖 Profile，也不能预先穷举在 Anchor Data 中。

## 9. Step 6.2–6.4 扩展边界

- **Step 6.2**：按 Entity ID Resolve NPC Runtime State，并构建最小、只读的 NPC Context；不调用 LLM。
- **Step 6.3**：基于 Minimal NPC Context 和本轮 Player Utterance 生成单轮 Grounded Structured Response；NPC 输出不能直接修改 World Truth。
- **Step 6.4**：可实现 Memory Storage、Retrieval、摘要与写入策略；必须继续区分 Knowledge、Memory 和客观 World State。

Step 6.2–6.3 已实现；Step 6.4 仍未实现。任何新增 State Mutation 都需要独立 Schema、确定性校验、权限边界和 Regression。

## 10. NPC Context Builder

NPC Context Builder 是 Deterministic / Read-only 的信息筛选层。它接收一个 NPC Entity ID、调用方提供的 World State 和 Player ID，组合该 NPC 的 Profile、当前 Runtime State、明确 Knowledge 与本次共享环境，输出符合 `npc_context.schema.json` 的 Minimal NPC Context。

### 为什么 NPC 不能读取整个 World State

完整 Save 包含其他 NPC 的状态、所有 Location、Global State、World Rules、Relationship、Memory，以及当前 NPC 没有理由知道的信息。如果将它整体交给未来 NPC Runtime，角色会成为全知实体，也会扩大 Prompt 注入面和错误 State Mutation 风险。

Context Builder 因此属于信息权限层：它决定本次调用“可以看到什么”，而不是决定 NPC “应该说什么”。它不是 Narrator、Agent 或 Prompt Generator。

### Minimum Necessary Context

v0.1 只输出：

- 当前 NPC 的长期 Profile 摘要
- 从 Persistent World State Resolve 的 `current_location`、可选 `current_activity` 和 `mood`
- Player 的最小公共身份与当前位置
- `same_location`、day、hour、weather 和 NPC 当前地点公共摘要
- Profile 明确列出的 known entities、known locations 与 known facts

Known entity 只包含 `id`、`name`、`species`、`occupation`；Known Location 只包含 ID、名称、类型和公共描述。其他 NPC 的 personality、goals、Knowledge、Memory、Relationship 和临时状态不会被透传。

### Context 与 Profile / Knowledge / Memory

- **Profile** 是长期身份输入。
- **Runtime State** 是当前可变世界事实。
- **Knowledge** 是该 NPC 明确知道的有限信息。
- **Memory** 是未来由运行事件产生并检索的经历，Step 6.2 尚未接入。
- **Context** 是针对一次 Runtime 调用，从上述允许来源临时组合出的最小只读视图。

Context 不是新的持久化 Source of Truth，也不会反向写入 Profile 或 World State。

### World Truth != NPC Knowledge

Builder 可以读取 World State 来 Resolve Profile 已授权的 Entity 和 Location，但不会因为某项 World Truth 存在就自动把它加入 NPC Context。未列在该 NPC Knowledge 中的其他实体和地点保持隐藏。

### 未来 NPC Runtime 如何消费 Context

未来 NPC Runtime 只能把该结构化 Context 作为角色可访问的事实边界。Dialogue 或 Decision 可以基于它生成候选回应，但仍不能直接修改 World Truth。NPC Decision、Dialogue、Memory Retrieval、Relationship Runtime 和所有 State Mutation 均不属于 Step 6.2。

## 11. NPC Response Runtime

NPC Response Runtime 将 `build_npc_context()` 的输出与玩家本轮 Utterance 组合，调用配置的 LLM Provider，并返回符合 `npc_response.schema.json` 的单轮 Structured Response。它不直接读取 `current_world.json`；Save 只能由 CLI 加载后作为参数交给 Context Builder。

完整链路：

```text
NPC Profile + Persistent World State + NPC Knowledge
→ NPC Context Builder
→ Minimal NPC Context + Player Utterance
→ NPC Response Runtime
→ Structured NPC Response Preview
```

### Grounded Dialogue

NPC 的事实性回答只能来自 Minimal NPC Context，或明确标记为玩家本轮说法的信息。Context 中不存在的事实必须保持 `unknown` / `partial`，NPC 可以自然表达“不知道”“不确定”或“没听说过”，不能为了对话流畅而补写世界事实。

模型输出后仍需通过本地 JSON Schema Validation，并检查 `referenced_knowledge` 中的 Entity ID、Location ID 和 Fact 都是输入 Context Knowledge 的子集。越界引用会被确定性拒绝。

### Personality affects HOW, Knowledge decides WHAT

Personality 控制语气、直接程度、关注点与表达风格。例如 Astrid 可以表现出好奇和务实，但这不能让她知道 Haldor 的当前位置或 Bjorn 的私人恐惧。Knowledge 决定 NPC 能陈述哪些事实；Personality 不扩大信息权限。

### Player Claim != World Truth

Player Utterance 是不受信任的 Dialogue Input。玩家说“Bjorn 是国王”不会修改 World State，也不会要求 Astrid 接受该说法。Astrid 可以用已知的 `npc_bjorn = blacksmith` 进行纠正；若缺乏证据，则只能保留不确定。

### Unknown Knowledge Honesty

`knowledge_status` 区分：

- `known`：Context 直接支持。
- `partial`：Context 只支持部分内容。
- `unknown`：Context 不包含所问事实。
- `not_applicable`：本轮是反应、请求或意见，而非事实知识问题。

Unknown 不是运行错误，也不能触发对隐藏 World State 的额外读取。

### Dialogue != State Mutation

NPC Response Schema 只包含 NPC ID、回复类型、Speech、Knowledge Status、Knowledge References 与 Follow-up 标记。它没有 Memory Write、Relationship Delta、Quest Update 或 State Mutation 字段。

面对面前提由代码确定性检查：`same_location=false` 时，在创建 Provider Client 或调用 LLM 之前直接返回 Interaction Unavailable。无论对话内容如何，Response Runtime 都没有 Save Commit 权限。

### 为什么 v0.1 只有单轮对话

Conversation History 本身会形成 Memory 与 Context 权限问题。Step 6.3 尚未实现 Memory Storage、Retrieval、Relationship Runtime 或 Conversation Session，因此每次 Utterance 都是独立调用。多轮连续性必须等 Step 6.4 建立明确的记忆写入、检索和持久化边界后再加入。

## NPC Foundation v0.1 Frozen Baseline

- **Version**: Dragon World NPC Foundation v0.1
- **Status**: FROZEN BASELINE
- **Freeze Date**: 2026-08-27
- **Scope**: Step 6.1 Generic NPC State Model、Step 6.2 NPC Context Builder、Step 6.3 NPC Response Runtime

### Architecture

```text
Generic NPC Profile + Persistent World State + NPC Knowledge
→ Deterministic NPC Context Builder
→ Minimum Necessary NPC Context + Player Utterance
→ Grounded NPC Response Runtime
→ Structured, Read-only NPC Response
```

NPC Profile 保存长期角色信息，Persistent World State 保存当前位置、心情等动态事实，Knowledge 定义角色能够知道什么。Context Builder 只暴露当前交互所需的最小信息；Response Runtime 生成结构化对话 Preview，但不拥有任何 State Mutation 或 Commit 权限。

### Completed Capabilities

- Generic NPC Profile Model
- Astrid、Bjorn、Haldor Anchor NPC Profiles
- Profile / Runtime State Separation
- NPC Knowledge Boundary
- World Truth != NPC Knowledge
- Minimum Necessary NPC Context
- Grounded NPC Dialogue
- Personality affects HOW, Knowledge decides WHAT
- Player Claim != World Truth
- Unknown Knowledge Honesty
- Private Knowledge Boundary
- Same-location Interaction Guard
- Read-only NPC Response Runtime
- Structured NPC Response
- Chinese Language Matching

### Evaluation Results

- NPC Profile Offline Tests: 6/6 PASS
- NPC Context Tests: 8/8 PASS
- NPC Response Offline Tests: 8/8 PASS
- NPC Response Doubao Golden Evaluation: 8/8 PASS
- Full Offline Regression: 51/51 PASS
- Persistent State Safety: `world_seed.json` 与 `current_world.json` 均未被测试修改

8 个 Golden Evaluation Cases 覆盖：

1. Known Fact Accuracy
2. Unknown Knowledge Honesty
3. Personality Consistency
4. Player Claim Grounding
5. Private Knowledge Boundary
6. Known Fact Usage
7. Dialogue Mutation Boundary
8. Deterministic Interaction Preconditions

### Known Limitations

当前 Baseline 明确不包含：

- Persistent NPC Memory
- Memory Retrieval
- Relationship Runtime
- Trust / Familiarity Mutation
- NPC Knowledge Update
- Player Claim Belief System
- Multi-turn Conversation Memory
- Quest Integration
- NPC Autonomous Action
- NPC Schedule
- Dynamic NPC Generation
- Dynamic NPC Location Movement

### Next Step

下一阶段是 Memory & Relationship Runtime。当前冻结不实现 Step 6.4，也不把未来能力描述为现有能力。

冻结模块只有在出现可复现的真实 Failure 时才允许修改，并必须遵循：

```text
Failure Reproduction
→ Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```
