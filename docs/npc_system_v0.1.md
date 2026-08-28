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

## NPC Interaction Event Layer v0.1

Step 6.4-A 在已通过 Grounding Validation 的单轮 NPC Response 之后增加一个确定性、只读的 Interaction Event Builder：

```text
NPC Context + Player Utterance
→ Grounded NPC Response
→ Interaction Event Builder
→ Structured Interaction Event Preview
→ Future Memory / Relationship Evaluator
```

Builder 只消费当前已有的 NPC Context、玩家原始输入和 NPC Response，不重新读取 World State、不调用 LLM，也不拥有 Commit 权限。Event 记录 NPC、Player、发生时间和地点、双方本轮表达、轻量 Topic、Player Claims、Memory Candidate 与保守的 Relationship Signal。

### Interaction Event != Memory

Interaction Event 回答“这次互动发生了什么”，每次符合条件的对话都可以产生 Event。Memory 则回答“NPC 是否应该长期记住这件事”。`memory_candidate=true` 只表示未来 Memory Evaluator 值得检查该事件，不会创建 Memory、写入 Save 或保证该事件被记住。

v0.1 仅把长期目标、重要个人计划、重大承诺或显著冲突标为候选。普通问候和知识问答默认不是 Memory Candidate，不因为每次对话都有 Event 就全部进入记忆。

### Player Claim != World Truth

`player_claims` 只保存玩家明确提出的事实主张或个人意图，并使用 `claims`、`declares`、`intends` 等归属措辞。例如“Bjorn 是国王”记录为“Eirik claims that Bjorn is a king”，而不是“Bjorn is a king”。普通问句不会被误记为 Claim。

Interaction Event Schema 没有 verified fact、Knowledge Update 或 World Mutation 字段，因此 Player Claim 既不会更新 NPC Knowledge，也不会成为 Persistent World Truth。未来系统若要接受某项事实，仍需独立证据、World Validation 与受控 Commit。

### Relationship Signal != Mutation

`relationship_signal` 只有：

- `none`
- `potential_positive`
- `potential_negative`

它是供未来 Relationship Evaluator 使用的保守候选信号，不包含 `trust_delta`、`familiarity` 数值、Relationship Type 或任何写入操作。含有关系宣称的对话不会仅凭玩家一句话建立配偶或其他客观关系；语义不足时优先输出 `none`。

### Step 6.4-B 输入边界

未来 Memory / Relationship Runtime 可以把 Interaction Event 当作经过 Schema Validation 的候选输入，再分别决定是否写入 Memory 或提出 Relationship Mutation。Step 6.4-A 本身不持久化 Event Log，不实现 Memory Retrieval、Relationship Mutation、NPC Knowledge Update、Quest Update 或任何 World State Mutation。

## Step 6.4-A Interaction Event Model v0.1 Frozen Baseline

- **Version**: Step 6.4-A Interaction Event Model v0.1
- **Status**: FROZEN BASELINE
- **Freeze Date**: 2026-08-27
- **Golden Cases**: 8/8 PASS
- **Event Layer Targeted Tests**: 11/11 PASS
- **Full Offline Regression**: 62/62 PASS
- **Schema Validation**: PASS
- **Read-only Hash Check**: PASS

冻结基线遵循以下不可混淆的边界：

- **Interaction Event != Memory**：Event 只描述本轮互动；是否长期记忆由未来 Memory Runtime 决定。
- **Player Claim != World Truth**：玩家主张保持归属信息，不能直接成为客观世界事实。
- **Player Intention != Executed Action**：玩家表达计划或愿望不代表行动已经发生，也不保证未来成功执行。
- **Relationship Signal != Relationship Mutation**：候选信号不能直接改变 Trust、Familiarity、Attitude 或 Relationship Type。
- **Interaction Event Layer is Read-only**：该层没有 Event Persistence、Memory Write、Relationship Commit 或 World State Mutation 权限。

下一阶段为 **Step 6.4-B Persistent NPC Memory v0.1**。该能力尚未实现，本次冻结不开始其设计或开发。

## Persistent NPC Memory v0.1

Step 6.4-B1 增加 NPC 系统第一条受控 Persistent Write Path。它只把已验证且 `memory_candidate=true` 的 Interaction Event 转换为 Memory Preview，并在用户明确确认后写入独立 Memory Store：

