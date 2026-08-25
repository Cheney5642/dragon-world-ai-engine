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
