// 任务页“结果”一栏（v5 第三期；地图 Q30）。开放道：最后一次交付的答案、主张与依据、自检、没验证的、要你补的；
// 历次交付与追问按序号排在下面。判定道与人工验收道：沿用结构化报告（ResultReport）。
// 只排版 status.goal 的原样字段：内核只校验“引用是真的”，不校验结论对不对，页面也不替它判。
import * as Dialog from "@radix-ui/react-dialog";
import { CircleAlert, CornerDownLeft, ShieldOff, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { KnChunk } from "../api/knowledge-types";
import type { ArtifactView, Delivery, GroundBrief, Review } from "../api/types";
import { useServices } from "../app/context";
import { btnClass } from "../kit";
import type { ViewModel } from "../model/viewmodel";
import { CopyButton, Prose } from "./Prose";
import { ArtifactCard, Plain, Text } from "./registers";
import { ResultReport } from "./ResultReport";

const OUTCOME_WORD: Record<Delivery["outcome"], string> = { answered: "完整回答", partial: "部分完成", blocked: "受阻" };
const CHECK_WORD = { pass: "通过", fail: "没做到", skipped: "没做" } as const;

/** 引用的资料（资料库第二期）：资料名、位置、当时的原文（登记时进 Blob 的那一份，不随资料更新而换）。
 * 资料之后有了新的可用版本时只提示，不替换原文。 */
function KnowledgeCard({ a }: { a: ArtifactView }) {
  const { api } = useServices();
  const [text, setText] = useState<string | null>(null);
  const [now, setNow] = useState<KnChunk | null>(null);
  const [gone, setGone] = useState(false);
  const kn = a.knowledge;
  useEffect(() => {
    let live = true;
    api.blob(a.hash).then((b) => live && setText(new TextDecoder("utf-8", { fatal: false }).decode(b)), () => live && setText(""));
    if (kn) api.knChunk(kn.chunk).then((c) => live && setNow(c), () => live && setGone(true));
    return () => { live = false; };
  }, [api, a.hash, kn]);
  return (
    <div className="tk-kn reg-human" data-register="human" data-knowledge={kn?.chunk ?? ""}>
      <dl className="tk-kn-meta">
        <div><dt>资料</dt><dd><Plain text={now?.source_name ?? kn?.source ?? ""} /><span className="t2 k-mono"> · 第 {kn?.revision} 版</span></dd></div>
        {kn?.locator && <div><dt>位置</dt><dd><Plain text={kn.locator} /></dd></div>}
      </dl>
      <blockquote className="tk-kn-text">{text === null ? <span className="t2">读取原文…</span> : <Plain text={text} />}</blockquote>
      <p className="tk-kn-note" data-kn-note>这是你给的资料里的话，没有在这次任务里验证。</p>
      {now?.newer_revision && <p className="tk-tag need" data-kn-newer>这份资料之后更新过；这里是引用时的原文。</p>}
      {gone && <p className="t2" data-kn-gone>资料已不在知识页（可能已删掉或清掉）；这里是引用时的原文。</p>}
    </div>
  );
}

/** 证据下钻：点一条依据，右侧抽屉里给出那次执行的命令、输出与哈希（ArtifactCard，与检视同一张卡）。 */
/** 一份登记记录的正文（证据抽屉与文件栏的预览共用）。 */
export function ArtifactPreview({ id, seq }: { id: string; seq: number }) {
  const { api } = useServices();
  const [a, setA] = useState<ArtifactView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setA(null); setErr(null);
    let live = true;
    api.artifact(id, seq).then((r) => live && setA(r), (e: Error) => live && setErr(e.message));
    return () => { live = false; };
  }, [api, id, seq]);
  if (!a) return <p className="t2">{err ? <>取不到登记记录：<Plain text={err} /></> : "读取中…"}</p>;
  return (
    <>
      {a.class === "knowledge" ? <KnowledgeCard a={a} /> : <ArtifactCard a={a} />}
      <p className="t2" data-file-trust>{a.class === "exec" || a.class === "judge" ? "由执行层登记，模型改不了它，可以作依据。" : a.class === "authored" ? "会话写的，不能作依据。" : a.class === "input" ? "你给的材料。" : "引用的资料：按“人”的语域排，不是执行证据。"}</p>
    </>
  );
}