```text
Validated Interaction Event
→ Deterministic Memory Builder
→ Memory Preview
→ JSON Schema Validation
→ Explicit User Confirmation
→ Idempotency Check
→ Atomic Commit
→ data/saves/npc_memories.json
```

Memory Builder 不调用 LLM，不重新解释完整 Dialogue，也不读取隐藏 World State。它优先使用 Event 中已经归属给玩家的 `player_claims` 作为简短 Memory Content。

### Interaction Event != Memory

Interaction Event 记录一次互动的结构化事实；Memory 是从重要 Event 中筛选出的 NPC 主观长期记录。`memory_candidate=false` 时 Builder 明确返回 `No persistent memory required`，不能生成或提交 Memory。`memory_candidate=true` 也只允许生成 Preview，不能绕过确认自动写入。

### Memory != World Truth

Memory Store 保存 NPC 的主观经历与信息来源，不是 Objective Persistent World State。三类数据保持独立 Source of Truth：

- `data/npcs/anchor_npcs.json`：NPC Profile，即 NPC 长期是谁。
- `data/saves/current_world.json`：客观 Persistent World State。
- `data/saves/npc_memories.json`：NPC Subjective Persistent Memory。

Memory Commit 只允许修改 `npc_memories.json`，不能修改 NPC Profile、World State、NPC Knowledge、Quest 或 Relationship。

### Player Claim 与 Epistemic Status

来自 Player Claim 或 Player Intention 的 Memory 使用 `epistemic_status=reported_by_player`。例如：

```text
Eirik claims that Bjorn is a king.
```

只表示 Astrid 记得 Eirik 曾这样说，不表示 Bjorn 真的是国王。v0.1 不提供 `verified_world_fact`，也没有 Memory → Knowledge Promotion。

`player_intention` 与已执行行动同样分离：Memory 可以记录 Eirik 打算明天独自去 Stormcliff，但不能写成他已经前往或必然会前往。

### Source Event Provenance

每条 Memory 保存 `source_event_id`，可追溯到产生它的 Interaction Event。`memory_id` 使用独立 UUID，不依赖数组位置。Store 使用 `(npc_id, source_event_id)` 作为幂等键，因此同一 NPC 不能重复提交同一个 Interaction Event，即使重复 Preview 生成了新的 `memory_id`。

### Memory Preview、Confirmation 与 Atomic Commit

Preview 阶段不读取或修改 Store。只有输入 `y` 或 `yes` 才进入 Commit；其他输入全部取消。Commit 会重新验证 Memory 与 Store Schema，并先检查幂等键。

写入采用同目录临时文件：

```text
In-memory updated Store
→ Write temporary JSON
→ Flush + fsync
→ Reload and validate temporary Store
→ os.replace atomic replacement
→ Reload and validate committed Store
```

若写入或替换失败，临时文件会被清理，原 Store 保持不变。

### 为什么 v0.1 不做 Retrieval

Step 6.4-B1 只完成 Memory Store、Preview 与 Safe Commit。Memory Retrieval、Memory Context Injection、多轮连续性、Relationship Runtime、Knowledge Update、Embedding、Vector Database 和 RAG 均未实现。Memory 不会自动加入 `NPC Context`；这些读取权限与选择策略留给 Step 6.4-B2。

### Runtime Interaction Event → Memory Commit Bridge

Memory Commit CLI 支持两个互斥来源：

- `--case N`：`Source mode: golden_fixture`，用于固定 Golden Fixture Evaluation。
- `--event-file <path>`：`Source mode: runtime_event`，用于加载外部 Runtime Interaction Event JSON。

`Source mode` 表示 Memory CLI 的输入通道。`--event-file` 仍必须通过冻结的 `npc_interaction_event.schema.json`；它不能接收用户直接构造的 Memory JSON，也不能绕过 `memory_candidate` 检查。合法 Event 始终进入同一个 `build_memory_preview()`、Memory Schema Validation、Explicit Confirmation、Idempotency Check 与 Atomic Commit 链路。

`memory_candidate=false` 的 Runtime Event 会返回 `No persistent memory required.`，不读取或修改 Memory Store。Player Claim 和 Player Intention 继续使用 Event 中已有的归属语义，Memory Builder 不重新解析自然语言，也不把它们升级为 World Truth。

### Development Interaction Event Export

