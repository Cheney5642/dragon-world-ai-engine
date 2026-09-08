"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  API_BASE_URL,
  commitNpcMemory,
  commitNpcRelationship,
  DragonWorldApiError,
  executeAction,
  getWorldState,
  interactWithNpc,
} from "@/lib/api";
import {
  displayLabel,
  LOCATION_MOOD_COPY,
  UI_COPY,
} from "@/lib/ui-copy";
import type { ActionExecuteResponse } from "@/types/action";
import type { NpcInteractionResponse } from "@/types/npc";
import type { InventoryEntry, WorldState } from "@/types/world";

import { WorldOpening } from "./world-opening";
import styles from "./world-shell.module.css";

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function formatInventoryItem(item: InventoryEntry): string {
  if (typeof item === "string") return item;
  const name = item.name ?? item.id ?? UI_COPY.player.unknownItem;
  return item.quantity && item.quantity > 1
    ? `${name} × ${item.quantity}`
    : name;
}

function actionErrorMessage(error: unknown, fallback: string): string {
  return error instanceof DragonWorldApiError ? error.message : fallback;
}

async function persistNpcMutationsSilently(
  interaction: NpcInteractionResponse,
): Promise<void> {
  const event = interaction.interaction_event;
  const plan = interaction.mutation_plan;
  if (!event || !plan) return;

  const commits: Promise<unknown>[] = [];
  if (
    plan.memory.candidate &&
    plan.memory.commit_available &&
    plan.memory.preview !== null
  ) {
    commits.push(commitNpcMemory({ interaction_event: event }));
  }
  if (
    plan.relationship.commit_available &&
    plan.relationship.preview !== null
  ) {
    commits.push(commitNpcRelationship({ interaction_event: event }));
  }

  // Persistence is deliberately independent from dialogue rendering. Rejected
  // commits are handled here without turning a successful NPC reply into an error.
  if (commits.length > 0) await Promise.allSettled(commits);
}

function PanelTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className={styles.panelHeading}>
      <span>{eyebrow}</span>
      <h2>{title}</h2>
    </div>
  );
}

function LoadingState() {
  return (
    <main className={styles.centeredState} aria-live="polite">
      <div className={styles.loadingSigil} aria-hidden="true">
        <span>DW</span>
      </div>
      <p>{UI_COPY.loading.title}</p>
      <span>{UI_COPY.loading.detail}</span>
    </main>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <main className={styles.centeredState} role="alert">
      <div className={styles.errorMark} aria-hidden="true">
        !
      </div>
      <p>{UI_COPY.errors.worldOffline}</p>
      <span>{UI_COPY.errors.backendHint(API_BASE_URL)}</span>
      <button className={styles.retryButton} type="button" onClick={onRetry}>
        {UI_COPY.errors.retry}
      </button>
    </main>
  );
}

