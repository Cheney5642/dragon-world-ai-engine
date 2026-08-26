# Dragon World Web Interaction v0.1 Baseline

## Baseline Status

- Version: Dragon World Web Interaction v0.1
- Status: FROZEN BASELINE
- Provider: doubao
- Model: doubao-seed-2-0-lite-260215
- Freeze Date: 2026-08-26

此文档冻结 Step 5.4 Web Interaction v0.1 的产品行为、安全边界与回归结果。它不表示后续 NPC、世界扩展或叙事系统已经实现。

## Architecture

```text
Player
  ↓
Next.js Frontend
  ↓
FastAPI
  ↓
Action Interpreter
  ↓
World Validator
  ↓
Action Executor
  ↓
Persistent World State
```

Frontend 只提交玩家的原始自然语言。Preview 不修改状态；Confirm 使用与 Preview 对应的 `previewedInput` 再次请求后端。后端重新读取最新 Save、重新运行 Interpreter 与 Validator、重新生成并确定性校验 Execution Plan，只有白名单 Mutation 才能原子写入 `data/saves/current_world.json`。

## Completed Capabilities

- Persistent World State Visualization
- Simplified Chinese Web UI
- Natural Language Action Input
- Action Interpretation
- World Validation
- Structured Action Preview
- Human-in-the-loop Confirmation
- Safe Action Commit
- Server-side Revalidation
- Persistent World State Refresh
- Deterministic World Log
- Developer View / Runtime Observability
- Blocked / Conditional / No-Mutation Handling
- Cancel Safety
- Stale Preview Protection
- Duplicate Commit Protection
- Backend Offline Handling
- Open World Unknown Exploration Baseline

## Evaluation Results

- Player Creation Evaluation: **6/6 PASS**
- Action Interpreter Evaluation: **8/8 PASS**
- World Validator Evaluation: **9/9 PASS**
- Action Executor Evaluation: **8/8 PASS**
- Open World Exploration Regression: **PASS**
- Schema and deterministic validation: **PASS**
- Evaluation Read Only: **PASS**
- TypeScript `tsc --noEmit`: **PASS**
- ESLint: **PASS**
- Next.js Production Build: **PASS**

真实 Web Runtime 已验收 Preview、Confirm、Commit、后端重校验、状态刷新、Cancel、Blocked、No-Mutation、Stale Preview 与重复提交保护。最终回归期间 `current_world.json` 与 `world_seed.json` 哈希保持不变。

## Open World Design Principle

- **Free Intent**：玩家可以自由表达任何行动意图；Interpretation 不等于成功。
- **Grounded Consequence**：只有通过 World Validation、确定性 Mutation 校验和明确 Commit 的结果才能成为 World Truth。
- **Stable Rules, Expandable World**：World Rules 保持稳定，但当前注册的 Location 与 NPC 不是世界永久边界。
- **Unknown != Illegal**：符合世界观但尚未注册的探索内容不能仅因 Entity 缺失而被 Block。
- **No Silent Generation**：Dynamic World Expansion 实现前，系统不得擅自创建 Location、NPC、Entity ID 或 Persistent State。

`requires_further_resolution` 是未来 World Expansion / Resolution System 的扩展接口。当前它只表明需要后续解析；对应 Preview 不产生 `proposed_mutations`，也不改变 Player Location。

## Safety Boundary

- AI 输出不能直接写入 Persistent World State。
- Frontend 不提交 `proposed_mutations`、Player State 或 World State。
- Commit 必须使用原始 `previewedInput` 并由服务器重新校验。
- `blocked`、`conditional`、`needs_clarification` 和无可执行 Mutation 的结果不能进入 Persistent Commit。
- v0.1 Mutation 白名单仅允许合规 Movement 更新 `player.current_location`。
- Preview、Evaluation 和 Cancel 均保持 Read Only。
- Runtime Save 不进入 Git；`data/world_seed.json` 永远不是 Commit 目标。

## Known Limitations

当前明确尚未实现：

- Generic NPC Runtime
- NPC Dialogue
- NPC Memory
- Relationship System
- NPC Knowledge / Perception
- Dynamic NPC Generation
- Dynamic World Expansion
- Multi-step Action Planning
- Narrator / Diegetic World Response
- Quest System
- Dynamic Event System
- Combat
- Dragon Bonding Runtime
- Multimodal / 3D World

## Future Expansion Points

- `requires_further_resolution` 可路由到未来 Entity / Location Resolution。
- `requires_npc_decision` 可路由到未来 NPC Runtime，但当前不会生成 NPC 回应。
- Executor 可以在新增独立规则、Schema、Mutation 白名单和 Regression 后扩展更多行动类型。
- Narrator、Quest、Event、Combat 与 Dragon Bonding 必须作为独立、可验证的系统加入。

## Freeze Discipline

冻结模块只有在出现可复现的真实 Failure 时才允许修改，并必须遵循：

```text
Failure Reproduction
→ Regression Case
→ Targeted Fix
→ Targeted Regression
→ Full Regression
```

不得为了单个 Case 改写既有产品原则，也不得破坏已经通过的旧 Case。