`inspect_interaction_event.py` 支持 `--output-event <path>`，将已验证 Event 原子导出为临时开发 JSON。例如：

```powershell
python scripts/inspect_interaction_event.py --case 6 --output-event data/runtime/latest_interaction_event.json
```

若已有真实 NPC Response Runtime 输出文件，可使用自定义模式：

```powershell
python scripts/inspect_interaction_event.py `
  --npc-id npc_astrid `
  --utterance "我明天准备一个人去 Stormcliff。" `
  --response-file data/runtime/latest_npc_response.json `
  --output-event data/runtime/latest_interaction_event.json
```

导出文件只是开发态 Bridge 输入，不是 Persistent Event Log。`data/runtime/` 被 Git 忽略，导出功能也拒绝覆盖 World Seed、Current World、Anchor Profiles 或 NPC Memory Store。

### Development Memory Store Reset

Golden Fixture 验收数据不会自动清理。开发者必须显式执行：

```powershell
python scripts/reset_npc_memories.py --confirm
```

Reset 会先验证现有 Store，再复用同一 Atomic Writer 写入：

```json
{
  "version": "0.1",
  "memories": []
}
```

没有 `--confirm` 时 Reset 被拒绝。该命令只允许替换 `npc_memories.json`，不会修改 World State、NPC Profile、Knowledge 或任何冻结契约。自动化测试只对 Temporary Store 执行 Reset；正式 Store 必须由用户人工决定何时清理。

## Memory Retrieval + Context Injection v0.1

Step 6.4-B2 为 Persistent NPC Memory 增加一条独立、确定性、只读的读取路径：

```text
data/saves/npc_memories.json
→ Memory Retriever
→ Top-K Relevant Memories
→ Memory Recall Context
→ NPC Response Runtime v0.2
→ Grounded Memory-aware Response Preview
```

它不会改变 Step 6.4-B1 的写入链路。一次 NPC Response 不能自动创建 Memory，也不能修改 World State、NPC Profile、Knowledge 或 Relationship。

### Memory Store != Response Context

Memory Store 是一个 NPC 的持久主观记录集合，不应该整库发送给模型。Retriever 首先以 `npc_id` 和 `player_id` 做硬过滤，防止其他 NPC 或其他玩家的 Memory 进入当前对话；随后才根据当前玩家输入进行相关性排序。

Retriever 使用轻量确定性评分，不调用 LLM、Embedding 或外部服务。v0.1 评分信号包括：

- `created_from_topic` 与玩家输入的语义词重合；
- Memory Content 中的关键 Entity、Location 与行动主题；
- `memory_type` 与当前询问方式的匹配；
- 小幅 Recency 加权。

默认只返回最相关的 0–3 条 Memory。没有相关 Memory 时返回空数组是正常结果；系统不会为了填满 Top-K 而注入无关过去，也不会因为存在 Memory 就在每轮主动提起。

### Memory Recall Context

Step 6.4-B2 不修改冻结的 `npc_context.schema.json`。检索结果使用独立的 `npc_memory_recall_context.schema.json`：

```json
{
  "npc_id": "npc_astrid",
  "player_id": "player_001",
  "retrieved_memories": [
    {
      "memory_id": "npc_memory_...",
      "memory_type": "player_intention",
      "content": "Eirik intends to go to Stormcliff alone tomorrow.",
      "epistemic_status": "reported_by_player",
      "world_context": {
        "world_day": 2,
        "world_hour": 9,
        "location_id": "skeld_village"
      },
      "created_from_topic": "stormcliff_travel_plan",
      "relevance_score": 7.4
    }
  ]
}
```

该结构是一次 Response 调用的最小主观回忆视图，不是新的 Persistent State，也不对最终玩家暴露 Retriever 内部推理。

### Memory != World Truth

`epistemic_status=reported_by_player` 始终表示“NPC 记得玩家曾这样说”，而不是“该内容已经被世界验证”。v0.2 Prompt 要求使用“你之前告诉我……”或“我记得你说过……”等归属表达。

例如记忆 `Eirik claims that Bjorn is a king` 允许 Astrid 确认 Eirik 曾这样说，但不能把 `Bjorn is a king` 当作事实。Memory 不会被写入 `referenced_knowledge`，也不会自动 Promotion 为 NPC Knowledge。

