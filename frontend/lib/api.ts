import type {
  ActionCommitResponse,
  ActionPreviewResponse,
} from "@/types/action";
import type { WorldState } from "@/types/world";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

export class DragonWorldApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DragonWorldApiError";
  }
}

export async function getWorldState(signal?: AbortSignal): Promise<WorldState> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/world`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      throw new DragonWorldApiError(
        `Dragon World API returned HTTP ${response.status}.`,
      );
    }

    return (await response.json()) as WorldState;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    if (error instanceof DragonWorldApiError) {
      throw error;
    }
    throw new DragonWorldApiError("Dragon World API is offline.");
  }
}

async function postAction<TResponse>(
  path: "/api/action/preview" | "/api/action/commit",
  input: string,
  signal?: AbortSignal,
): Promise<TResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ input }),
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      throw new DragonWorldApiError(
        `Dragon World API returned HTTP ${response.status}.`,
      );
    }

    return (await response.json()) as TResponse;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    if (error instanceof DragonWorldApiError) {
      throw error;
    }
    throw new DragonWorldApiError("Dragon World API is offline.");
  }
}

export function previewAction(
  input: string,
  signal?: AbortSignal,
): Promise<ActionPreviewResponse> {
  return postAction<ActionPreviewResponse>(
    "/api/action/preview",
    input,
    signal,
  );
}

export function commitAction(
  input: string,
  signal?: AbortSignal,
): Promise<ActionCommitResponse> {
  return postAction<ActionCommitResponse>(
    "/api/action/commit",
    input,
    signal,
  );
}
