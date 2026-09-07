export interface IdentityInitializeRequest {
  player_id: string;
  self_description: string;
}

export type IdentityInitializeStatus = "initialized" | "already_initialized";

export interface IdentityInitializeResponse {
  status: IdentityInitializeStatus;
  player_id: string;
  display_name: string | null;
  identity_initialized: boolean;
  identity_summary: string;
}