同样，`Eirik intends to go to Stormcliff alone tomorrow` 只表示一个过去表达的计划。它不能证明 Eirik 已经去过 Stormcliff、一定会去，或行动已经成功。当前 World State 与实际执行结果仍由各自的权威层决定。

### Read / Write Separation

Memory 的写入与读取是两条不耦合的管线：

```text
Write: Interaction Event → Memory Builder → Preview → Confirmation → Commit
Read:  Memory Store → Deterministic Retriever → Recall Context → Response Preview
```

读取管线没有 Commit 权限。检查 CLI、v0.2 Response CLI 和自动测试都会对 Memory Store、Current World、World Seed 与 Anchor Profiles 做前后 Hash Check。

### Response Runtime v0.1 vs v0.2

- `npc/response_runtime.py` 与 `prompts/npc_response_system.md` 是冻结的无 Memory v0.1 Baseline，保持原样。
- `npc/response_runtime_v0_2.py` 组合冻结的 NPC Context v0.1、独立 Memory Recall Context 和当前 Player Utterance。
- `prompts/npc_response_memory_system_v0.2.md` 继承 v0.1 Grounding、Knowledge、人格与语言原则，并增加 Memory epistemic rules。
- v0.2 输出仍复用冻结的 `npc_response.schema.json`，因此没有扩张 Response Mutation 权限。

### 为什么 v0.1 不使用 Vector DB / RAG

当前 Anchor NPC 与 Memory 规模很小，确定性过滤和轻量评分更容易审计、测试和复现，也能清楚验证 Privacy / Identity Boundary。Embedding、Vector Database、RAG Framework、Memory Summarization、Consolidation 与 Deletion Policy 都不是当前问题所必需；只有未来数据规模和真实 Failure 证明需要时才引入。

### 离线 Golden Coverage

Step 6.4-B2 的 8 条 Golden Case 覆盖：直接回忆、具体计划回忆、无关 Memory、跨 NPC 隔离、跨 Player 隔离、错误玩家主张的归属、意图不等于完成、空 Memory。Response Integration 使用 Mock Provider，验证 Context Injection 与冻结 Response Schema，不在开发阶段调用真实 Doubao。

## NPC Persistent Memory Read Pipeline v0.1 Frozen Baseline

- **Version**: Step 6.4-B2 — NPC Memory Retrieval + Context Injection v0.1
- **Capability Name**: NPC Persistent Memory Read Pipeline v0.1
- **Status**: FROZEN BASELINE
- **Freeze Date**: 2026-08-27
- **Memory Retriever Tests**: 11/11 PASS
- **Memory-aware Response Integration**: 9/9 PASS
- **Targeted Tests**: 20/20 PASS
- **Full Offline Regression**: 103/103 PASS
- **Python Syntax**: PASS
- **JSON Validation**: 21/21 PASS
- **Protected Hash Check**: PASS
- **Real Doubao E2E**: Relevant Recall PASS; Irrelevant Memory Isolation PASS

冻结后的 Persistent Memory 由两条独立管线组成：

```text
Persistent Memory Write Path
Interaction Event
→ Memory Builder
→ Preview
→ Explicit Confirmation
→ Safe Commit

Persistent Memory Read Path
Memory Store
→ Deterministic Retriever
→ Relevant Memories
→ Memory Recall Context
→ NPC Response Runtime v0.2
→ Read-only Response Preview
```

Write Path 与 Read Path 不共享隐式写入权限。Response Runtime 只能读取相关 Memory；它不能自动 Commit 新 Memory。Memory Builder 与 Commit Runtime 也不会负责检索或生成 NPC Response。

### Frozen Capabilities

- Persistent NPC Memory Store
- Deterministic Memory Retrieval
- NPC / Player Identity Isolation
- Topic、Entity、Location、Memory Type 与 Recency 相关性评分
- 默认 Top-K 3 检索
- 独立 Memory Recall Context Schema
- Memory-aware NPC Response Runtime v0.2
- `reported_by_player` Epistemic Status 保护
- Player Intention 与 Executed Action 分离
- Memory 与 World Truth 分离
- Relevant Memory Recall
- Irrelevant Memory Suppression
- Memory Read / Write Separation
- Read-only Retrieval 与响应预览
- Frozen NPC Response Runtime v0.1 与 Response Schema 兼容