export function EvidenceDrawer({ id, seq, onClose }: { id: string | null; seq: number; onClose: () => void }) {
  const { api } = useServices();
  const [a, setA] = useState<ArtifactView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setA(null); setErr(null);
    if (!id) return;
    let live = true;
    api.artifact(id, seq).then((r) => live && setA(r), (e: Error) => live && setErr(e.message));
    return () => { live = false; };
  }, [api, id, seq]);
  return (
    <Dialog.Root open={id !== null} onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="k-overlay" />
        <Dialog.Content className="tk-drawer" data-evidence={id ?? ""} aria-describedby={undefined}>
          <header>
            <Dialog.Title className="tk-drawer-h">{a?.class === "exec" ? "执行记录" : a?.class === "knowledge" ? "引用的资料" : "登记的内容"}<span className="tk-ref on">{id}</span></Dialog.Title>
            <Dialog.Close className={btnClass("bare", "sm")} aria-label="关闭"><X aria-hidden="true" /></Dialog.Close>
          </header>
          <div className="tk-drawer-b">
            {a?.class === "knowledge" ? <KnowledgeCard a={a} /> : a ? <ArtifactCard a={a} /> : <p className="t2">{err ? <>取不到登记记录：<Plain text={err} /></> : "读取中…"}</p>}
            {a?.class === "exec" && <p className="t2">这条记录由执行层自动登记，模型改不了它。</p>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Refs({ refs, onRef }: { refs: GroundBrief[]; onRef: (id: string) => void }) {
  return <span className="tk-refs">{refs.map((r) => <button key={r.id} type="button" className={`tk-ref${r.class === "knowledge" ? " kn" : ""}`} data-ref={r.id} data-ref-class={r.class} onClick={() => onRef(r.id)}>{r.class === "knowledge" ? `资料 ${r.id}` : r.id}</button>)}</span>;
}

/** 答案正文：会话写的（authored）按叙述语域放；取 Blob 解成文字。 */
function Answer({ id, seq }: { id: string; seq: number }) {
  const { api } = useServices();
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.artifact(id, seq).then((a) => api.blob(a.hash)).then(
      (b) => live && setText(new TextDecoder("utf-8", { fatal: false }).decode(b)),
      (e: Error) => live && setErr(e.message),
    );
    return () => { live = false; };
  }, [api, id, seq]);
  return (
    <div className="tk-ans reg-narrative" data-register="narrative" data-answer={id}>
      <header className="tk-ans-h"><span className="reg-label">模型撰写</span><span className="t2">答案</span><span className="grow" />{text !== null && <CopyButton text={text} label="复制答案全文" />}</header>
      {text === null ? <p className="t2">{err ? <>取不到答案：<Plain text={err} /></> : "读取答案…"}</p> : <Prose text={text} />}
    </div>
  );
}

const VERDICT_WORD = { supported: "有据", unsupported: "引用不符", unclear: "看不出" } as const;
const RERUN_WORD = { pass: "重跑通过", fail: "重跑不过", not_rerun: "没能重跑" } as const;

/** 复核读数（地图 Q34）：另一个会话逐条核过这次交付。读数由确定性代码数出；逐条意见是复核会话写的（叙述），
 * 不是判定，不改变任务的状态。 */
function ReviewView({ r, d, onRef }: { r: Review; d: Delivery; onRef: (id: string) => void }) {
  const n = r.readings;
  const rr = n.reruns;
  const reran = rr.pass + rr.fail + rr.not_rerun;
  return (
    <section className="tk-sec tk-review" data-review={r.id} tabIndex={-1}>
      <h2>独立复核<small data-review-readings>{n.claims} 条主张里 {n.supported} 条有据、{n.unsupported} 条引用不符、{n.unclear} 条看不出{reran > 0 && <>；自检重跑 {rr.pass} 过、{rr.fail} 不过、{rr.not_rerun} 条没能重跑</>}{n.counterexamples > 0 && <>；{n.counterexamples} 条反例</>}</small></h2>
      <p className="tk-review-note t2">另起一个会话，没有参与求解，只读交付与留档逐条核对。这是参考读数，不是判定，不改变任务的状态。</p>
      <div className="reg-narrative" data-register="narrative"><span className="reg-label">复核会话撰写</span><Text t={r.summary} block={false} /></div>
      <ul className="tk-li">
        {r.claims.map((c) => (
          <li key={`c${c.claim}`} data-review-claim={c.claim} data-verdict={c.verdict}>
            <span className={`tk-res rv-${c.verdict}`}>{VERDICT_WORD[c.verdict]}</span>
            <span className="grow"><span className="t2">主张 {c.claim + 1}</span>{d.claims[c.claim] && <> · <Text t={d.claims[c.claim].text} block={false} /></>}<br /><Text t={c.note} block={false} /></span>
            {c.refs.length > 0 && <Refs refs={c.refs} onRef={onRef} />}
          </li>
        ))}
        {r.reruns.map((x) => (
          <li key={`r${x.check}`} data-review-rerun={x.check} data-rerun={x.result}>
            <span className={`tk-res rv-${x.result}`}>{RERUN_WORD[x.result]}</span>
            <span className="grow"><span className="t2">自检 {x.check + 1}</span>{d.self_check[x.check] && <> · <Text t={d.self_check[x.check].what} block={false} /></>}{x.note && <><br /><Text t={x.note} block={false} /></>}</span>
            {x.refs.length > 0 && <Refs refs={x.refs} onRef={onRef} />}
          </li>
        ))}
        {r.counterexamples.map((t, i) => (
          <li key={`x${i}`} data-counterexample={i}><span className="tk-res rv-unsupported">反例</span><span className="grow"><Text t={t} block={false} /></span></li>
        ))}
      </ul>
    </section>
  );
}

