// 判据卡（HMI 设计 §3.3）：Goal、带判据的 Intent、观察类论断三处共用一个组件，
// 正如三者走同一条判定路径。任何显示"达成、通过、solved"的位置都由它或它的缩略徽章承载。
import type { Badge, Level, Predicate, Terminal } from "../api/types";
import { GRADE_WORD, LEVEL_GLYPH, levelWord, RESULT_GLYPH, TERMINAL_GLYPH, terminalWord } from "../model/levels";
import { shortHash } from "../model/text";
import { ArtifactChip, Plain, VaultRefView } from "./registers";

/** 形状记号：与文字并排，读屏器跳过。 */
export function Glyph({ g }: { g: string }) {
  return <span className="glyph" aria-hidden="true">{g}</span>;
}

/** 缩略徽章：至少带判官名与版本，点开即判据卡。 */
export function CriterionBadge({ badge, onOpen }: { badge: Badge | null; onOpen?: () => void }) {
  if (!badge) return <span className="badge badge-none" data-badge="none">无判据</span>;
  const text = `${badge.label}${badge.grade ? ` · ${GRADE_WORD[badge.grade]}` : ""}`;
  return onOpen ? (
    <button type="button" className="badge badge-criterion" data-badge="criterion" onClick={onOpen}>{text}</button>
  ) : (
    <span className="badge badge-criterion" data-badge="criterion">{text}</span>
  );
}

export function LevelBadge({ level, word }: { level: Level | null; word: string }) {
  if (!level) return null;
  return <span className={`badge level level-${level}`} data-level={level}><Glyph g={LEVEL_GLYPH[level]} />{level} {word}</span>;
}

/** 终态徽章：三值；必带判官徽章。accepted 写"人验收"。 */
export function TerminalBadge({ terminal, badge, level, onOpen }: { terminal: Terminal | null; badge: Badge; level: Level | null; onOpen?: () => void }) {
  return (
    <span className="terminal" data-terminal={terminal ?? "running"}>
      <span className="badge" data-terminal-word><Glyph g={TERMINAL_GLYPH[terminal ?? "running"]} />{terminalWord(terminal)}</span>
      <CriterionBadge badge={badge} onOpen={onOpen} />
      <span className="muted">根结论 {level ?? "—"}</span>
    </span>
  );
}

const RESULT_WORD = { pass: "通过", fail: "失败", inconclusive: "无结论" } as const;

export function CriterionCard({ p, seq }: { p: Predicate; seq: number }) {
  const keys = Object.keys(p.expect ?? {}).sort();
  return (
    <section className="criterion" data-criterion={p.target}>
      <header>
        <strong>判据</strong> <CriterionBadge badge={p} />
        <LevelBadge level={p.level} word={levelWord(p.level, p.level_word, p)} />
      </header>
      <dl className="kv">
        <dt>规格</dt>
        <dd>{p.spec_ref ? <>{p.spec_ref} · sha256 <code>{shortHash(p.spec_hash ?? "")}</code></> : "无 spec_ref"}</dd>
        <dt>expect</dt>
        <dd>
          {keys.length > 0 ? (
            <ul className="expect">{keys.map((k) => <li key={k}><code><Plain text={k} /></code> = <code><Plain text={JSON.stringify(p.expect[k])} /></code></li>)}</ul>
          ) : "无"}
        </dd>
        {p.sealed.length > 0 && (<><dt>含密级资产</dt><dd><VaultRefView refs={p.sealed} /></dd></>)}
        {p.max_attempts !== null && (<><dt>尝试</dt><dd>已用 {p.attempts_used ?? 0} / 上限 {p.max_attempts}</dd></>)}
      </dl>
      <h4>支持记录（裁决序列）</h4>
      {p.verdicts.length === 0 ? <p className="muted">尚无裁决</p> : (
        <ul className="tree">
          {p.verdicts.map((v) => (
            <li key={v.seq} data-verdict={v.result}>
              <details data-action="open-support">
                <summary><Glyph g={RESULT_GLYPH[v.result]} />seq {v.seq} · {v.judge}@{v.version} · {v.grade ? GRADE_WORD[v.grade] : "未定级"} · {RESULT_WORD[v.result]}{v.candidate ? ` · 候选 ${v.candidate}` : ""}</summary>
                <ul className="tree">
                  {v.evidence.map((a) => <ArtifactChip key={a} id={a} seq={seq} hint="判官输出" />)}
                  {v.candidate && <ArtifactChip id={v.candidate} seq={seq} hint="候选（authored）" />}
                </ul>
              </details>
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        {p.fail_means === "refuted" ? "这是一条论断：判官给出 fail 即证伪。" : "这是待达成的状态：判官给出 fail 即未达成，计一次尝试。"}
      </p>
    </section>
  );
}