### Frozen Grounding Boundaries

- **Memory Store != NPC Context**：Store 是完整的主观持久记录；Response 只接收 Retriever 选择出的最小 Recall Context。
- **Memory != World Truth**：被记住的内容不会自动修改 Objective World State 或 NPC Knowledge。
- **Player Claim != Verified Fact**：`reported_by_player` 只能证明玩家曾这样表达。
- **Player Intention != Executed Action**：计划、愿望或承诺不证明行动已经发生或未来必然发生。

真实 Doubao E2E 已验证：Astrid 能以“你之前告诉我”的归属方式回忆 Eirik 的 Stormcliff 计划，不把计划说成已执行行动；当玩家询问 Bjorn 的职业时，Stormcliff Memory 不会进入 Recall Context，Astrid 继续仅根据稳定 Knowledge 回答 Bjorn 是 Skeld 的铁匠。两次运行都保持 Read-only。

### Explicitly Not Implemented

本冻结版本不包含：Relationship Runtime、Trust / Familiarity、Automatic Memory Commit、Multi-turn Conversation Working Memory、Memory Summarization、Memory Consolidation、Memory Decay / Forgetting、Memory Importance Scoring、Embedding Retrieval、Vector Database、RAG Framework、Knowledge Promotion、Autonomous NPC Actions、NPC Schedule 或 Quest Integration。

冻结基线后，只有可复现的真实 Failure 才允许修改相关实现。解冻必须遵循：

```text
Failure Reproduction
→ New Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```

任何修复都不得为单个 Case 破坏现有 Golden Cases、冻结的 NPC v0.1 Contracts、Step 5 Baseline、FastAPI Contract、Action Pipeline 或 World Rules。

## NPC Relationship Runtime v0.1 — C1

Step 6.4-C1 建立最小、可解释、可验证的 NPC × Player Relationship Domain Model，并从已验证 Interaction Event 生成只读 Relationship Change Preview：

```text
Current Relationship State
+ Validated Interaction Event
→ Deterministic Relationship Evaluator
→ Relationship Change Preview
→ JSON Schema Validation
→ Read-only Result
```

C1 没有 Relationship Store 或 Commit 权限。`current_relationship` 只来自 Mock / Fixture；Evaluator 不读取或修改 World State、Memory、NPC Profile 或 NPC Knowledge。

### Relationship Dimensions

第一版只包含以下维度：

- `npc_id` + `player_id`：关系所属的 NPC / Player 组合。
- `familiarity`：0–3，分别表示 stranger、acquainted、familiar、close。
- `trust`：-2 到 +2 的保守信任范围。
- `attitude`：`hostile`、`wary`、`neutral`、`warm`。

模型不包含 Love、Romance、Marriage、Jealousy、Loyalty、Fear、Respect、Faction 或通用 `relationship_type`。这些维度没有被当前产品行为验证，不应提前加入。

初始关系保持保守：未知 NPC / Player 默认 `familiarity=0`、`trust=0`、`attitude=neutral`；已有明确普通熟人背景时可使用 `familiarity=1`。C1 Fixture 将 Astrid 与同村的 Eirik 设为 acquainted，但不会因此赋予正 Trust 或 Warm Attitude。

### Memory != Relationship

Memory 保存 NPC 对过去信息或互动的主观记录；Relationship 是 NPC × Player 的累积状态。Evaluator 只消费已验证 Interaction Event，不从 Memory Content 计算关系，也不会因为 Recall 到一条 Memory 就改变 Familiarity、Trust 或 Attitude。

Memory Pipeline 与 Relationship Preview 保持分离：

```text
Memory:       Interaction Event → Memory Evaluation → Optional Memory Commit
Relationship: Interaction Event → Relationship Evaluation → Read-only Preview
```

### Why Ordinary Dialogue Does Not Increase Relationship

Dialogue、Memory Candidate 和 `relationship_signal` 都不等于 Relationship Mutation。问候、普通问题、天气闲聊、无意义赞美或重复 Small Talk 默认输出 `no_change`。C1 不实现“聊天次数增加 Familiarity”，从数据模型上避免反复说“你好”刷关系。

Evaluator 不采用 `potential_positive → trust +1` 的直接映射。Positive Preview 必须同时具备：

