export interface InventoryItem {
  id?: string;
  name?: string;
  quantity?: number;
}

export type InventoryEntry = string | InventoryItem;

export interface Player {
  id: string;
  player_id: string;
  name: string | null;
  display_name: string | null;
  species: string | null;
  occupation: string | null;
  current_location: string;
  goals: string[];
  inventory: InventoryEntry[];
  identity_initialized: boolean;
  identity_label: string | null;
  identity_summary: string;
}

export interface WorldInfo {
  name: string;
  day: number;
  hour: number;
  weather: string;
}

export interface Location {
  id: string;
  name: string;
  type: string;
}

export interface NPC {
  id: string;
  name: string;
  species: string;
  occupation: string;
}

export interface Dragon {
  dragon_id: string;
  name: string;
  appearance: {
    description?: string;
    distinctive_features?: string[];
    ecological_flavor?: string;
  };
  personality_traits: string[];
  behavior_state: string;
  taming_state: string;
  location: string;
  player_relationship: DragonRelationship | null;
}

export interface DragonRelationship {
  familiarity: number;
  trust: number;
  fear: number;
  bond: number;
  riding_unlocked: boolean;
}

export interface WorldState {
  player: Player;
  world: WorldInfo;
  current_location: Location;
  nearby_npcs: NPC[];
  nearby_dragons: Dragon[];
}