function ActionDeveloperView({ result }: { result: ActionExecuteResponse }) {
  const action = result.structured_action;
  const resolution = result.resolution;
  const hasStateChanges = Object.keys(resolution.state_changes).length > 0;
  const actionFields: Array<[string, string | boolean | null]> = [
    ["action", action.action],
    ["target", action.target],
    ["destination", action.destination],
    ["direction", action.direction],
    ["intent", action.intent],
    ["method", action.method],
    ["needs_clarification", action.needs_clarification],
  ];

  return (
    <details className={styles.actionDeveloperView}>
      <summary>{UI_COPY.actionDeveloper.title}</summary>
      <div className={styles.previewGrid}>
        <article className={styles.previewCard}>
          <span>01 · {UI_COPY.actionDeveloper.structuredAction}</span>
          <h4>{action.action_family}</h4>
          <dl className={styles.developerFacts}>
            {actionFields.map(([label, value]) =>
              value === null ? null : (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ),
            )}
          </dl>
          {action.explicit_goal ? (
            <p className={styles.previewNote}>
              explicit_goal: {action.explicit_goal.operation} · {action.explicit_goal.goal}
            </p>
          ) : null}
        </article>

        <article className={styles.previewCard}>
          <span>02 · {UI_COPY.actionDeveloper.resolution}</span>
          <h4>{resolution.status}</h4>
          <dl className={styles.developerFacts}>
            <div>
              <dt>effect_scope</dt>
              <dd>{resolution.effect_scope}</dd>
            </div>
            <div>
              <dt>reason_code</dt>
              <dd>{resolution.reason_code ?? "null"}</dd>
            </div>
            {resolution.domain_route ? (
              <div>
                <dt>domain_route</dt>
                <dd>{resolution.domain_route}</dd>
              </div>
            ) : null}
          </dl>
        </article>

        <article className={styles.previewCard}>
          <span>03 · {UI_COPY.actionDeveloper.worldEffect}</span>
          <h4>
            {hasStateChanges
              ? UI_COPY.actionDeveloper.persistentMutation
              : UI_COPY.actionDeveloper.noPersistentMutation}
          </h4>
          {resolution.state_changes.current_location ? (
            <p className={styles.previewNote}>
              current_location → {resolution.state_changes.current_location}
            </p>
          ) : null}
          {resolution.state_changes.goals ? (
            <div className={styles.previewList}>
              <strong>goals</strong>
              <ul>
                {resolution.state_changes.goals.map((goal) => (
                  <li key={goal}>{goal}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {resolution.domain_route ? (
            <p className={styles.domainRouteNotice}>
              {resolution.domain_route === "dragon"
                ? UI_COPY.actionDeveloper.routedToDragon
                : UI_COPY.actionDeveloper.routedToNpc}
            </p>
          ) : null}
        </article>
      </div>
    </details>
  );
}

export function WorldShell() {
  const actionInFlightRef = useRef(false);
  const [worldState, setWorldState] = useState<WorldState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [actionInput, setActionInput] = useState("");
  const [actionResult, setActionResult] =
    useState<ActionExecuteResponse | null>(null);
  const [actionRunning, setActionRunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [worldLogMessage, setWorldLogMessage] = useState<string | null>(null);
  const [consoleMessage, setConsoleMessage] = useState<string>(
    UI_COPY.action.initialStatus,
  );
  const [npcUtterance, setNpcUtterance] = useState("");
  const [npcInteraction, setNpcInteraction] =
    useState<NpcInteractionResponse | null>(null);
  const [npcSending, setNpcSending] = useState(false);
  const [npcError, setNpcError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    getWorldState(controller.signal)
      .then((state) => {
        setWorldState(state);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFailed(true);
        setLoading(false);
      });

    return () => controller.abort();
  }, [retryKey]);

  function handleRetry() {
    setLoading(true);
    setFailed(false);
    setRetryKey((value) => value + 1);
  }

  async function handleActionSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = actionInput.trim();
    if (!input || actionRunning || actionInFlightRef.current) return;

    actionInFlightRef.current = true;
    setActionRunning(true);
    setActionError(null);
    setActionResult(null);
    setConsoleMessage(UI_COPY.action.interpreting);

    try {
      const result = await executeAction({
        player_id: "player_001",
        player_input: input,
      });
      setActionResult(result);
      const latestWorld = await getWorldState();
      setWorldState(latestWorld);
      setWorldLogMessage(result.player_message);
      setActionInput("");
      setConsoleMessage(result.player_message);
    } catch (error: unknown) {
      setActionError(
        actionErrorMessage(error, UI_COPY.errors.commitFallback),
      );
      setConsoleMessage(UI_COPY.action.commitFailed);
    } finally {
      actionInFlightRef.current = false;
      setActionRunning(false);
    }
  }

  function handleActionInputChange(value: string) {
    setActionInput(value);
    setActionError(null);
    if (actionResult) setActionResult(null);
  }

  async function handleNpcSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const utterance = npcUtterance.trim();
    if (!utterance || npcSending) return;

    setNpcSending(true);
    setNpcError(null);
    setNpcInteraction(null);

    try {
      const interaction = await interactWithNpc({
        npc_id: "npc_astrid",
        player_id: "player_001",
        utterance,
      });
      setNpcInteraction(interaction);
      await persistNpcMutationsSilently(interaction);
    } catch (error: unknown) {
      setNpcError(actionErrorMessage(error, UI_COPY.errors.npcFallback));
    } finally {
      setNpcSending(false);
    }
  }

  if (loading) return <LoadingState />;
  if (failed || !worldState) {
    return <ErrorState onRetry={handleRetry} />;
  }
  if (!worldState.player.identity_initialized) {
    return (
      <WorldOpening
        playerId={worldState.player.player_id}
        onWorldReady={setWorldState}
      />
    );
  }

  const { player, world, current_location: location, nearby_npcs: nearbyNpcs } =
    worldState;
  const locationMood =
    LOCATION_MOOD_COPY[location.id] ?? UI_COPY.world.fallbackMood;
  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brandLockup}>
          <div className={styles.brandMark} aria-hidden="true">
            <span>DW</span>
          </div>
          <div>
            <p>{UI_COPY.brand.subtitle}</p>
            <h1>{UI_COPY.brand.name}</h1>
          </div>
        </div>

        <div className={styles.worldClock}>
          <div>
            <span>{UI_COPY.header.worldCycle}</span>
            <strong>
              {UI_COPY.header.dayAndHour(world.day, formatHour(world.hour))}
            </strong>
          </div>
          <div className={styles.onlineStatus}>
            <span aria-hidden="true" />
            {UI_COPY.header.worldOnline}
          </div>
        </div>
      </header>

      <div className={styles.dashboard}>
        <aside className={`${styles.panel} ${styles.playerPanel}`}>
          <PanelTitle
            eyebrow={UI_COPY.player.section}
            title={
              player.display_name ?? player.name ?? UI_COPY.player.unnamed
            }
          />

          <div className={styles.identityGrid}>
            {player.identity_initialized ? (
              <div className={styles.wideIdentity}>
                <span>{UI_COPY.player.identity}</span>
                <strong>
                  {player.identity_label ?? UI_COPY.player.unknownIdentity}
                </strong>
              </div>
            ) : (
              <>
                <div>
                  <span>{UI_COPY.player.species}</span>
                  <strong>{displayLabel(player.species)}</strong>
                </div>
                <div>
                  <span>{UI_COPY.player.occupation}</span>
                  <strong>{displayLabel(player.occupation)}</strong>
                </div>
              </>
            )}
            <div className={styles.wideIdentity}>
              <span>{UI_COPY.player.currentLocation}</span>
              <strong>{location.name}</strong>
            </div>
          </div>

          <section className={styles.listSection}>
            <h3>{UI_COPY.player.goals}</h3>
            {player.goals.length ? (
              <ul className={styles.goalList}>
                {player.goals.map((goal, index) => (
                  <li key={`${goal}-${index}`}>
                    <span aria-hidden="true" />
                    {goal}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.emptyState}>{UI_COPY.player.noGoals}</p>
            )}
          </section>

          <section className={styles.listSection}>
            <h3>{UI_COPY.player.inventory}</h3>
            {player.inventory.length ? (
              <ul className={styles.inventoryList}>
                {player.inventory.map((item, index) => (
                  <li
                    key={
                      typeof item === "string"
                        ? `${item}-${index}`
                        : item.id ?? index
                    }
                  >
                    {formatInventoryItem(item)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.emptyState}>
                {UI_COPY.player.emptyInventory}
              </p>
            )}
          </section>
        </aside>

        <section className={styles.worldPanel}>
          <div className={styles.locationHeading}>
            <span>{UI_COPY.world.currentLocation}</span>
            <h2>{location.name}</h2>
            <p>{locationMood}</p>
          </div>

          <div className={styles.scene} data-location={location.id}>
            <div className={styles.skyGlow} />
            <div className={styles.mistBack} />
            <div className={styles.distantLand} />
            <div className={styles.nearLand} />
            <div className={styles.sceneGrain} />
            <div className={styles.sceneBadge}>
              <span>{displayLabel(location.type)}</span>
              <strong>{displayLabel(world.weather)}</strong>
            </div>
          </div>

          <div className={styles.worldLog}>
            <div className={styles.logMarker} aria-hidden="true">
              01
            </div>
            <div>
              <span>{UI_COPY.world.log}</span>
              <p>
                {worldLogMessage ??
                  UI_COPY.world.currentLocationLog(location.name)}
              </p>
            </div>
            <time>{UI_COPY.world.dayLabel(world.day)}</time>
          </div>
        </section>

        <aside className={`${styles.panel} ${styles.statePanel}`}>
          <PanelTitle eyebrow={UI_COPY.world.liveState} title={world.name} />

          <div className={styles.weatherCard}>
            <span className={styles.weatherGlyph} aria-hidden="true">
              ≋
            </span>
            <div>
              <span>{UI_COPY.world.weather}</span>
              <strong>{displayLabel(world.weather)}</strong>
            </div>
          </div>

          <dl className={styles.factList}>
            <div>
              <dt>{UI_COPY.world.day}</dt>
              <dd>{world.day}</dd>
            </div>
            <div>
              <dt>{UI_COPY.world.hour}</dt>
              <dd>{formatHour(world.hour)}</dd>
            </div>
            <div>
              <dt>{UI_COPY.world.location}</dt>
              <dd>{location.name}</dd>
            </div>
          </dl>

          <section className={styles.nearbySection}>
            <h3>{UI_COPY.world.nearbyNpcs}</h3>
            {nearbyNpcs.length ? (
              <div className={styles.npcList}>
                {nearbyNpcs.map((npc) => (
                  <article key={npc.id} className={styles.npcCard}>
                    <div aria-hidden="true">{npc.name.slice(0, 1)}</div>
                    <p>
                      <strong>{npc.name}</strong>
                      <span>{displayLabel(npc.occupation)}</span>
                    </p>
                  </article>
                ))}
              </div>
            ) : (
              <p className={styles.emptyState}>
                {UI_COPY.world.noNearbyNpcs}
              </p>
            )}
          </section>

          <details className={styles.developerView}>
            <summary>{UI_COPY.developer.title}</summary>
            <ul>
              {UI_COPY.developer.systems.map((service) => (
                <li key={service}>
                  <span>{service}</span>
                  <strong>{UI_COPY.developer.connected}</strong>
                </li>
              ))}
            </ul>
            <dl className={styles.pipelineTelemetry}>
              <div>
                <dt>{UI_COPY.developer.resolutionStatus}</dt>
                <dd>
                  {actionResult?.resolution.status ?? UI_COPY.developer.idle}
                </dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.effectScope}</dt>
                <dd>{actionResult?.resolution.effect_scope ?? UI_COPY.developer.notRun}</dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.reasonCode}</dt>
                <dd>{actionResult?.resolution.reason_code ?? UI_COPY.developer.notRun}</dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.mutationCount}</dt>
                <dd>
                  {actionResult
                    ? Object.keys(actionResult.resolution.state_changes).length
                    : 0}
                </dd>
              </div>
            </dl>
            <p>{UI_COPY.developer.metadataNote}</p>
          </details>
        </aside>
      </div>

      <section className={styles.dialoguePanel}>
        <div className={styles.consoleHeading}>
          <span>{UI_COPY.npcDialogue.section}</span>
          <p>{UI_COPY.npcDialogue.panelHint}</p>
        </div>

        <div className={styles.dialogueIdentity}>
          <div aria-hidden="true">A</div>
          <p>
            <span>{UI_COPY.npcDialogue.npcName}</span>
            <strong>Astrid</strong>
          </p>
        </div>

        <div className={styles.dialogueResponse} aria-live="polite">
          <span>{UI_COPY.npcDialogue.response}</span>
          {npcInteraction?.interaction_available === false ? (
            <p className={styles.dialogueUnavailable}>
              {npcInteraction.unavailable_reason ??
                UI_COPY.npcDialogue.unavailableFallback}
            </p>
          ) : npcInteraction?.npc_response ? (
            <p>{npcInteraction.npc_response.speech}</p>
          ) : npcSending ? (
            <p>{UI_COPY.npcDialogue.loading}</p>
          ) : (
            <p className={styles.dialoguePlaceholder}>
              {UI_COPY.npcDialogue.emptyResponse}
            </p>
          )}
        </div>

        <form onSubmit={handleNpcSubmit}>
          <label htmlFor="npc-dialogue-input">
            {UI_COPY.npcDialogue.inputLabel}
          </label>
          <div className={styles.actionRow}>
            <textarea
              id="npc-dialogue-input"
              value={npcUtterance}
              onChange={(event) => {
                setNpcUtterance(event.target.value);
                setNpcError(null);
              }}
              placeholder={UI_COPY.npcDialogue.placeholder}
              rows={2}
              disabled={npcSending}
            />
            <button
              type="submit"
              disabled={!npcUtterance.trim() || npcSending}
            >
              <span>
                {npcSending
                  ? UI_COPY.npcDialogue.sending
                  : UI_COPY.npcDialogue.send}
              </span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>

        {npcError ? (
          <p className={styles.previewError} role="alert">
            {npcError}
          </p>
        ) : null}
      </section>

      <section className={styles.actionConsole}>
        <div className={styles.consoleHeading}>
          <span>{UI_COPY.action.section}</span>
          <p aria-live="polite">{consoleMessage}</p>
        </div>
        <form onSubmit={handleActionSubmit}>
          <label htmlFor="action-input">{UI_COPY.action.label}</label>
          <div className={styles.actionRow}>
            <textarea
              id="action-input"
              value={actionInput}
              onChange={(event) => handleActionInputChange(event.target.value)}
              placeholder={UI_COPY.action.placeholder}
              rows={2}
              disabled={actionRunning}
            />
            <button
              type="submit"
              disabled={!actionInput.trim() || actionRunning}
            >
              <span>
                {actionRunning
                  ? UI_COPY.action.executing
                  : UI_COPY.action.execute}
              </span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
        {actionError ? (
          <p className={styles.previewError} role="alert">
            {actionError}
          </p>
        ) : null}
        {actionResult ? <ActionDeveloperView result={actionResult} /> : null}
      </section>
    </main>
  );
}
