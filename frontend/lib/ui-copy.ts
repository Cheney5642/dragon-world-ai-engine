import type {
  ActionExecutionType,
  ActionKind,
  PipelineStatus,
  WorldValidationCheckStatus,
  WorldValidationStatus,
} from "@/types/action";

export type CommitUiStatus =
  | "not_requested"
  | "ready"
  | "committing"
  | "committed"
  | "not_committed"
  | "failed";

export const PIPELINE_STATUS_COPY: Record<PipelineStatus, string> = {
  needs_clarification: "需要玩家确认",
  allowed: "世界校验通过",
  conditional: "需要进一步处理",
  blocked: "行动被阻止",
  ready: "可以执行",
  unsupported: "当前世界暂不支持",
  not_executable: "当前无法执行",
  no_mutation: "不产生持久世界变化",
  committed: "已执行",
};

export const VALIDATION_STATUS_COPY: Record<WorldValidationStatus, string> = {
  allowed: "允许",
  conditional: "需要进一步处理",
  blocked: "行动被阻止",
  needs_clarification: "需要玩家确认",
};

export const VALIDATION_CHECK_STATUS_COPY: Record<
  WorldValidationCheckStatus,
  string
> = {
  supported: "已支持",
  contradicted: "存在冲突",
  unknown: "未知",
};

export const ACTION_KIND_COPY: Record<ActionKind, string> = {
  speech: "对话",
  movement: "移动",
  interaction: "互动",
  observation: "观察",
  wait: "等待",
  self_expression: "自我表达",
  compound: "复合行动",
  other: "其他",
};

export const EXECUTION_TYPE_COPY: Record<ActionExecutionType, string> = {
  movement: "移动",
  encounter: "相遇",
  speech: "对话",
  unsupported: "暂不支持",
};

export const COMMIT_STATUS_COPY: Record<CommitUiStatus, string> = {
  not_requested: "未请求",
  ready: "等待确认",
  committing: "正在执行",
  committed: "已执行",
  not_committed: "未写入",
  failed: "执行失败",
};

const KNOWN_VALUE_COPY: Record<string, string> = {
  cloudy: "多云",
  human: "人类",
  dragon: "龙",
  village: "村庄",
  wild_area: "荒野",
  ruins: "遗迹",
  forest: "森林",
  current_location: "当前位置",
  blacksmith: "铁匠",
  "blacksmith apprentice": "铁匠学徒",
  fisherman: "渔民",
  guard: "守卫",
  "dragon tamer": "驯龙师",
  merchant: "商人",
  "fisherman's daughter": "渔夫之女",
};

export const LOCATION_MOOD_COPY: Record<string, string> = {
  skeld_village: "寒冷的海港村落",
  stormcliff: "强风侵蚀的临海峭壁",
  old_ruins: "沉寂的古代石质遗迹",
  whispering_woods: "野生动物与龙类栖息的森林",
};

