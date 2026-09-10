import type { Dragon, Player } from "@/types/world";

export type FreeActionFamily =
  | "travel"
  | "explore"
  | "observe_search"
  | "interact"
  | "use_acquire"
  | "create_trade"
  | "conflict"
  | "rest_wait"
  | "other";

export interface ExplicitGoal {
  operation: "add" | "remove";
  goal: string;
}

export interface StructuredFreeAction {
  action_family: FreeActionFamily;
  action: string;
  target: string | null;
  destination: string | null;
  direction: string | null;
  intent: string | null;
  method: string | null;
  explicit_goal: ExplicitGoal | null;
  needs_clarification: boolean;
}

export type FreeActionStatus =
  | "success"
  | "partial"
  | "blocked"
  | "needs_clarification";

export type FreeActionEffectScope =
  | "narrative_only"
  | "player_state"
  | "domain_route";

export interface FreeActionResolution {
  status: FreeActionStatus;
  effect_scope: FreeActionEffectScope;
  reason_code: string | null;
  domain_route: "npc" | "dragon" | null;
  state_changes: {
    current_location?: string;
    goals?: string[];
  };
}

export interface ActionExecuteRequest {
  player_id: string;
  player_input: string;
}

export type DragonEncounterOutcome =
  | "none"
  | "trace"
  | "sighting"
  | "direct_encounter";

export interface DragonEncounterResult {
  outcome: DragonEncounterOutcome;
  is_final: boolean;
  requires_new_dragon: boolean;
  dragon_id: string | null;
  reason_code: string;
  context_score: number;
  roll: number;
  source: "existing" | "generated" | null;
  dragon: Dragon | null;
}

export interface DragonBondState {
  familiarity: number;
  trust: number;
  fear: number;
  bond: number;
  riding_unlocked: boolean;
}

export interface DragonInteractionSnapshot {
  familiarity: number;
  trust: number;
  fear: number;
  bond: number;
  taming_state: string;
}

export interface DragonInteractionResult {
  status: "applied" | "already_applied" | "blocked" | "needs_clarification";
  resolution_status:
    | "success"
    | "partial"
    | "blocked"
    | "needs_clarification";
  dragon_id: string | null;
  dragon_name: string | null;
  interaction_type: string | null;
  dragon_reaction: string | null;
  relationship_effect: "positive" | "neutral" | "negative";
  reason_code: string | null;
  positive_category: string | null;
  anti_farming: "full" | "familiarity_only" | "zero" | "not_applicable";
  applied_deltas: {
    familiarity: number;
    trust: number;
    fear: number;
    bond: number;
  };
  bond_state: DragonBondState | null;
  before: DragonInteractionSnapshot | null;
  after: DragonInteractionSnapshot | null;
  taming_state: string | null;
  taming_transition: { from: string; to: string } | null;
  player_message: string;
}

export interface ActionExecuteResponse {
  structured_action: StructuredFreeAction;
  resolution: FreeActionResolution;
  player_message: string;
  source_event_id: string;
  dragon_encounter: DragonEncounterResult;
  dragon_interaction: DragonInteractionResult | null;
}

export type ActionKind =
  | "speech"
  | "movement"
  | "interaction"
  | "observation"
  | "wait"
  | "self_expression"
  | "compound"
  | "other";

export interface ActionTarget {
  type: string;
  id: string | null;
  name: string | null;
}

export interface ActionStep {
  verb: string;
  target: ActionTarget | null;
  goal: string | null;
  method: string | null;
}

export interface ActionInterpretation {
  raw_input: string;
  action_kind: ActionKind;
  steps: ActionStep[];
  speech: string | null;
  claimed_facts: string[];
  requires_world_check: boolean;
  needs_clarification: boolean;
}

export type WorldValidationStatus =
  | "allowed"
  | "conditional"
  | "blocked"
  | "needs_clarification";

export type WorldValidationCheckStatus =
  | "supported"
  | "contradicted"
  | "unknown";

export interface WorldValidationCheck {
  fact: string;
  status: WorldValidationCheckStatus;
  evidence: string;
}

export interface WorldValidationResult {
  overall_status: WorldValidationStatus;
  checks: WorldValidationCheck[];
  missing_requirements: string[];
  conflicts: string[];
  requires_npc_decision: boolean;
  requires_further_resolution: boolean;
  validated_interpretation: string;
}

export type ActionExecutionType =
  | "movement"
  | "encounter"
  | "speech"
  | "unsupported";

export interface ResolvedEntity {
  entity_type: "player" | "npc" | "location";
  entity_id: string;
  name: string;
}

export interface ProposedMutation {
  entity_type: "player";
  entity_id: string;
  field: "current_location";
  old_value: string;
  new_value: string;
}

export interface ActionExecutionPlan {
  execution_type: ActionExecutionType;
  can_execute: boolean;
  resolved_entities: ResolvedEntity[];
  proposed_mutations: ProposedMutation[];
  execution_notes: string;
  requires_next_system: string | null;
}

export type PipelineStatus =
  | "needs_clarification"
  | "allowed"
  | "conditional"
  | "blocked"
  | "ready"
  | "unsupported"
  | "not_executable"
  | "no_mutation"
  | "committed";

export interface ActionPreviewResponse {
  interpretation: ActionInterpretation;
  validation: WorldValidationResult | null;
  execution_plan: ActionExecutionPlan | null;
  pipeline_status: PipelineStatus;
}

export interface ActionCommitResponse extends ActionPreviewResponse {
  committed: boolean;
  player: Player | null;
}
