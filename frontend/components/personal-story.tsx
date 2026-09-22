"use client";

import type { PersonalStory as Story, StoryUpdate } from "@/types/story";
import type { SceneVisualResult } from "@/types/action";
import styles from "./personal-story.module.css";

const branches: Record<string, string> = {
  undecided: "故事正在展开", shared_path: "与他人同行", independent_path: "独自探索",
};

export function PersonalStoryPanel({ story, onChoose, busy, visual, update }: {
  story: Story; onChoose: (text: string) => void; busy: boolean;
  visual?: SceneVisualResult | null; update?: StoryUpdate | null;
}) {
  const active = story.active_event;
  return (
    <section className={styles.panel} aria-label="我的人生故事">
      <details className={styles.storyBook}>
        <summary className={styles.bookCover}>
          <span className={styles.scrollIcon} aria-hidden="true">
            <i className={styles.scrollSheet} />
            <i className={styles.scrollBack} />
            <i className={styles.scrollFront} />
          </span>
          <span className={styles.coverCopy}>
            <span>CHRONICLE OF THE NORTH</span>
            <strong>我的人生故事</strong>
            <small>{story.origin.identity} · {active?.title ?? "下一页，由你书写"}</small>
          </span>
          <span className={styles.bookMeta}>
            <span>{branches[story.thread.branch] ?? story.thread.branch} · {story.memories.length} 段经历</span>
            <small>展开卷册 <i aria-hidden="true">⌄</i></small>
          </span>
        </summary>

        <div className={styles.bookPages}>
          <div className={styles.columns}>
            <article className={styles.origin}>
              <span>我是谁 · 玩家自述</span><h3>{story.origin.identity}</h3>
              <p>{story.origin.background}</p>
              <p className={styles.traits}>{story.origin.personality.join(" · ") || "性格尚待你的行动展现"}</p>
              <dl><dt>我想去往何处</dt><dd>{story.origin.goal}</dd>
                <dt>可能的故事方向</dt><dd>{story.thread.direction}</dd></dl>
              {story.origin.unverified_claims.length ? <p className={styles.note}>自述中的外部经历仍待验证，不会直接授予世界地位或关系。</p> : null}
            </article>
            <article className={styles.event}>
              <span>世界因你的行动回应</span>
              <h3>{active?.title ?? "下一页，由你书写"}</h3>
              <p>{active?.narrative ?? "自由探索、拜访当地人，或追随自己的目标。你的重要选择会留在这里。"}</p>
              {active ? <>
                <details><summary>为什么这件事发生？</summary><p>{active.reason}</p></details>
                <div className={styles.choices}>{active.choices.map((choice) => (
                  <button type="button" key={choice.id} disabled={busy} onClick={() => onChoose(choice.input)}>
                    <strong>{choice.label} →</strong><small>{choice.consequence}</small>
                  </button>
                ))}</div>
                <p className={styles.note}>建议会填入行动框，你仍可改写。分享需要与明确的 NPC 同地点。</p>
              </> : null}
              {update ? <p className={styles.update} role="status">{update.message}</p> : null}
            </article>
          </div>
          <details className={styles.timeline} open>
            <summary>人生轨迹 · 已发生的经历</summary>
            <ol>{story.memories.slice(-12).map((memory) => (
              <li key={memory.sequence}><span>经历 {String(memory.sequence).padStart(2, "0")}</span><p>{memory.summary}</p></li>
            ))}</ol>
            <p className={styles.note}>按经历排序；世界时间尚未自动推进。普通聊天和未完成的愿望不会记为成就。</p>
          </details>
          <details className={styles.developer}>
            <summary>Developer View · 个人故事的依据</summary>
            <div className={styles.debugGrid}>
              {([
                ["Player Identity", story.origin], ["Narrative Thread", story.thread],
                ["World Changes", story.world_changes], ["NPC Relationship", story.npc_relationships],
                ["Recent Events", story.recent_events],
              ] as const).map(([label, data]) => <section key={label}><h4>{label}</h4><pre>{JSON.stringify(data, null, 2)}</pre></section>)}
              {visual ? <section><h4>Scene Description → Image Prompt</h4>
                <p>Provider: {visual.provider} · {visual.status}</p>
                <pre>{JSON.stringify(visual.scene_description, null, 2)}</pre><pre>{visual.image_prompt}</pre>
              </section> : null}
            </div>
          </details>
        </div>
      </details>
    </section>
  );
}
