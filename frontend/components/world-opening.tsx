"use client";

import { useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  DragonWorldBusinessError,
  DragonWorldHttpError,
  DragonWorldNetworkError,
  getWorldState,
  initializePlayerIdentity,
} from "@/lib/api";
import { UI_COPY } from "@/lib/ui-copy";
import type { WorldState } from "@/types/world";

import styles from "./world-opening.module.css";

type OpeningStep = "intro" | "identity_input";

interface WorldOpeningProps {
  playerId: string;
  onWorldReady: (world: WorldState) => void;
}

function identityErrorMessage(error: unknown): string {
  if (error instanceof DragonWorldNetworkError) {
    return UI_COPY.opening.networkError;
  }
  if (error instanceof DragonWorldBusinessError) {
    if (error.code === "invalid_self_description") {
      return UI_COPY.opening.inputRequired;
    }
    return UI_COPY.opening.genericError;
  }
  if (error instanceof DragonWorldHttpError) {
    if (error.status === 502) return UI_COPY.opening.interpretationError;
    if (error.status >= 500) return UI_COPY.opening.persistenceError;
  }
  return UI_COPY.opening.genericError;
}

export function WorldOpening({ playerId, onWorldReady }: WorldOpeningProps) {
  const submitInFlightRef = useRef(false);
  const [step, setStep] = useState<OpeningStep>("intro");
  const [selfDescription, setSelfDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshInitializedWorld(): Promise<void> {
    const latestWorld = await getWorldState();
    if (!latestWorld.player.identity_initialized) {
      throw new Error("Identity initialization was not visible on read-back.");
    }
    onWorldReady(latestWorld);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const description = selfDescription.trim();
    if (!description || submitting || submitInFlightRef.current) {
      if (!description) setError(UI_COPY.opening.inputRequired);
      return;
    }

    submitInFlightRef.current = true;
    setSubmitting(true);
    setError(null);

    try {
      const result = await initializePlayerIdentity({
        player_id: playerId,
        self_description: description,
      });
      if (
        result.status !== "initialized" &&
        result.status !== "already_initialized"
      ) {
        throw new Error("Unexpected identity initialization status.");
      }
      await refreshInitializedWorld();
    } catch (caught: unknown) {
      if (
        caught instanceof DragonWorldBusinessError &&
        caught.code === "identity_already_initialized"
      ) {
        try {
          await refreshInitializedWorld();
          return;
        } catch {
          setError(UI_COPY.opening.refreshError);
          return;
        }
      }
      setError(identityErrorMessage(caught));
    } finally {
      submitInFlightRef.current = false;
      setSubmitting(false);
    }
  }

  if (step === "intro") {
    return (
      <main className={styles.openingShell}>
        <div className={styles.atmosphere} aria-hidden="true">
          <span className={styles.horizon} />
          <span className={styles.dragonTrace} />
        </div>
        <section className={styles.introCard} aria-labelledby="opening-title">
          <div className={styles.brandMark} aria-hidden="true">
            DW
          </div>
          <p className={styles.eyebrow}>{UI_COPY.opening.chapter}</p>
          <h1 id="opening-title">{UI_COPY.opening.title}</h1>
          <div className={styles.storyCopy}>
            <p>{UI_COPY.opening.worldPrelude}</p>
            <p>{UI_COPY.opening.pathPrelude}</p>
            <p>{UI_COPY.opening.freedom}</p>
          </div>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={() => setStep("identity_input")}
          >
            <span>{UI_COPY.opening.enter}</span>
            <span aria-hidden="true">→</span>
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.openingShell}>
      <div className={styles.atmosphere} aria-hidden="true">
        <span className={styles.horizon} />
        <span className={styles.dragonTrace} />
      </div>
      <section className={styles.identityCard} aria-labelledby="identity-title">
        <div className={styles.arrivalCopy}>
          <p className={styles.eyebrow}>{UI_COPY.opening.arrivalLabel}</p>
          <h1>{UI_COPY.opening.arrivalTitle}</h1>
          <p className={styles.arrivalLead}>{UI_COPY.opening.arrivalLead}</p>
          <p>{UI_COPY.opening.arrivalScene}</p>
        </div>

        <form className={styles.identityForm} onSubmit={handleSubmit}>
          <div>
            <p className={styles.formIndex}>{UI_COPY.opening.identitySection}</p>
            <h2 id="identity-title">{UI_COPY.opening.identityPrompt}</h2>
            <p className={styles.formHint}>{UI_COPY.opening.identityHint}</p>
          </div>
          <label htmlFor="identity-description">
            {UI_COPY.opening.inputLabel}
          </label>
          <textarea
            id="identity-description"
            value={selfDescription}
            onChange={(event) => {
              setSelfDescription(event.target.value);
              setError(null);
            }}
            placeholder={UI_COPY.opening.placeholder}
            maxLength={4000}
            rows={7}
            disabled={submitting}
            autoFocus
          />
          <div className={styles.formFooter}>
            <span>{selfDescription.length} / 4000</span>
            <button
              className={styles.primaryButton}
              type="submit"
              disabled={!selfDescription.trim() || submitting}
            >
              {submitting ? UI_COPY.opening.submitting : UI_COPY.opening.start}
              {!submitting ? <span aria-hidden="true">→</span> : null}
            </button>
          </div>
          {error ? (
            <p className={styles.errorMessage} role="alert">
              {error}
            </p>
          ) : null}
        </form>
      </section>
    </main>
  );
}
