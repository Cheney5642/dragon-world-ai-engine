export interface InventoryItem {
  id?: string;
  name?: string;
  quantity?: number;
}

export type InventoryEntry = string | InventoryItem;

export interface Player {
  id: string;
  name: string | null;
  species: string;
  occupation: string | null;
  current_location: string;
  goals: string[];
  inventory: InventoryEntry[];
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

export interface WorldState {
  player: Player;
  world: WorldInfo;
  current_location: Location;
  nearby_npcs: NPC[];
}