/** 跳到本次交付里的一节（概要条上的数字点过来）：滚到那一节并把焦点放上去，读屏器接着往下读。 */
function jump(from: HTMLElement, sel: string) {
  const el = from.closest("[data-delivery]")?.querySelector<HTMLElement>(sel);
  if (!el) return;
  el.scrollIntoView?.({ block: "start" });
  el.focus({ preventScroll: true });
}

/** “没有经过独立判定”：这次交付有多少是有据的，一眼看全。数字都是数出来的（交付登记的字段），不是页面的判断。 */
function SelfVerdict({ d, backed, cited }: { d: Delivery; backed: number; cited: number }) {
  const pass = d.self_check.filter((c) => c.result === "pass").length;
  const stat = (key: string, sel: string, num: ReactNode, word: string, tone = "") => (
    <li key={key}><button type="button" className={`tk-vstat ${tone}`} data-jump={key} onClick={(e) => jump(e.currentTarget, sel)}><b className="num">{num}</b><span>{word}</span></button></li>
  );
  return (
    <aside className="tk-verdict" data-verdict="self" data-outcome={d.outcome} aria-label="判定状态">
      <ShieldOff className="tk-verdict-ic" aria-hidden="true" />
      <div className="tk-verdict-t">
        <b>没有经过独立判定</b>
        <span>以上是智能体自己的结论（{OUTCOME_WORD[d.outcome]}）。下面是它实际跑过的依据，和它没验证的地方。</span>
      </div>
      <ul className="tk-verdict-nums" aria-label="这次交付的概要">
        {d.needs.length > 0 && stat("needs", "[data-needs]", d.needs.length, "件事要你补", "need")}
        {d.claims.length > 0 && stat("claims", "[data-claims]", <>{backed}<i>/{d.claims.length}</i></>, cited > 0 ? `条依据有执行记录，${cited} 条引用资料` : "条依据有执行记录", backed < d.claims.length ? "warn" : "ok")}
        {d.self_check.length > 0 && stat("self-check", "[data-self-check]", <>{pass}<i>/{d.self_check.length}</i></>, "项自查通过", pass < d.self_check.length ? "warn" : "ok")}
        {d.unverified.length > 0 && stat("unverified", "[data-unverified]", d.unverified.length, "处没验证", "warn")}
        {d.review ? stat("review", "[data-review]", "有", "独立复核的读数") : <li><span className="tk-vstat off"><b>无</b><span>独立复核</span></span></li>}
      </ul>
    </aside>
  );
}

