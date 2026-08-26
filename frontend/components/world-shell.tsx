"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  API_BASE_URL,
  commitAction,
  DragonWorldApiError,
  getWorldState,
  previewAction,
} from "@/lib/api";
import {
  ACTION_KIND_COPY,
  COMMIT_STATUS_COPY,
  displayLabel,
  EXECUTION_TYPE_COPY,
  LOCATION_MOOD_COPY,
  movementCommittedLog,
  PIPELINE_STATUS_COPY,
  UI_COPY,
  VALIDATION_CHECK_STATUS_COPY,
  VALIDATION_STATUS_COPY,
} from "@/lib/ui-copy";
import type { CommitUiStatus } from "@/lib/ui-copy";
import type { ActionPreviewResponse } from "@/types/action";
import type { InventoryEntry, WorldState } from "@/types/world";

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

function isCommitEligible(preview: ActionPreviewResponse): boolean {
  return (
    preview.pipeline_status === "ready" &&
    preview.validation?.overall_status === "allowed" &&
    preview.execution_plan?.can_execute === true &&
    preview.execution_plan.proposed_mutations.length > 0
  );
}

function needsNoPersistentMutation(preview: ActionPreviewResponse): boolean {
  return (
    preview.pipeline_status === "no_mutation" ||
    (preview.pipeline_status === "ready" &&
      preview.execution_plan?.can_execute === true &&
      preview.execution_plan.proposed_mutations.length === 0)
  );
}

