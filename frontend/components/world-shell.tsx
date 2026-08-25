"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { API_BASE_URL, getWorldState } from "@/lib/api";
import type { InventoryEntry, WorldState } from "@/types/world";

import styles from "./world-shell.module.css";

const LOCATION_MOODS: Record<string, string> = {
  skeld_village: "Cold harbor settlement",
  stormcliff: "Wind-scoured sea cliffs",
  old_ruins: "Ancient stone remains",
  whispering_woods: "Wild forest territory",
};

function formatLabel(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function formatInventoryItem(item: InventoryEntry): string {
  if (typeof item === "string") return item;
  const name = item.name ?? item.id ?? "Unknown item";
  return item.quantity && item.quantity > 1
    ? `${name} × ${item.quantity}`
    : name;
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
      <p>Loading Dragon World...</p>
      <span>Synchronizing persistent state</span>
    </main>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <main className={styles.centeredState} role="alert">
      <div className={styles.errorMark} aria-hidden="true">
        !
      </div>
      <p>Dragon World API is offline.</p>
      <span>
        In development, confirm the Backend is running at {API_BASE_URL}.
      </span>
      <button className={styles.retryButton} type="button" onClick={onRetry}>
        Retry connection
      </button>
    </main>
  );
}

export function WorldShell() {
  const [worldState, setWorldState] = useState<WorldState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [actionInput, setActionInput] = useState("");
  const [consoleMessage, setConsoleMessage] = useState(
    "AI Action Pipeline — Connecting",
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

  function handleActionSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConsoleMessage("Action interaction will be connected in Step 5.4.3.");
  }

  if (loading) return <LoadingState />;
  if (failed || !worldState) {
    return <ErrorState onRetry={handleRetry} />;
  }

  const { player, world, current_location: location, nearby_npcs: nearbyNpcs } =
    worldState;
  const locationMood = LOCATION_MOODS[location.id] ?? "Dragon Isles territory";

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brandLockup}>
          <div className={styles.brandMark} aria-hidden="true">
            <span>DW</span>
          </div>
          <div>
            <p>AI World Engine</p>
            <h1>DRAGON WORLD</h1>
          </div>
        </div>

        <div className={styles.worldClock}>
          <div>
            <span>World cycle</span>
            <strong>
              Day {world.day} <i aria-hidden="true">·</i> {formatHour(world.hour)}
            </strong>
          </div>
          <div className={styles.onlineStatus}>
            <span aria-hidden="true" />
            World Online
          </div>
        </div>
      </header>

      <div className={styles.dashboard}>
        <aside className={`${styles.panel} ${styles.playerPanel}`}>
          <PanelTitle eyebrow="Player state" title={player.name ?? "Unnamed"} />

          <div className={styles.identityGrid}>
            <div>
              <span>Species</span>
              <strong>{formatLabel(player.species)}</strong>
            </div>
            <div>
              <span>Occupation</span>
              <strong>{formatLabel(player.occupation)}</strong>
            </div>
            <div className={styles.wideIdentity}>
              <span>Current location</span>
              <strong>{location.name}</strong>
            </div>
          </div>

          <section className={styles.listSection}>
            <h3>Goals</h3>
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
              <p className={styles.emptyState}>No goals recorded.</p>
            )}
          </section>

          <section className={styles.listSection}>
            <h3>Inventory</h3>
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
              <p className={styles.emptyState}>Empty</p>
            )}
          </section>
        </aside>

        <section className={styles.worldPanel}>
          <div className={styles.locationHeading}>
            <span>Current location</span>
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
              <span>{formatLabel(location.type)}</span>
              <strong>{formatLabel(world.weather)}</strong>
            </div>
          </div>

          <div className={styles.worldLog}>
            <div className={styles.logMarker} aria-hidden="true">
              01
            </div>
            <div>
              <span>World Log</span>
              <p>Current location: {location.name}</p>
            </div>
            <time>Day {world.day}</time>
          </div>
        </section>

        <aside className={`${styles.panel} ${styles.statePanel}`}>
          <PanelTitle eyebrow="Live state" title={world.name} />

          <div className={styles.weatherCard}>
            <span className={styles.weatherGlyph} aria-hidden="true">
              ≋
            </span>
            <div>
              <span>Weather</span>
              <strong>{formatLabel(world.weather)}</strong>
            </div>
          </div>

          <dl className={styles.factList}>
            <div>
              <dt>Day</dt>
              <dd>{world.day}</dd>
            </div>
            <div>
              <dt>Hour</dt>
              <dd>{formatHour(world.hour)}</dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>{location.name}</dd>
            </div>
          </dl>

          <section className={styles.nearbySection}>
            <h3>Nearby NPCs</h3>
            {nearbyNpcs.length ? (
              <div className={styles.npcList}>
                {nearbyNpcs.map((npc) => (
                  <article key={npc.id} className={styles.npcCard}>
                    <div aria-hidden="true">{npc.name.slice(0, 1)}</div>
                    <p>
                      <strong>{npc.name}</strong>
                      <span>{formatLabel(npc.occupation)}</span>
                    </p>
                  </article>
                ))}
              </div>
            ) : (
              <p className={styles.emptyState}>No one nearby.</p>
            )}
          </section>

          <details className={styles.developerView}>
            <summary>Developer View</summary>
            <ul>
              {[
                "Action Interpreter",
                "World Validator",
                "Action Executor",
                "Persistent State",
              ].map((service) => (
                <li key={service}>
                  <span>{service}</span>
                  <strong>Connected</strong>
                </li>
              ))}
            </ul>
            <p>Live pipeline telemetry arrives in Step 5.4.3.</p>
          </details>
        </aside>
      </div>

      <section className={styles.actionConsole}>
        <div className={styles.consoleHeading}>
          <span>Natural language action</span>
          <p aria-live="polite">{consoleMessage}</p>
        </div>
        <form onSubmit={handleActionSubmit}>
          <label htmlFor="action-input">What do you do?</label>
          <div className={styles.actionRow}>
            <textarea
              id="action-input"
              value={actionInput}
              onChange={(event) => setActionInput(event.target.value)}
              placeholder="Type anything you want to attempt..."
              rows={2}
            />
            <button type="submit" disabled={!actionInput.trim()}>
              <span>Send</span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
