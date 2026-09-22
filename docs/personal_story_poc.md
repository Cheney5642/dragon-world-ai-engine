# Personal Story PoC — 本地试玩与实现说明

本地工作区扩展，未创建 Release、版本 Tag 或 Freeze。正式 Runtime 仍使用 PostgreSQL；没有新 Migration、依赖或第二套行动管线。

## Phase 0 审查结论

- 复用 `identity/interpreter.py`、`identity/grounding.py` 和身份 context：自由身份继续区分自述、愿望和客观事实。
- 复用 `/api/action/execute` 与 D2/D3/D4/D5/D6：故事读取已经提交的行动，不替换动作校验、地点发现或驯龙规则。
- 复用 NPC Relationship Evaluator、Memory Preview 与现有 NPC API。只有实际同地点分享已有亲历记录才生成 `verified_shared_result`；聊天中的自称帮助不等于完成帮助。
- 复用 `world_state_entries` 的按玩家 JSONB 文档保存 PoC 故事，键为 `player.<id>.story.v1`。`interaction_events` 保留正式来源；NPC 记忆、关系仍用现有表。
- 复用 Scene Renderer 的 provider 与失败降级；扩展关键故事事件的结构化场景、Prompt 及 Developer View。
- 原界面固定使用 `player_001`。现在新建人生使用独立 Player，前端按所选 Player 读回；NPC API 同样按请求玩家加载世界。原 Demo 玩家与世界不会被重置。
- Bjorn 的档案引用旧玩家。NPC Context 现在可读取这位旧熟人的公开实体，同时保持当前新玩家独立，不继承旧角色的师徒经历或关系。

## 启动

用户负责长期运行的服务。修改代码后重启自己的 Backend；Frontend 使用现有 Next.js 启动方式：

```text
# 项目根目录
.venv/bin/python -m uvicorn api.app:app --env-file .env --host 127.0.0.1 --port 8000

# frontend 目录
npm run dev
```

本轮没有更改 `.env`。文本模型使用原有 Provider 配置；图片沿用原有可选配置。不要重复启动已占用 8000/3000 的服务。

首次进入浏览器会显示自由身份创建；已创建的角色会从 PostgreSQL 继续人生。浏览器本地仅保存所选 Player ID 与角色标签，不作为世界事实存档。顶部可开启新人生或切换该浏览器创建过的人生。新人生共用已有地点/NPC/Dragon 世界，不代表 Multiplayer，也不复制或重置 Kael。

## 6–8 步试玩

输入身份：

> 我是一个失去家族荣耀的年轻骑士，希望寻找传说中的龙。

然后逐句行动：

1. `我观察了一下四周` — 生成当前地点的个人观察事件；展开“为什么这件事发生？”查看身份、目标、来源行动和历史。
2. `我向 Astrid 分享这次观察记录` — 在 Skeld 与 Astrid 同地点时，分享正式亲历记录。产生 NPC Memory；复用规则评估信任与熟悉度。不会声称玩家已经救人或驯龙。
3. `我前往 Old Ruins` — 通过原有地点规则旅行；下一个事件读取先前的分享选择与 NPC 关系。
4. `我决定暂时保密，保留自己的记录` — 个人故事转向独立探索，不额外改变 NPC 信任。
5. `我回到 Skeld` — 新事件反映之前的保密选择。
6. `我停下来休息片刻` — 普通休息不会产生 Riding Result，也不会虚增人生里程碑。
7. 可选：`我向 Astrid 询问附近有什么值得探索的地方` — 原有 NPC Runtime 对话；正式关系变化会记录进人生时间线。
8. 刷新浏览器；重启自己的 Backend 后再次刷新，检查人生经历、关系与所选玩家位置。

再次“开启新人生”，输入：

> 我是一个流亡贵族，希望通过帮助当地居民恢复家族荣耀。

同地点观察时应获得不同关注点的事件。贵族身份仍作为未经世界证明的自述；不会授予权力。

点击事件建议只会填入行动框，仍可编辑自己的语言。可以直接前往其它地点继续探索，无须先完成建议项。分享需要明确且同地点的 NPC；不在村庄时先返回，不能远程增加关系。同一地点的亲历记录只奖励一次分享，不允许反复刷取信任。

## 面试展示

“我的人生故事”展示身份、背景、性格倾向、目标、可能的方向、当前选择与人生轨迹。Developer View 展示：

- Player Identity：包含自述／愿望标记和未验证主张。
- Narrative Thread：初始方向、当前分支、已记录章节数。
- World Changes：已提交移动、目标变化、正式龙互动、地点发现或 NPC 关系变化。
- NPC Relationship：PostgreSQL 当前读回。
- Recent Events：事件原因、参与实体、建议选择、已发生后果与来源 ID。
- Scene Description / Image Prompt：仅由当前正式地点、可见实体与已记录事件构建。Provider disabled/failed 时仍可查看 Prompt，文字行动继续。

## API 增量

