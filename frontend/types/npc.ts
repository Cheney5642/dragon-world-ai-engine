export interface NpcInteractRequest {
  npc_id: string;
  player_id: string;
  utterance: string;
}

export type NpcResponseType =
  | "answer"
  | "question"
  | "uncertain"
  | "disagreement"
  | "reaction"
  | "refusal";

export interface NpcResponsePreview {
  npc_id: string;
  response_type: NpcResponseType;
  speech: string;
  knowledge_status: string;
  requires_followup: boolean;
}

export type NpcRelationshipSignal =
  | "none"
  | "potential_positive"
  | "potential_negative";

export interface NpcInteractionEventSummary {
  event_id: string;
  npc_id: string;
  player_id: string;
  memory_candidate: boolean;
  relationship_signal: NpcRelationshipSignal;
}

export type NpcInteractionEvent = NpcInteractionEventSummary &
  Record<string, unknown>;

export interface NpcMemoryMutationPreview {
  candidate: boolean;
  preview: unknown | null;
  commit_available: boolean;
}

export interface NpcRelationshipMutationPreview {
  signal: NpcRelationshipSignal;
  preview: unknown | null;
  commit_available: boolean;
}

export interface NpcMutationPlan {
  event_id: string;
  npc_id: string;
  player_id: string;
  memory: NpcMemoryMutationPreview;
  relationship: NpcRelationshipMutationPreview;
  has_any_mutation: boolean;
}

export interface NpcInteractionResponse {
  interaction_available: boolean;
  unavailable_reason: string | null;
  npc_response: NpcResponsePreview | null;
  interaction_event: NpcInteractionEvent | null;
  mutation_plan: NpcMutationPlan | null;
}

export interface NpcCommitRequest {
  interaction_event: NpcInteractionEvent;
}

export interface NpcCommitResponse {
  event_id: string;
  domain: "memory" | "relationship";
  committed: boolean;
  record: Record<string, unknown>;
  cross_store_transaction: boolean;
}

export interface BackendErrorDetail {
  error_type: "business_rejection" | "system_error";
  code: string;
  message: string;
}
