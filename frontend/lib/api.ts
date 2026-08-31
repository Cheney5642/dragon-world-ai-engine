import type {
  ActionCommitResponse,
  ActionPreviewResponse,
} from "@/types/action";
import { UI_COPY } from "@/lib/ui-copy";
import type {
  BackendErrorDetail,
  NpcCommitRequest,
  NpcCommitResponse,
  NpcInteractRequest,
  NpcInteractionResponse,
} from "@/types/npc";
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

export class DragonWorldNetworkError extends DragonWorldApiError {
  constructor(message: string) {
    super(message);
    this.name = "DragonWorldNetworkError";
  }
}

export class DragonWorldHttpError extends DragonWorldApiError {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "DragonWorldHttpError";
  }
}

export class DragonWorldBusinessError extends DragonWorldHttpError {
  constructor(
    message: string,
    status: number,
    public readonly code: string,
  ) {
    super(message, status);
    this.name = "DragonWorldBusinessError";
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
        UI_COPY.errors.http(response.status),
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
    throw new DragonWorldApiError(UI_COPY.errors.worldOffline);
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
        UI_COPY.errors.http(response.status),
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
    throw new DragonWorldApiError(UI_COPY.errors.worldOffline);
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

function isBackendErrorDetail(value: unknown): value is BackendErrorDetail {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const detail = value as Partial<BackendErrorDetail>;
  return (
    (detail.error_type === "business_rejection" ||
      detail.error_type === "system_error") &&
    typeof detail.code === "string" &&
    typeof detail.message === "string"
  );
}

async function readBackendError(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

type NpcApiPath =
  | "/api/npc/interact"
  | "/api/npc/memory/commit"
  | "/api/npc/relationship/commit";

async function postNpc<TRequest, TResponse>(
  path: NpcApiPath,
  request: TRequest,
  signal?: AbortSignal,
): Promise<TResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      const payload = (await readBackendError(response)) as
        | { detail?: unknown }
        | null;
      const detail = payload?.detail;
      if (
        isBackendErrorDetail(detail) &&
        detail.error_type === "business_rejection"
      ) {
        throw new DragonWorldBusinessError(
          detail.message,
          response.status,
          detail.code,
        );
      }

      throw new DragonWorldHttpError(
        isBackendErrorDetail(detail)
          ? detail.message
          : UI_COPY.errors.http(response.status),
        response.status,
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
    throw new DragonWorldNetworkError(UI_COPY.errors.worldOffline);
  }
}

export function interactWithNpc(
  request: NpcInteractRequest,
  signal?: AbortSignal,
): Promise<NpcInteractionResponse> {
  return postNpc<NpcInteractRequest, NpcInteractionResponse>(
    "/api/npc/interact",
    request,
    signal,
  );
}

export function commitNpcMemory(
  request: NpcCommitRequest,
  signal?: AbortSignal,
): Promise<NpcCommitResponse> {
  return postNpc<NpcCommitRequest, NpcCommitResponse>(
    "/api/npc/memory/commit",
    request,
    signal,
  );
}

export function commitNpcRelationship(
  request: NpcCommitRequest,
  signal?: AbortSignal,
): Promise<NpcCommitResponse> {
  return postNpc<NpcCommitRequest, NpcCommitResponse>(
    "/api/npc/relationship/commit",
    request,
    signal,
  );
}