- `POST /api/player/create`：`{request_id: UUID, self_description: string}`；返回新 Player ID 与 world。相同请求 ID 重试不会重复创建或覆盖身份。
- `GET /api/world?player_id=...`：所选玩家世界；PoC 玩家额外包含 `personal_story` 和 `known_locations`。
- `GET /api/story/{player_id}`：人生记忆、当前分支、最近事件及关系，只读。
- 现有 `POST /api/action/execute` 增加可空 `story_update`；原有结构化行动、Resolution、D5/D6/D7 返回保持可用。
- NPC 端点保持原 Contract；世界读取改为与请求中的 Player 一致。

## 事务边界

身份创建中的 Player、PlayerState 和初始故事在同一事务中写入，模型失败不产生半成品角色。故事提交在既有行动完成后执行；它不会回滚已经成功的 D2 行动。

亲历记录分享的 Story、NPC Event、Memory、Relationship 在同一事务内完成；重放同一来源幂等。故事提交失败时返回明确的 `story_update.status=failed`，不声称故事已保存，不提示重做已提交的世界行动。图片生成在这些事务完成后调用，失败不会改变世界或故事事实。

## 验证入口

```text
.venv/bin/python -m unittest tests.test_personal_story -v
.venv/bin/python -m unittest tests.test_web_api tests.test_npc_api tests.test_location_discovery tests.test_dragon_riding tests.test_scene_renderer -q

# frontend
npx tsc --noEmit
npm run lint
npm run build
```

新测试在真实 PostgreSQL 上使用独立临时玩家，并清理准确的测试 ID；自动测试中的文本与图片 Provider 是受控测试替身。真实模型试玩需要另外确认，不把测试替身结果称为真实生成。

原 D5 fixture 假设动态地点注册表为空；本轮将断言改成相对已有注册表的增量验证，并恢复测试结束后的注册表来源元数据。Web 旧 JSON fixture 改为测试临时文件；Dragon read-back 测试改为读取自己的测试玩家。没有为测试改变正式 Runtime 规则，也没有删除已有用例。

本轮实际验证：

- 265 项相关自动测试通过，包含 18 项新增 PoC 测试；覆盖 D2–D7、PostgreSQL、NPC Context/Runtime/Relationship、Web/API。
- Python Syntax、TypeScript、ESLint、Production Build、`git diff --check` 通过。
- 使用真实文本 Provider 和 PostgreSQL，在进程内 ASGI API 创建寻龙骑士与流亡贵族，各执行 6 次自然语言行动，全部 HTTP 200。同地点分别产生 `field_observation` 与 `reputation_opportunity`；分享使 Astrid 的 trust 达到 1，保密改变后续叙事。测试使用固定的遭遇随机值以免生成无关临时龙，图片 Provider disabled。
- 真实图片 API 效果尚未验收；已验证失败和 disabled 降级。
- 浏览器已检查新人生开场和自由身份输入页面。正在运行的旧 Backend 未包含新创建 API；完整浏览器试玩须由用户重启 Backend 后进行，没有把进程内验证宣称为完整 Browser E2E。
- 临时 PoC 玩家已清理；旧 D5 测试留下的失效测试来源指针也已清理，地点内容不变。

## 修改文件清单

新增：

```text
identity/origin.py
core/personal_story.py
frontend/types/story.ts
frontend/components/personal-story.tsx
frontend/components/personal-story.module.css
tests/test_personal_story.py
docs/personal_story_poc.md
```

扩展：

```text
api/app.py
api/npc_api.py
database/persistence.py
npc/context_builder.py
multimodal/scene_renderer.py
frontend/lib/api.ts
frontend/types/action.ts
frontend/types/world.ts
frontend/components/world-opening.tsx
frontend/components/world-opening.module.css
frontend/components/world-shell.tsx
frontend/components/world-shell.module.css
tests/test_web_api.py
tests/test_location_discovery.py
tests/test_dragon_encounter_integration.py
README.md
```

## 当前限制

- 事件是规则约束的 PoC：AI 理解自由身份和行动，四种故事关注点（探索、声望、关怀、自由）影响事件表达；分享／保密形成后续分支。还不是无限生成剧情或完整 Quest System。
- 自由描述支持任意角色，但世界中的目的地、能力与行为结果仍需要 Grounding。没有明确目的地时可被要求澄清；界面显示已知地点供参考。
- 普通“我帮助了村民”不会凭空成为成就。首个可演示正向关系行为是分享实际探索记录；更复杂的帮助行为仍需后续加入正式规则。
- 当前主旨来自 Origin，玩家的新目标会被后续事件读取；不会实时重写一套无限叙事路线。
- 世界日／小时不自动推进，时间线使用“经历 N”。普通聊天不是人生里程碑。完整记忆暂存单个 PostgreSQL JSONB 文档，适合短时 Demo，未做长期归档。
- 图片 Prompt 与降级可验证；真实图片生成质量必须单独人工验收。图片 URL 当前不作为历史视觉档案保存，刷新不恢复图片。
- 不包含视频生成；未来视频可消费同一 Scene Description，通过独立 Provider Interface 实现，当前没有视频任务或后台服务。
- Local PoC 沿用现有无鉴权本地 API，不提供跨用户授权或公网部署保障。
- 原有 Demo Player 如果存在世界状态不一致，仍由 v0.1 校验拒绝读取。本扩展不自动清理 mounted state 或覆盖旧世界；新人生入口独立于旧玩家读回。
