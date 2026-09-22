export interface CharacterOrigin {
  identity: string;
  background: string;
  personality: string[];
  goal: string;
  narrative_direction: string;
  focus: string;
  epistemic_status: string;
  unverified_claims: string[];
}

export interface StoryEvent {
  event_id: string;
  event_type: string;
  title: string;
  narrative: string;
  reason: string;
  source_event_id: string;
  chapter: number;
  status: "open" | "resolved" | "deferred";
  location: { id: string; name: string };
  involved_entities: { id: string; name: string; type: string }[];
  choices: { id: string; label: string; input: string; consequence: string }[];
  consequences: Record<string, unknown>;
  evidence_refs: string[];
}

export interface NarrativeMemory {
  sequence: number;
  kind: string;
  summary: string;
  source_event_id: string | null;
  location_id: string;
  world_changes: Record<string, unknown>;
}

export interface PersonalStory {
  origin: CharacterOrigin;
  thread: { direction: string; branch: string; chapter: number };
  memories: NarrativeMemory[];
  recent_events: StoryEvent[];
  active_event: StoryEvent | null;
  npc_relationships: {
    npc_id: string; npc_name: string; familiarity: number; trust: number; attitude: string;
  }[];
  world_changes: NarrativeMemory[];
}

export interface StoryUpdate {
  status: "recorded" | "already_applied" | "failed" | "needs_clarification" | "no_change";
  event: StoryEvent | null;
  message: string;
}