- 已验证的 `npc_dialogue` Interaction Event；
- 明确的 `potential_positive`；
- 由上游 Grounded Authority 标记的有意义帮助 / 兑现承诺 / 保护或已验证行动结果 Topic；
- `memory_candidate=true`；
- 没有未验证 `player_claims`；
- 与事件一致的 NPC Response Type。

当前认可的 Grounded Topic 是一个小型、可审计的 Evaluation Vocabulary，不是从玩家原始文本重新推断。未来 Action Result 或 World Event 应由其权威层产生这类 Grounded Evidence。

Negative Preview 同样需要明确 Signal、受支持的 Grounded / Direct Hostile Topic、重要事件标记和相符的 NPC Response。直接威胁本身是 NPC 在对话中观察到的互动；它可以降低 Trust，但不会证明威胁中宣称的外部伤害已经发生。

### Player Claim Cannot Create Relationship Fact

`player_claims` 保留玩家表达的归属边界。玩家单方面说“我救过你父亲”不能证明帮助已经发生，也不能提高 Trust。玩家宣布 Astrid 是妻子不能创建 Spouse、Marriage 或任何关系类型，也不会提高 Familiarity / Trust。

Claim 可以成为未来 Evidence Resolver 的输入，但在被独立验证前始终不是 Relationship Fact。

### Bounds and Preview

所有数值都在 Evaluator 和 Schema 中双重限制：Familiarity 为 0–3，Trust 为 -2 到 +2。达到上限或下限后，相同方向的 Proposed Change 会被 Clamp，不会越界。

Relationship Change Preview 明确包含：

- `current_relationship`
- `proposed_relationship`
- Familiarity / Trust 的 Before、After、Delta 与 Changed 标记
- Attitude 的 Before、After 与 Changed 标记
- `decision`（`no_change` 或 `change_proposed`）
- `source_event_id` 与确定性 Reason

Preview 只描述建议，不代表已提交。相同 Current State 与 Interaction Event 始终生成相同结果；Evaluator 不使用随机数或 LLM。

### Future Database Mapping

未来关系型数据库可将 `npc_id + player_id` 作为 `npc_relationships` 的天然复合唯一键，并保存 Familiarity、Trust 与 Attitude。C1 Schema 已保持单记录、标量字段和明确边界，便于后续迁移；本阶段不创建 JSON Persistent Store、不接 PostgreSQL，也不引入 SQLAlchemy。Persistent Relationship Commit 留给 Step 6.4-C2。

## Step 6.4-C1 — NPC Relationship State + Evaluation v0.1 Frozen Baseline

- **Version**: Step 6.4-C1 — NPC Relationship State + Evaluation v0.1
- **Status**: FROZEN BASELINE
- **Freeze Date**: 2026-08-27
- **Relationship Targeted Tests**: 13/13 PASS
- **Golden Cases**: 8/8 PASS
- **Full Offline Regression**: 116/116 PASS
- **Python Syntax**: PASS
- **JSON / Schema Validation**: PASS
- **Protected Hash Check**: PASS

冻结的 C1 Baseline 包含：

- NPC × Player Relationship Domain Model
- Familiarity、Trust 与 Attitude 的最小 Schema
- Relationship Change Preview Contract
- Deterministic Relationship Evaluator
- Grounded Evidence Boundary
- Anti-Farming / 防刷关系规则
- Player Claim 与 Relationship Fact 分离
- Relationship Signal 与 Relationship Mutation 分离
- Familiarity / Trust Bounds Protection
- Read-only Relationship Evaluation

人工验收确认了三条关键行为：普通 Greeting 保持 `no_change`；系统已确认的 Meaningful Grounded Help 只产生小幅、可解释、受 Bounds 约束的正向变化；Unsupported Hero Claim 即使要求 NPC 信任玩家，也不会提高 Familiarity、Trust 或改变 Attitude。

冻结基线继续遵守：

- **Dialogue != Relationship Mutation**
- **Memory != Relationship**
- **Relationship Signal != Relationship Mutation**
- **Player Claim != Relationship Fact**

普通对话不能自动提高 Familiarity 或 Trust。只有具备充分 Grounded Evidence 的有意义事件，才能进入关系变化路径。C1 的 Evaluator 只产生 Preview，没有 Commit 权限。

本冻结版本尚未实现：

- Persistent Relationship Store
- Relationship Commit
- Relationship Context Injection
- Relationship-aware NPC Response

