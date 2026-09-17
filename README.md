# Dragon World — AI World Engine v0.1

Dragon World 是一款以自由自然语言行动驱动的持久化开放世界原型。玩家可以提出任何行动；语言模型负责理解与表达，World Engine 根据证据、规则与 PostgreSQL 中的状态决定什么真正发生。当前 Demo 世界是 Dragon Isles。

**Dragon World v0.1 — FINAL FROZEN.** D1–D8 与最终 Browser E2E 已完成；后续能力属于独立的 v0.2 范围，不包含在本版本中。

## Architecture

```text
Player / Next.js Presentation
  → FastAPI Interaction Layer (/api/action/execute)
  → World Runtime / Orchestration
  → World Rules and grounded D2 resolution
  → NPC Runtime / Dragon Runtime / D5 Location Discovery
  → PostgreSQL Persistent World (only Runtime source of truth)
  → /api/world read-back → Presentation / D7 Scene Renderer
```

自然语言解释不能直接写入 World Truth。D2 提交正式 Interaction Event；NPC、Dragon、Location 与 Riding 的专属规则只在符合条件时提交状态。D7 图片是从已提交世界状态构建的第一人称渲染结果，不反写事实。旧 JSON 是迁移/备份产物，不参与正式 Runtime 写入。

## Implemented Demo Capabilities

- 自由身份与自然语言行动；受控的预览、提交及世界状态读取。
- NPC 对话及正式 Memory / Relationship 边界；不把玩家自述当作客观事实。
- 动态 Dragon Encounter、Bond / Taming 和具有反刷取规则的 Dragon 互动。
- D5 受控动态地点发现与 PostgreSQL 地点注册表 read-back。
- D6 Dragon Riding：明确骑乘意图、门槛验证、首次骑乘解锁、骑乘移动、下龙。骑乘状态存于 `world_state_entries`，骑乘解锁存于 `player_dragon_bonds`；玩家和龙同一事务移动。D4 已驯服不等于可骑乘：首次解锁需要 trust ≥ 4、bond ≥ 3、fear ≤ 1、符合体型和年龄条件且双方同地点；未达门槛时只能通过正式互动推进羁绊。普通休息、观察等非骑乘行动不会进入 D6。
- D7 关键事件的第一人称静态 Scene Visual：地点发现、正式 Dragon Encounter、上龙、骑乘抵达。未配置图片供应商或供应商出错时返回可见降级状态，文字玩法保持可用。没有视频生成。
- 中文 World Shell：当前地点、附近 NPC / Dragon、关系和骑乘状态、世界日志、自然语言行动、Scene Visual 与结构化 Developer View。

## Dragon World v0.1 Demo Flow

约 3–5 分钟，使用 `player_001` 和现有 PostgreSQL 世界，不重置已驯服的 Kael。具体位置、Bond 和 Riding State 以 `/api/world` 当前 read-back 为准，不为演示覆盖持久状态。

1. 在浏览器查看 `/api/world` 读出的当前位置、NPC、Kael 与羁绊；用自由语言探索，观察 Structured Action、Grounding（与真实对象/地点绑定）和 World Log。
2. 查看已注册的动态地点“雾蚀凹湾”，在可达规则内前往或从当前位置 read-back；正式地点和位置都由 PostgreSQL 决定。
3. 在 Kael 所在位置观察或与它互动，展示 Encounter、Bond / Taming 边界。Kael 已驯服，不为演示伪造再次驯服。
4. 若骑乘尚未解锁，先通过合法且非重复的 D4 互动达到门槛；输入“我骑上 Kael”。首次成功会记录 `dragon_accepts_mount`；已经解锁时按现有状态正常上龙。
5. 输入明确的骑乘移动命令前往当前可达地点；玩家与龙必须原子地一起抵达。动态地点旅行也遵守地点连接规则。场景图片若未配置则显示降级提示，玩法继续。
6. 输入“我从 Kael 背上下来”，随后输入“我在雾蚀凹湾停下来休息片刻”；休息应是普通叙事行动，`dragon_riding=null`。刷新浏览器、重启用户自己的 Backend 并读取 `/api/world`，确认骑乘状态、羁绊和地点仍一致。

该故事展示的是 LLM 理解/表达与 World Engine 决定世界事实之间的职责分离，不承诺每句自由输入都成功。

## Local Run

Python 虚拟环境安装 `requirements.txt`；在项目根目录由 `.env.example` 创建本地 `.env`，设置 PostgreSQL `DATABASE_URL` 与所需文本模型配置，并运行 `alembic upgrade head`。不要提交 `.env` 或密钥。现有 Demo World 需要正式 Recovery Seed，不能靠启动服务自动伪造历史。

用户负责长期运行 Backend 和 Frontend：

```text
Backend:  .venv/bin/python -m uvicorn api.app:app --env-file .env --host 127.0.0.1 --port 8000
Frontend: cd frontend && npm install && npm run dev
```

浏览器打开 `http://localhost:3000`。前端 API 地址配置见 `frontend/.env.local.example`。

图片是可选功能：在本地 `.env` 中配置 `IMAGE_PROVIDER=doubao`、`ARK_IMAGE_MODEL`、`ARK_IMAGE_SIZE`，并使用已有的 `ARK_API_KEY` / `ARK_BASE_URL`。不配置图片模型或 Key 时状态为 `disabled`；供应商失败为 `failed`，均不会撤销游戏行动。图片结果仅在当前 Action API Response 中返回远程 URL 与少量 metadata，刷新后不会从数据库重建该图片；世界事实照常从 PostgreSQL 重建。v0.1 已验证 Provider Contract、模拟渲染与 disabled graceful fallback；**当前本机未完成人工真实图片 API 生成验收**。

## Validation and Boundaries

自动验证入口为 `python -m unittest`、`frontend` 下的 `npm run lint` / `npm run build`，以及 `git diff --check`。数据库集成测试会创建并清理专属测试玩家；不要把测试数据混入 Demo 世界。旧 D5 测试有“动态地点注册表起初为空”的 fixture 假设，不适用于已恢复的正式 Demo 数据；此限制不代表 D5 Runtime 回归。

## Known Limitations and Deferred Scope

- 当前主要 Demo Dragon 是 Kael；这不是完整的多龙内容库。
- 真实图片 API 生成效果尚未在当前本机人工验收；只确认渲染契约、模拟结果和 Provider disabled/failure 降级。
- 不包含视频生成、Multiplayer、完整 Combat / Economy / Quest System 或无限动态地图。
- 没有第二套 World Engine，也不允许图片模型反写世界事实。上述扩展均延后讨论；本次 Freeze **不开始 v0.2**。