function DeliveryView({ d, seq, onRef, onReply }: { d: Delivery; seq: number; onRef: (id: string) => void; onReply?: (() => void) | undefined }) {
  // “N 条里 M 条有执行记录”只数执行记录与材料；引用资料另计“K 条引用了资料”，不进 M（cz 验收附加条件 1）
  const backed = d.claims.filter((c) => c.supported).length;
  const cited = d.claims.filter((c) => c.cited).length;
  return (
    <div className="tk-delivery" data-delivery={d.id} data-outcome={d.outcome}>
      {d.answer && <Answer id={d.answer} seq={seq} />}
      <SelfVerdict d={d} backed={backed} cited={cited} />
      {d.needs.length > 0 && (
        <section className="tk-sec tk-needs" data-needs tabIndex={-1} aria-labelledby={`${d.id}-needs`}>
          <header className="tk-needs-h">
            <CircleAlert aria-hidden="true" />
            <h2 id={`${d.id}-needs`}>要你补的<span className="tk-ct need">{d.needs.length}</span></h2>
            <p>{d.outcome === "blocked" ? "它卡在这里了：补上这些，它才能接着做。" : "补上这些，它可以把剩下的做完。"}</p>
          </header>
          <ol className="tk-needs-l">
            {d.needs.map((n, i) => (
              <li key={i} data-need={i}>
                <span className="tk-mk need" aria-hidden="true">{i + 1}</span>
                <span className="grow"><Text t={n} block={false} /></span>
              </li>
            ))}
          </ol>
          {onReply && (
            <footer className="tk-needs-f">
              <button type="button" className={btnClass("line", "sm")} data-action="reply-needs" onClick={onReply}><CornerDownLeft aria-hidden="true" />在下面的输入框里补上</button>
              <span className="t2">补充会作为追问交给它，它接着之前的工作区做。</span>
            </footer>
          )}
        </section>
      )}
      {d.claims.length > 0 && (
        <section className="tk-sec" data-claims tabIndex={-1}>
          <h2>依据<small data-claims-count>{d.claims.length} 条里 {backed} 条有执行记录{cited > 0 && <span data-cited-count>；{cited} 条引用了资料</span>}</small></h2>
          <ul className="tk-li">
            {d.claims.map((c, i) => (
              <li key={i} data-claim={i} data-supported={c.supported} data-cited={c.cited}>
                <span className="tk-mk">{i + 1}</span><span className="grow"><Text t={c.text} block={false} />{c.cited && !c.supported && <span className="tk-tag kn">只有资料，没有执行记录</span>}</span>
                {c.refs.length > 0 ? <Refs refs={c.refs} onRef={onRef} /> : <span className="tk-tag need">没有执行记录</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {d.self_check.length > 0 && (
        <section className="tk-sec" data-self-check tabIndex={-1}>
          <h2>它自己查过的</h2>
          <ul className="tk-li">
            {d.self_check.map((c, i) => (
              <li key={i} data-check={c.result}>
                <span className={`tk-res ${c.result}`}>{CHECK_WORD[c.result]}</span><span className="grow"><Text t={c.what} block={false} />{c.item && <span className="t2"> · 新建时登记的 {c.item}</span>}</span>
                {c.refs.length > 0 && <Refs refs={c.refs} onRef={onRef} />}
              </li>
            ))}
          </ul>
        </section>
      )}
      {d.unverified.length > 0 && (
        <section className="tk-sec" data-unverified tabIndex={-1}>
          <h2>没验证的<small>{d.unverified.length} 处</small></h2>
          <ul className="tk-li">{d.unverified.map((u, i) => <li key={i}><span className="tk-mk dot" aria-hidden="true" /><Text t={u} block={false} /></li>)}</ul>
        </section>
      )}
      {d.review && <ReviewView r={d.review} d={d} onRef={onRef} />}
    </div>
  );
}

const FEEDBACK_WORD = { adopted: "你采纳了这次交付", rejected: "你没有采纳这次交付", none: "关闭任务时没有给反馈" } as const;

export function TaskResult({ vm, onReply }: { vm: ViewModel; onReply?: (() => void) | undefined }) {
  const [ref, setRef] = useState<string | null>(null);
  const o = vm.open;
  if (vm.goal.accept !== "open") return vm.closed ? <ResultReport vm={vm} /> : <p className="t2">还没有结果。</p>;
  const last = o.deliveries.at(-1);
  if (!last) return <p className="t2" data-result-empty>{vm.closed ? "这个任务结束时没有交付。" : "还没有交付。做完会在这里给出答案、依据和它没验证的地方。"}</p>;
  // 历次交付与追问按序号交错排：最后一次交付展开在上，之前的收起
  const rounds = [...o.deliveries.slice(0, -1).map((d) => ({ seq: d.seq, d })), ...o.followUps.map((u) => ({ seq: u.seq, u }))].sort((a, b) => b.seq - a.seq);
  const asked = o.followUps.filter((u) => u.seq > last.seq);
  return (
    <div className="tk-result" data-result data-open-result>
      {vm.closed && o.feedback && <p className="tk-fb" data-feedback={o.feedback}>{FEEDBACK_WORD[o.feedback]}。</p>}
      {asked.length > 0 && <div className="tk-fb" data-asked>你在这次交付之后追问了：<Text t={asked.at(-1)!.text} block={false} />。它正接着之前的工作区做，做完会再交一次。</div>}
      <DeliveryView d={last} seq={vm.seq} onRef={setRef} onReply={onReply} />
      {rounds.length > 0 && (
        <section className="tk-sec" data-rounds>
          <h2>之前的几轮</h2>
          <ul className="tk-li">
            {rounds.map((r) => "d" in r && r.d ? (
              <li key={r.seq}><details><summary>seq {r.seq} 交付 · {OUTCOME_WORD[r.d.outcome]}</summary><DeliveryView d={r.d} seq={vm.seq} onRef={setRef} /></details></li>
            ) : "u" in r && r.u ? (
              <li key={r.seq} data-follow-up={r.u.id}><span className="tk-mk you">问</span><span className="grow">seq {r.seq} 你追问：<Text t={r.u.text} block={false} /></span></li>
            ) : null)}
          </ul>
        </section>
      )}
      <EvidenceDrawer id={ref} seq={vm.seq} onClose={() => setRef(null)} />
    </div>
  );
}
