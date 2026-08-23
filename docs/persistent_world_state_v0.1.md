# Persistent World State v0.1

## 基本概念

- **State（状态）**：世界在某个时刻的结构化事实快照，包括时间、地点、玩家、NPC 和全局指标。
- **Persistent State（持久状态）**：跨越多次程序运行仍被保存的 State。程序关闭后再次启动，世界应从上次保存的状态继续，而不是自动回到初始状态。
- **World Seed（世界初始模板）**：`data/world_seed.json`，代表 New Game 时 Dragon World 的标准初始状态。它是 immutable seed，不是运行中的游戏存档。
- **Save（存档）**：`data/saves/current_world.json`，代表当前游戏正在持续演化的 World State。未来玩家、NPC 和世界事件产生的合法变化都应发生在 Save 中。
- **Commit（提交）**：把经过 Schema、World Rules 和业务规则校验的状态变化正式写入 Save。这里的 Commit 指持久化世界变化，不是 Git commit。Step 4.1 只初始化 Save，尚未实现 Player Commit。

## 初始化流程

```text
data/world_seed.json
        ↓ New Game / init_save
data/saves/current_world.json
        ↓ future state mutations
持续演化的 Persistent World State
```

运行：

```text
python scripts/init_save.py
```

首次运行会从 Seed 创建独立的当前存档。如果存档已存在，默认不会覆盖。

需要明确开始一个全新世界时运行：

```text
python scripts/init_save.py --reset
```

`--reset` 只会用 Seed 替换 `data/saves/current_world.json`，不会修改 `data/world_seed.json`。

## 为什么不能直接修改 World Seed

World Seed 是可重复创建 New Game 的可信初始模板。如果正常游戏过程直接修改 Seed，玩家行为、NPC 变化或世界事件就会污染初始状态，之后无法可靠地创建一个全新的世界，也难以区分“设计好的初始事实”和“运行中发生的事实”。

因此运行时读取和修改的目标必须是 Save。Seed 只用于初始化或显式 reset。

## 为什么 v0.1 先使用 JSON Save

当前世界规模很小，只有一个本地存档，JSON 已经能够提供可读、可检查、可复制的持久化格式。它便于直接对照 Seed 和 Save，并快速验证状态生命周期。

数据库会引入连接、迁移、部署和运维复杂度。在尚未验证 Player Commit、状态校验和事件变更流程前，这些成本没有必要。未来当并发、多存档、查询性能或事务需求出现时，再评估数据库。
