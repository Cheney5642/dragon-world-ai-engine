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
  opening: {
    chapter: "序章",
    title: "你在异世界重生了。",
    worldPrelude:
      "这里是北境世界，一个人与龙共舞的低魔世界。龙，是这片土地上最强大、最神秘，也最美丽的生物。",
    pathPrelude:
      "它们可能出现在暴风中的悬崖、森林深处、古老遗迹，或海岸之外无人知晓的土地。你可以寻找它们、了解它们、与它们建立羁绊，最终驾驭巨龙自由翱翔。",
    freedom:
      "你也可以走上一条完全不同的道路。这个世界没有规定你应该成为谁；你的来历、身份与愿望，将从你自己的讲述开始。",
    enter: "进入这个世界",
    arrivalLabel: "SKELD · 北境海岸",
    arrivalTitle: "你在 Skeld 醒来。",
    arrivalLead: "海风带着盐与寒意吹过你的脸。",
    arrivalScene:
      "远处的云层之间，一个巨大的黑影一闪而过。当你再次睁开眼睛时，你已经站在北境海岸的小村 Skeld。",
    identitySection: "01 · 开放身份",
    identityPrompt: "告诉这个世界：你是谁？",
    identityHint:
      "不用选择职业、种族或固定背景。用你自己的语言，描述你的名字、来历、性格、愿望，或任何你认为重要的事情。",
    inputLabel: "你的身份故事",
    placeholder:
      "我是一个从南方来到北境的哥布林商人，一直在寻找传说中的巨龙。",
    start: "开始我的故事",
    submitting: "世界正在聆听你的故事……",
    inputRequired: "请先告诉这个世界你是谁。",
    networkError: "暂时无法听见世界的回应。请确认后端在线后重试。",
    interpretationError: "世界暂时无法理解这段身份故事，请稍后再试。",
    persistenceError: "身份暂时无法写入这个世界，请稍后再试。",
    refreshError: "身份已提交，但世界状态尚未完成同步，请重试。",
    genericError: "身份初始化暂时失败。你的输入已保留，可以再次尝试。",
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
    identity: "身份",
    unknownIdentity: "身份未明",
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
    systems: [
      "D2-B Action Interpreter",
      "D2-C Action Resolution",
      "PostgreSQL Controlled Commit",
    ],
    connected: "已连接",
    resolutionStatus: "Resolution Status",
    effectScope: "Effect Scope",
    reasonCode: "Reason Code",
    mutationCount: "世界变化数量",
    idle: "空闲",
    notRun: "尚未运行",
    metadataNote: "只显示 /api/action/execute 返回的正式运行时数据。",
  },
  action: {
    section: "自然语言行动",
    initialStatus: "自由世界行动已就绪",
    label: "你想做什么？",
    placeholder: "输入你想尝试的任何行动……",
    preview: "预览行动",
    previewing: "正在预览……",
    execute: "采取行动",
    executing: "正在行动……",
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
    npcReady: (name: string) => `已切换至 ${name}，可以开始对话。`,
    npcTargetUnavailable: "目标 NPC 当前不在附近，未切换对话对象。",
  },
  npcDialogue: {
    section: "NPC 对话",
    panelHint: (name: string) => `与 ${name} 自然交谈`,
    noNpcSelected: "附近没有可对话角色",
    npcName: "对话角色",
    response: "NPC 回复",
    emptyResponse: (name?: string) =>
      name ? `向 ${name} 说点什么，开始本次对话。` : "当前没有可对话角色。",
    loading: (name?: string) => `${name ?? "NPC"} 正在回应……`,
    unavailableFallback: (name?: string) =>
      `${name ?? "该 NPC"} 当前无法与你互动。`,
    inputLabel: (name?: string) => `你想对 ${name ?? "NPC"} 说什么？`,
    placeholder: (name?: string) =>
      name ? `输入你想对 ${name} 说的话……` : "附近没有可对话角色",
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
  actionDeveloper: {
    title: "Developer View · Formal Action Result",
    structuredAction: "Structured Action",
    resolution: "Resolution",
    worldEffect: "World Effect",
    persistentMutation: "Persistent Mutation",
    noPersistentMutation: "No Persistent Mutation",
    routedToDragon: "Routed to Dragon Domain",
    routedToNpc: "Routed to NPC Domain",
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
