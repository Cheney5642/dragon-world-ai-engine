# Dragon World — AI Native World Engine Prototype

Dragon World 是一个由自然语言驱动的持久化开放世界原型。玩家不是从固定职业或任务列表开始，而是用一句话创造身份、目标和人生方向；之后每次自由行动都会经过结构化理解、世界规则裁决和 PostgreSQL 状态提交，逐步形成只属于这个玩家的故事。

> **版本状态**
>
> - `v0.1.0`：已冻结并位于 GitHub `main`，最终提交为 `090b83c`。
> - `v0.2 PoC`：当前 `main` 的产品展示版本，包含 AI Character Origin、Personal Narrative、真实场景生图和地点专属画面；它是 PoC 里程碑，尚未创建独立版本标签。

![Dragon World — Skeld](frontend/public/locations/skeld.jpg)

## What This Prototype Proves

Dragon World 想验证的不是“让 AI 多写几段 RPG 文案”，而是一个更完整的 AI Native World Loop：

```text
Player Creation
  → World Understanding
  → Free Exploration
  → Grounded Dynamic Event
  → Personal Narrative Memory
  → Future Consequence
  → Scene Visual Generation
```

核心原则是：

> Player can say or attempt anything; the world decides what becomes true.
>
> 玩家可以说任何话、尝试任何事；世界决定什么能够成立、什么真正发生。

LLM 负责理解自由输入和生成叙事表达，但不能直接修改 World Truth。正式事实必须经过规则校验和 Runtime 提交后，才能进入 PostgreSQL 持久世界。

## Latest Local PoC Capabilities

### AI Character Origin

玩家不需要选择“战士 / 法师 / 猎人”。可以直接输入：

```text
我是一个失去家族荣耀的年轻骑士，希望寻找传说中的龙。
```

系统会生成并保存：

- Identity / Background
- Personality
- Goal
- Narrative Direction
- 未被世界证实的自述声明

玩家可以创建和切换多段独立人生，已有 v0.1 Demo 世界不会被覆盖。

### Natural Language World Interaction

- 自由自然语言行动与 Structured Action（结构化动作）。
- World Grounding（世界落地）：地点、NPC、Dragon 和行动目标必须对应正式世界事实。
- Action Validation / Resolution：玩家提出行动不等于行动必然成功。
- `/api/action/execute` 返回结构化结果、玩家反馈和 Developer View 数据。

### Persistent World

- PostgreSQL 是正式 Runtime 唯一事实来源。
- 玩家位置、Dragon 状态、Bond、Taming、Riding、NPC Memory、Relationship、动态地点和个人故事均可持久化读取。
- 浏览器刷新或 Backend 重启后，通过 `/api/world` 恢复正式状态。
- 不使用 JSON Runtime Dual Write，不把 LLM 输出直接当作数据库事实。

### NPC and Dragon Runtime

- NPC 对话、Memory、Relationship 与 Knowledge Boundary。
- `Trust != Truth`：NPC 信任玩家不等于接受玩家的错误陈述。
- Dynamic Dragon Encounter。
- Dragon Interaction、Anti-Farming、Bond / Taming。
- Dragon Riding：门槛校验、骑乘解锁、Mount、Mounted Travel、Dismount。
- 普通观察、休息和交流不会错误进入 Riding Branch。

### Controlled Dynamic Location Discovery

- Runtime 可以在符合条件时创建受控动态地点。
- 动态地点会进入 PostgreSQL Location Registry，并参与正式 travel/read-back。
- 当前 Demo 已包含动态地点“雾蚀凹湾”。

### Personal Narrative Engine

- 保存的是“玩家人生轨迹”，不是聊天记录。
- 玩家身份、目标、已完成行动、NPC Relationship 和历史选择共同影响后续事件。
- 故事事件带有 reason、evidence、choices 和 consequences，可解释“为什么发生”。
- 分享见闻或保留记录会形成不同 Narrative Branch。
- 人生故事 UI 使用可折叠卷轴展示，默认不会占据主要游戏视野。

### Multimodal Scene Generation

- World Truth → Scene Description → Structured Image Prompt → Image Provider。
- 当前视觉触发包括 Dragon Encounter、Dynamic Location Discovery、Mount、Mounted Arrival 和 Personal Story Event。
- 火山方舟 Seedream 的真实图片调用与非空 `image_url` 已人工验证成功。
- 图片 Provider 超时或失败时保持 Graceful Fallback；文字玩法仍返回 HTTP 200。
- 图片只是 Presentation Artifact，不反写 World State。

### Location-specific Game Art

主视图根据 `current_location` 自动切换地点专属背景。实时事件生成图片具有更高展示优先级；没有事件图片时，始终保留地点画面。

| Stormcliff | Old Ruins |
| --- | --- |
| ![Stormcliff](frontend/public/locations/stormcliff.jpg) | ![Old Ruins](frontend/public/locations/old-ruins.jpg) |
| 永久受到风暴与巨浪冲击的黑色海崖。 | 建造者未知、被群山和迷雾包围的古代遗迹。 |