下一阶段为 **Step 6.4-C2 — Persistent Relationship Runtime**。在 C2 明确开始前，不得为 C1 增加持久化写入或隐式关系变化。

冻结后只有可复现的真实 Failure 才允许修改 C1 Schema、Evaluator、Golden Dataset 或 Evaluation Rules。任何解冻必须遵循：

```text
Failure Reproduction
→ New Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```

## Step 6.4-C2-A — Persistent NPC Relationship Store v0.1

C2-A 将冻结的 C1 Relationship Change Preview 接入独立、受控的 Persistent Write Path：

```text
Validated Interaction Event
+ Current Persistent Relationship
→ Frozen Relationship Evaluator
→ Relationship Change Preview
→ Schema Validation
→ Explicit Human Confirmation
→ Server-side Re-evaluation
→ Atomic Commit
→ data/saves/npc_relationships.json
```

Relationship Store 是独立 Runtime Domain，不属于 `current_world.json`、`anchor_npcs.json` 或 `npc_memories.json`。正式 Store 初始结构为：

```json
{
  "version": "0.1",
  "relationships": []
}
```

每条 Persistent Record 包含冻结 Relationship State 的 `npc_id`、`player_id`、`familiarity`、`trust`、`attitude`，以及轻量 Audit 字段 `applied_event_ids` 和 `last_source_event_id`。

### Unique NPC × Player Relationship

Store Validator 强制 `(npc_id, player_id)` 唯一，一个组合只能拥有一个当前关系状态。这与未来关系型数据库的 `UNIQUE(npc_id, player_id)` 对齐。JSON Schema 负责字段类型和 Bounds，本地确定性校验负责复合唯一键及 Audit 一致性。

### Default Relationship Is Not an Automatic Write

当 Store 中不存在指定 NPC / Player 组合时，Runtime 根据冻结的 C1 Initial Relationship Policy 在内存中构建 Default Relationship。当前 Vertical Demo 明确认定 `npc_astrid + player_001` 是普通熟人，因此默认 `familiarity=1`、`trust=0`、`attitude=neutral`；其他未配置组合默认 `0 / 0 / neutral`。

Preview 不会因为读取了 Default Relationship 就创建 Persistent Record。只有冻结 Evaluator 产生 `change_proposed`，用户明确确认且 Commit 再验证通过后，才允许建立第一条 Store Record。

### Commit Authority

Commit API 只接受 Frozen Interaction Event 和系统生成的 Expected Preview。它不接受客户端直接提交 Familiarity、Trust、Attitude 或任意 Proposed State。

确认后 Runtime 会重新加载 Store、检查幂等性、重新解析当前关系并再次调用冻结 Evaluator。如果重新生成的 Preview 与用户看到的 Preview 不一致，Commit 会以 Stale Preview 拒绝，而不是提交未确认的变化。

`decision=no_change` 时不会显示有效 Commit 路径，不询问确认，也不写 Store。Greeting、普通问题、Marriage Claim 和 Unsupported Hero Claim 都保持该边界。

### Idempotency and Lightweight Audit

每条 Persistent Record 保存已成功应用的 `applied_event_ids`。`source_event_id + npc_id + player_id` 已存在时，重复 Preview 或 Commit 返回：

```text
Relationship change for this interaction event already applied.
```

同一 Grounded Help Event 因此不能把 Trust 从 0→1 后再次刷到 2。`last_source_event_id` 提供当前状态最近一次变化来源；C2-A 不建立完整 Event Sourcing 或 Relationship History。未来数据库可把 Applied Event Audit 拆分为独立表。

### Atomic Write and Reset

Relationship Commit 复用项目安全写入模式：

```text
In-memory Updated Store
→ Validate
→ Same-directory Temporary File
→ Flush + fsync
→ Reload + Validate Temporary Store
→ os.replace
→ Reload + Validate Committed Store
```

失败时临时文件被清理，原 Store 保持不变。`reset_npc_relationships.py --confirm` 使用同一 Atomic Writer 把 Store 重置为合法空结构；没有 `--confirm` 时明确拒绝。Reset 只允许修改 Relationship Store。

### Runtime Event Bridge and Inspection

`commit_npc_relationship.py` 支持两种互斥来源：