export const UI_COPY = {
  brand: {
    name: "DRAGON WORLD",
    subtitle: "AI 世界引擎",
  },
  loading: {
    title: "正在加载 Dragon World……",
    detail: "正在同步持久世界状态",
  },
  errors: {
    worldOffline: "Dragon World API 当前离线。",
    backendHint: (baseUrl: string) =>
      `开发模式下，请确认后端服务正在运行：${baseUrl}`,
    retry: "重试连接",
    previewFallback: "无法生成行动预览。",
    commitFallback: "无法执行本次行动。",
    refreshAfterCommit: "行动已执行，但无法刷新最新世界状态。",
    npcFallback: "无法获得 NPC 回复。",
    http: (status: number) => `Dragon World API 返回 HTTP ${status}。`,
  },
  header: {
    worldCycle: "世界周期",
    dayAndHour: (day: number, hour: string) => `第 ${day} 天 · ${hour}`,
    worldOnline: "世界在线",
  },
  player: {
    section: "玩家状态",
    unnamed: "未命名角色",
    species: "种族",
    occupation: "职业",
    currentLocation: "当前位置",
    goals: "目标",
    noGoals: "尚未记录目标。",
    inventory: "物品栏",
    emptyInventory: "空",
    unknownItem: "未知物品",
  },
  world: {
    currentLocation: "当前位置",
    fallbackMood: "Dragon Isles 区域",
    log: "世界日志",
    currentLocationLog: (location: string) => `当前位置：${location}`,
    liveState: "世界状态",
    weather: "天气",
    day: "天数",
    hour: "时间",
    location: "位置",
    nearbyNpcs: "附近角色",
    noNearbyNpcs: "附近没有其他角色。",
    dayLabel: (day: number) => `第 ${day} 天`,
  },
  developer: {
    title: "开发者视图",
    systems: ["动作解释器", "世界校验器", "行动执行器", "持久世界状态"],
    connected: "已连接",
    pipelineStatus: "流水线状态",
    validationStatus: "校验状态",
    executionType: "执行类型",
    mutationCount: "世界变化数量",
    commitStatus: "状态写入",
    idle: "空闲",
    notRun: "尚未运行",
    notPlanned: "尚未规划",
    metadataNote: "仅显示经过校验的流水线元数据。",
  },
  action: {
    section: "自然语言行动",
    initialStatus: "AI 行动流水线 · 仅预览",
    label: "你想做什么？",
    placeholder: "输入你想尝试的任何行动……",
    preview: "预览行动",
    previewing: "正在预览……",
    interpreting: "正在理解行动……",
    previewReady: (status: string) => `预览完成 · ${status}`,
    previewFailed: "行动预览失败",
    changed: "输入已改变 · 请重新预览",
    cancelled: "已取消预览 · 存档未修改",
    revalidating: "服务器正在重新校验并执行行动……",
    notCommitted: (status: string) => `行动未写入 · ${status}`,
    commitSucceeded: "行动已执行 · 世界状态已刷新",
    refreshFailed: "世界状态刷新失败",
    commitFailed: "行动执行失败",
  },
  npcDialogue: {
    section: "NPC 对话",
    panelHint: "与 Astrid 自然交谈",
    npcName: "对话角色",
    response: "NPC 回复",
    emptyResponse: "向 Astrid 说点什么，开始本次对话。",
    loading: "Astrid 正在回应……",
    unavailableFallback: "Astrid 当前无法与你互动。",
    inputLabel: "你想对 Astrid 说什么？",
    placeholder: "输入你想对 Astrid 说的话……",
    send: "发送",
    sending: "发送中……",
  },
  preview: {
    title: "行动流水线预览",
    interpretation: "动作解释",
    noTarget: "无明确目标",
    goal: "目标",
    method: "方式",
    speech: "说话内容",
    claimedFacts: "事实主张",
    validation: "世界校验",
    checks: "校验项",
    conflicts: "冲突",
    missingRequirements: "缺少条件",
    validationNotReached: "本次预览尚未进入世界校验阶段。",
    executionPlan: "执行计划",
    canExecute: "可以执行",
    mutations: "世界变化",
    yes: "是",
    no: "否",
    proposedMutations: "候选世界变化",
    before: "变化前",
    after: "变化后",
    nextSystem: "下一处理系统",
    noExecutionPlan: "本次预览没有生成执行计划。",
    noPersistentMutation: "无需写入持久世界状态。",
    confirm: "确认执行",
    committing: "正在执行……",
    cancel: "取消",
  },
} as const;

export function displayLabel(value: string | null | undefined): string {
  if (!value) return "未知";
  return (
    PIPELINE_STATUS_COPY[value as PipelineStatus] ??
    VALIDATION_STATUS_COPY[value as WorldValidationStatus] ??
    VALIDATION_CHECK_STATUS_COPY[value as WorldValidationCheckStatus] ??
    ACTION_KIND_COPY[value as ActionKind] ??
    EXECUTION_TYPE_COPY[value as ActionExecutionType] ??
    COMMIT_STATUS_COPY[value as CommitUiStatus] ??
    KNOWN_VALUE_COPY[value] ??
    value.replaceAll("_", " ")
  );
}

export function movementCommittedLog(
  playerName: string,
  fromLocation: string,
  toLocation: string,
): string {
  return `${playerName} 从 ${fromLocation} 移动到了 ${toLocation}。`;
}
