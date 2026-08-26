import type { Player } from "@/types/world";

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