- `--case N`：`Source mode: golden_fixture`
- `--event-file <path>`：`Source mode: runtime_event`

两者都消费同一个冻结的 `npc_interaction_event.schema.json`，不创建第二套 Event Contract。`inspect_npc_relationship.py` 只读显示 Persistent Record；缺少记录时会显示未持久化 Default Relationship 与 `Persistent record exists: no`。

`npc_relationship_persistence_test_cases.json` 定义 8 条 C2-A Persistence Golden Case，并通过 `interaction_case` 引用冻结的 C1 Event Fixture：Greeting、普通问题、Marriage Claim、Grounded Help Cancel/Confirm、Duplicate Commit、Grounded Threat、Unsupported Hero Claim 与 Bounds。它只描述持久化行为，不复制或改写 Interaction Event Contract。

### Persistent Boundary

C2-A 合法 Commit 只允许修改 `data/saves/npc_relationships.json`。自动测试使用 Temporary Relationship Store，并通过 Hash Check 保护 World Seed、Current World、NPC Memory Store、Anchor Profiles、NPC Knowledge 与全部冻结 Runtime。

本阶段尚未实现 Relationship Context Injection、Relationship-aware NPC Response、Relationship Commit API/Web UI、PostgreSQL、SQLAlchemy 或 Alembic。这些能力不能从 Store 的存在推断为已完成。

## Step 6.4-C2-A Persistent NPC Relationship Store v0.1 Frozen Baseline

- **Version**: Step 6.4-C2-A — Persistent NPC Relationship Store v0.1
- **Status**: FROZEN BASELINE
- **Freeze Date**: 2026-08-28
- **Relationship Persistence Targeted Tests**: 17/17 PASS
- **Relationship Evaluation Tests**: 13/13 PASS
- **Persistence Golden Cases**: 8/8 PASS
- **Full Offline Regression**: 133/133 PASS
- **Python Syntax**: PASS
- **JSON / Schema Validation**: PASS
- **Protected Hash Check**: PASS

冻结的 C2-A Baseline 包含：

- 独立 Persistent NPC Relationship Store
- Default Relationship Read-only Fallback
- NPC × Player 复合唯一关系
- Frozen Evaluator 驱动的 Relationship Change Preview
- Human-in-the-loop Commit
- Server-side Re-evaluation 与 Stale Preview Protection
- Safe Atomic Write
- `source_event_id + npc_id + player_id` Idempotency
- `applied_event_ids` 与 `last_source_event_id` 轻量 Audit
- Golden Fixture 与 Runtime Event 输入
- Read-only Inspection
- Explicit Safe Reset
- Persistent Boundary Protection

最终人工验收确认：Greeting 的 `no_change` 不创建 Persistent Record；Grounded Meaningful Help 经 Preview 和用户输入 `y` 后，将 Astrid × Eirik 从 `1 / 0 / neutral` 安全提交为 `2 / 1 / warm`；重复提交同一 `npc_event_44444444444444444444444444444444` 被幂等性检查拒绝，关系不会继续增长到 `3 / 2 / warm`。

冻结写入架构为：

```text
Validated Interaction Event
+ Current Persistent Relationship
→ Frozen Relationship Evaluator
→ Relationship Change Preview
→ Schema Validation
→ Human Confirmation
→ Idempotency Check
→ Atomic Commit
→ npc_relationships.json
```

Interaction Event 不能直接修改 Relationship，客户端也不能直接提交 Familiarity、Trust 或 Attitude。任何 Mutation 必须由冻结 Evaluator 根据受支持的 Grounded Evidence 生成，并在 Commit 时重新验证。

Relationship 继续是独立 Runtime Persistent Domain：

- **NPC Profile != Relationship**
- **Memory != Relationship**
- **Relationship != World State**

合法 Commit 只允许修改 `data/saves/npc_relationships.json`。本冻结版本尚未实现 Relationship Context Injection 或 Relationship-aware NPC Response。

下一阶段为 **Step 6.4-C2-B — Relationship Context Injection + Relationship-aware Response**。在该阶段被明确启动前，不得扩展 C2-A 的响应行为或引入隐式 Relationship Mutation。

冻结后只有可复现的真实 Failure 才允许修改 Store Schema、Persistence Runtime、Golden Dataset 或 Commit Rules。解冻必须遵循：

```text
Failure Reproduction
→ New Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```