| Whispering Woods | 雾蚀凹湾 |
| --- | --- |
| ![Whispering Woods](frontend/public/locations/whispering-woods.jpg) | ![雾蚀凹湾](frontend/public/locations/mist-eroded-cove.jpg) |
| 古老巨木、野生生物与龙类传闻共存的森林。 | 被寒雾和海风侵蚀、隐藏于黑色海岸中的动态地点。 |

所有地点图均为项目生成的原创黑暗中世纪史诗奇幻环境图，不包含具体人物、Dragon 或阵营徽记，避免静态背景伪造实时 World Truth。

## Architecture

```text
Next.js Presentation
  ├─ Character Origin / Life Selection
  ├─ Natural Language Action
  ├─ Personal Story Scroll
  └─ World + Scene Visual Read-back
                ↓
FastAPI Interaction Layer
                ↓
Structured Action / Grounding / Resolution
                ↓
World Orchestrator
  ├─ NPC Runtime
  ├─ Dragon Runtime
  ├─ Location Discovery
  ├─ Riding Runtime
  └─ Personal Narrative Director
                ↓
PostgreSQL Persistent World
                ↓
Scene Visual Renderer → Ark Seedream / Graceful Fallback
```

### AI Boundary

| Component | Responsibility |
| --- | --- |
| LLM | 理解玩家输入、提出候选解释、生成自然语言表达 |
| Rule Engine / Runtime | 判断行动是否合法、什么事实能够改变、哪些事件可以提交 |
| PostgreSQL | 保存正式 World Truth 和个人人生轨迹 |
| Image Provider | 根据已提交事实渲染场景，不修改世界状态 |

## Demo Flow

1. 打开网页，用自然语言创建任意身份。
2. 查看系统生成的 Identity、Background、Goal 和 Narrative Direction。
3. 输入自由行动，例如“我离开村庄，前往北方森林寻找龙的踪迹”。
4. 查看 Structured Action、Resolution 和 Grounded World Effect。
5. 与 NPC 或 Dragon 互动，观察 Relationship / Bond 的受控变化。
6. 在关键故事节点查看 Personal Narrative Event 和场景图片。
7. 前往 Skeld、Stormcliff、Old Ruins、Whispering Woods 或雾蚀凹湾，观察主画面自动切换。
8. 展开“我的人生故事”卷轴，查看 Identity、Narrative Thread、World Changes、NPC Relationship 和 Recent Events。
9. 刷新浏览器或重启 Backend，通过 `/api/world` 验证持久化结果。

## Local Run

Python 虚拟环境安装 `requirements.txt`；从 `.env.example` 创建本地 `.env`，设置 PostgreSQL `DATABASE_URL` 与所需 Provider 配置，然后执行：

```bash
alembic upgrade head
.venv/bin/python -m uvicorn api.app:app --env-file .env --host 127.0.0.1 --port 8000
```

另一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:3000`。不要提交 `.env`、数据库密码或 Provider Key。

### Optional Image Provider

本地 `.env` 可配置：

```text
IMAGE_PROVIDER=doubao
ARK_IMAGE_MODEL=<your-seedream-model>
ARK_IMAGE_SIZE=1024x1024
ARK_IMAGE_TIMEOUT=120
```

`ARK_API_KEY` 与 `ARK_BASE_URL` 只保存在本地环境。Provider 未配置时状态为 `disabled`；调用异常时状态为 `failed`，两种情况都不会撤销已经完成的世界行动。

## Validation

主要验证入口：

```bash
python -m unittest
cd frontend && npm run lint
cd frontend && npm run build
git diff --check
```

v0.1 已完成 Final Browser E2E。当前 v0.2 PoC 已人工验证角色创建、个人故事、Dragon Interaction、真实 Seedream 生图、图片失败降级和地点背景展示；本次提交前同时执行 Python 与 Web 定向回归。

## Known Limitations

- 当前是 AI 产品与世界引擎 PoC，不是完整商业游戏。
- 主要 Demo Dragon 仍是 Kael；动态遭遇中可出现其他 Dragon，例如 Voryn。
- 图片 URL 是当前 Action Response 的展示结果，尚未建立 Visual Artifact 持久化图库。
- 同步生图会增加关键 Action 的响应时间；当前通过独立图片超时和 Graceful Fallback 控制影响。
- 不包含视频生成；只预留后续 Video Generation Interface 方向。
- 不包含 Multiplayer、完整 Combat、Economy 或传统 Quest System。
- 当前地点专属背景覆盖已知的 5 个地点；未来新生成的动态地点需要新的视觉资产或通用动态背景策略。

## Repository Status

`v0.1.0` 标签继续作为冻结稳定基线；GitHub `main` 包含当前 v0.2 PoC 展示能力。v0.2 仍是产品验证版本，不代表商业级完整游戏或新的冻结标签。