function actionErrorMessage(error: unknown, fallback: string): string {
  return error instanceof DragonWorldApiError ? error.message : fallback;
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

function ActionPreviewPanel({
  preview,
  canConfirm,
  committing,
  onConfirm,
  onCancel,
}: {
  preview: ActionPreviewResponse;
  canConfirm: boolean;
  committing: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { interpretation, validation, execution_plan: plan } = preview;

  return (
    <section className={styles.previewPanel} aria-label={UI_COPY.preview.title}>
      <header className={styles.previewHeader}>
        <div>
          <span>{UI_COPY.preview.title}</span>
          <h3>{interpretation.raw_input}</h3>
        </div>
        <strong data-status={preview.pipeline_status}>
          {PIPELINE_STATUS_COPY[preview.pipeline_status]}
        </strong>
      </header>

      <div className={styles.previewGrid}>
        <article className={styles.previewCard}>
          <span>01 · {UI_COPY.preview.interpretation}</span>
          <h4>{ACTION_KIND_COPY[interpretation.action_kind]}</h4>
          <ol className={styles.stepList}>
            {interpretation.steps.map((step, index) => (
              <li key={`${step.verb}-${index}`}>
                <div>
                  <strong>{step.verb}</strong>
                  <span>
                    {step.target?.name ??
                      step.target?.id ??
                      UI_COPY.preview.noTarget}
                  </span>
                </div>
                {step.goal ? (
                  <p>
                    {UI_COPY.preview.goal}：{step.goal}
                  </p>
                ) : null}
                {step.method ? (
                  <p>
                    {UI_COPY.preview.method}：{step.method}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
          {interpretation.speech ? (
            <p className={styles.previewNote}>
              {UI_COPY.preview.speech}：“{interpretation.speech}”
            </p>
          ) : null}
          {interpretation.claimed_facts.length ? (
            <div className={styles.previewList}>
              <strong>{UI_COPY.preview.claimedFacts}</strong>
              <ul>
                {interpretation.claimed_facts.map((claim) => (
                  <li key={claim}>{claim}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </article>

        <article className={styles.previewCard}>
          <span>02 · {UI_COPY.preview.validation}</span>
          {validation ? (
            <>
              <h4>{VALIDATION_STATUS_COPY[validation.overall_status]}</h4>
              <p className={styles.previewNote}>
                {validation.validated_interpretation}
              </p>
              <div className={styles.previewList}>
                <strong>{UI_COPY.preview.checks}</strong>
                <ul>
                  {validation.checks.map((check, index) => (
                    <li key={`${check.fact}-${index}`}>
                      {check.fact} — {VALIDATION_CHECK_STATUS_COPY[check.status]}
                    </li>
                  ))}
                </ul>
              </div>
              {validation.conflicts.length ? (
                <div className={styles.previewList}>
                  <strong>{UI_COPY.preview.conflicts}</strong>
                  <ul>
                    {validation.conflicts.map((conflict) => (
                      <li key={conflict}>{conflict}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {validation.missing_requirements.length ? (
                <div className={styles.previewList}>
                  <strong>{UI_COPY.preview.missingRequirements}</strong>
                  <ul>
                    {validation.missing_requirements.map((requirement) => (
                      <li key={requirement}>{requirement}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : (
            <p className={styles.previewEmpty}>
              {UI_COPY.preview.validationNotReached}
            </p>
          )}
        </article>

        <article className={styles.previewCard}>
          <span>03 · {UI_COPY.preview.executionPlan}</span>
          {plan ? (
            <>
              <h4>{EXECUTION_TYPE_COPY[plan.execution_type]}</h4>
              <p className={styles.previewNote}>{plan.execution_notes}</p>
              <dl className={styles.planFacts}>
                <div>
                  <dt>{UI_COPY.preview.canExecute}</dt>
                  <dd>
                    {plan.can_execute ? UI_COPY.preview.yes : UI_COPY.preview.no}
                  </dd>
                </div>
                <div>
                  <dt>{UI_COPY.preview.mutations}</dt>
                  <dd>{plan.proposed_mutations.length}</dd>
                </div>
              </dl>
              {plan.proposed_mutations.length ? (
                <div className={styles.previewList}>
                  <strong>{UI_COPY.preview.proposedMutations}</strong>
                  <ul>
                    {plan.proposed_mutations.map((mutation, index) => (
                      <li key={`${mutation.field}-${index}`}>
                        {displayLabel(mutation.field)} · {UI_COPY.preview.before}：
                        {mutation.old_value} · {UI_COPY.preview.after}：
                        {mutation.new_value}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {plan.requires_next_system ? (
                <p className={styles.previewNote}>
                  {UI_COPY.preview.nextSystem}：{plan.requires_next_system}
                </p>
              ) : null}
            </>
          ) : (
            <p className={styles.previewEmpty}>
              {UI_COPY.preview.noExecutionPlan}
            </p>
          )}
        </article>
      </div>

      {needsNoPersistentMutation(preview) ? (
        <p className={styles.noMutationNotice}>
          {UI_COPY.preview.noPersistentMutation}
        </p>
      ) : null}

      <div className={styles.confirmControls}>
        {canConfirm || committing ? (
          <button type="button" onClick={onConfirm} disabled={committing}>
            {committing ? UI_COPY.preview.committing : UI_COPY.preview.confirm}
          </button>
        ) : null}
        <button
          className={styles.cancelButton}
          type="button"
          onClick={onCancel}
          disabled={committing}
        >
          {UI_COPY.preview.cancel}
        </button>
      </div>
    </section>
  );
}

export function WorldShell() {
  const commitInFlightRef = useRef(false);
  const [worldState, setWorldState] = useState<WorldState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [actionInput, setActionInput] = useState("");
  const [actionPreview, setActionPreview] =
    useState<ActionPreviewResponse | null>(null);
  const [previewedInput, setPreviewedInput] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [commitStatus, setCommitStatus] =
    useState<CommitUiStatus>("not_requested");
  const [worldLogMessage, setWorldLogMessage] = useState<string | null>(null);
  const [consoleMessage, setConsoleMessage] = useState<string>(
    UI_COPY.action.initialStatus,
  );

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
    const input = actionInput;
    if (!input.trim() || previewLoading || committing) return;

    setPreviewLoading(true);
    setActionError(null);
    setActionPreview(null);
    setPreviewedInput(null);
    setCommitStatus("not_requested");
    setConsoleMessage(UI_COPY.action.interpreting);

    try {
      const preview = await previewAction(input);
      setActionPreview(preview);
      setPreviewedInput(input);
      setCommitStatus(isCommitEligible(preview) ? "ready" : "not_requested");
      setConsoleMessage(
        UI_COPY.action.previewReady(
          PIPELINE_STATUS_COPY[preview.pipeline_status],
        ),
      );
    } catch (error: unknown) {
      setActionError(
        actionErrorMessage(error, UI_COPY.errors.previewFallback),
      );
      setConsoleMessage(UI_COPY.action.previewFailed);
    } finally {
      setPreviewLoading(false);
    }
  }

  function handleActionInputChange(value: string) {
    setActionInput(value);
    setActionError(null);
    if (!actionPreview && previewedInput === null) return;

    setActionPreview(null);
    setPreviewedInput(null);
    setCommitStatus("not_requested");
    setConsoleMessage(UI_COPY.action.changed);
  }

  function handleCancelPreview() {
    setActionPreview(null);
    setPreviewedInput(null);
    setActionError(null);
    setCommitStatus("not_requested");
    setConsoleMessage(UI_COPY.action.cancelled);
  }

  async function handleConfirmAction() {
    if (
      !actionPreview ||
      !previewedInput ||
      committing ||
      commitInFlightRef.current ||
      commitStatus !== "ready" ||
      !isCommitEligible(actionPreview)
    ) {
      return;
    }

    const committedInput = previewedInput;
    const previousLocation =
      worldState?.current_location.name ?? displayLabel(null);
    const playerName = worldState?.player.name ?? UI_COPY.player.unnamed;
    let serverCommitted = false;

    commitInFlightRef.current = true;
    setCommitting(true);
    setCommitStatus("committing");
    setActionError(null);
    setConsoleMessage(UI_COPY.action.revalidating);

    try {
      const result = await commitAction(committedInput);
      setActionPreview(result);

      if (!result.committed) {
        setPreviewedInput(null);
        setCommitStatus("not_committed");
        setConsoleMessage(
          UI_COPY.action.notCommitted(
            PIPELINE_STATUS_COPY[result.pipeline_status],
          ),
        );
        return;
      }

      serverCommitted = true;
      setCommitStatus("committed");
      const latestWorld = await getWorldState();
      setWorldState(latestWorld);
      setWorldLogMessage(
        movementCommittedLog(
          playerName,
          previousLocation,
          latestWorld.current_location.name,
        ),
      );
      setActionPreview(null);
      setPreviewedInput(null);
      setActionError(null);
      setActionInput("");
      setConsoleMessage(UI_COPY.action.commitSucceeded);
    } catch (error: unknown) {
      setCommitStatus(serverCommitted ? "committed" : "failed");
      setActionError(
        serverCommitted
          ? UI_COPY.errors.refreshAfterCommit
          : actionErrorMessage(error, UI_COPY.errors.commitFallback),
      );
      setConsoleMessage(
        serverCommitted
          ? UI_COPY.action.refreshFailed
          : UI_COPY.action.commitFailed,
      );
    } finally {
      commitInFlightRef.current = false;
      setCommitting(false);
    }
  }

  if (loading) return <LoadingState />;
  if (failed || !worldState) {
    return <ErrorState onRetry={handleRetry} />;
  }

  const { player, world, current_location: location, nearby_npcs: nearbyNpcs } =
    worldState;
  const locationMood =
    LOCATION_MOOD_COPY[location.id] ?? UI_COPY.world.fallbackMood;
  const canConfirm =
    actionPreview !== null &&
    previewedInput !== null &&
    commitStatus === "ready" &&
    isCommitEligible(actionPreview);

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
            title={player.name ?? UI_COPY.player.unnamed}
          />

          <div className={styles.identityGrid}>
            <div>
              <span>{UI_COPY.player.species}</span>
              <strong>{displayLabel(player.species)}</strong>
            </div>
            <div>
              <span>{UI_COPY.player.occupation}</span>
              <strong>{displayLabel(player.occupation)}</strong>
            </div>
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
                <dt>{UI_COPY.developer.pipelineStatus}</dt>
                <dd>
                  {actionPreview
                    ? PIPELINE_STATUS_COPY[actionPreview.pipeline_status]
                    : UI_COPY.developer.idle}
                </dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.validationStatus}</dt>
                <dd>
                  {actionPreview?.validation
                    ? VALIDATION_STATUS_COPY[
                        actionPreview.validation.overall_status
                      ]
                    : UI_COPY.developer.notRun}
                </dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.executionType}</dt>
                <dd>
                  {actionPreview?.execution_plan
                    ? EXECUTION_TYPE_COPY[
                        actionPreview.execution_plan.execution_type
                      ]
                    : UI_COPY.developer.notPlanned}
                </dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.mutationCount}</dt>
                <dd>
                  {actionPreview?.execution_plan?.proposed_mutations.length ?? 0}
                </dd>
              </div>
              <div>
                <dt>{UI_COPY.developer.commitStatus}</dt>
                <dd>{COMMIT_STATUS_COPY[commitStatus]}</dd>
              </div>
            </dl>
            <p>{UI_COPY.developer.metadataNote}</p>
          </details>
        </aside>
      </div>

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
              disabled={committing}
            />
            <button
              type="submit"
              disabled={!actionInput.trim() || previewLoading || committing}
            >
              <span>
                {previewLoading
                  ? UI_COPY.action.previewing
                  : UI_COPY.action.preview}
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
        {actionPreview ? (
          <ActionPreviewPanel
            preview={actionPreview}
            canConfirm={canConfirm}
            committing={committing}
            onConfirm={handleConfirmAction}
            onCancel={handleCancelPreview}
          />
        ) : null}
      </section>
    </main>
  );
}
