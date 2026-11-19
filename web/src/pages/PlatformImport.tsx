// 从平台导入（external-verdict §5.8 的主入口）：已登记的平台 → 任务清单（不领题）→ 领题（平台此刻开始计时）→
// 确认卡 → 创建任务。没有起草模型：字段都来自连接器档案、平台清单与说明；排版、出处都在服务端（qicao 的导入）。
// 外部判定的任务永远要人按“创建任务”：交付是对外动作，会消耗平台额度。
import { useEffect, useState } from "react";
import { newIdemKey } from "../api/client";
import type { KaitiVetted, PlatformEntry, PlatformTask } from "../api/kaiti";
import { useServices } from "../app/context";
import { navigate } from "../app/router";
import { submitVetted } from "../app/submit";
import { Mark, Mast, SectionHead, btnClass } from "../kit";
import { fieldWord, SOURCE, valueText, wallOf } from "../model/kaiti";
import { pending, recorded, rejected } from "../ui/feedback";
import { Plain } from "../ui/registers";
import { rejectText } from "../ui/useProposal";
import { Link } from "./Problems";

const errText = (e: unknown) => rejectText(e as Error) ?? (e as Error).message;

export function PlatformImport({ id }: { id?: string }) {
  const { api, cfg } = useServices();
  const writable = cfg.token !== null;
  const [plats, setPlats] = useState<PlatformEntry[] | null>(null);
  const [tasks, setTasks] = useState<PlatformTask[] | null>(null);
  const [card, setCard] = useState<KaitiVetted | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [usd, setUsd] = useState("");
  const [minutes, setMinutes] = useState("");

  useEffect(() => {
    if (!writable) return;
    api.platforms().then((x) => setPlats(x.items), (e) => setErr(errText(e)));
  }, [api, writable]);

  const chosen = plats?.find((p) => p.id === id) ?? (plats && plats.length === 1 && !id ? plats[0] : undefined);
  useEffect(() => {
    setTasks(null); setCard(null);
    if (!chosen) return;
    api.platformTasks(chosen.id).then((x) => setTasks(x.items), (e) => setErr(errText(e)));
  }, [api, chosen?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function claim(t: PlatformTask) {
    if (!chosen || busy) return;
    setBusy(t.task); setErr(null);
    const budget: { usd_milli?: number; wall_s?: number } = {};
    if (usd.trim()) budget.usd_milli = Math.round(Number(usd) * 1000);
    if (minutes.trim()) budget.wall_s = Math.round(Number(minutes) * 60);
    try {
      setCard(await api.platformImport(chosen.id, { task: t.task, ...(Object.keys(budget).length ? { budget } : {}) }));
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function create() {
    if (!card || busy) return;
    setBusy("open"); setErr(null);
    const toastId = pending("新建任务");
    try {
      const r = await submitVetted(api, card, "", newIdemKey());
      recorded(toastId, "新建任务", r.seq);
      navigate({ page: "problem", pid: r.pid, asOf: null, node: null });
    } catch (e) {
      setErr(errText(e));
      rejected(toastId, "新建任务", errText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="kaiti" data-platform-import>
      <Mast vol={["卷三", "新建"]} cap="从平台导入" title="判定权在外部平台的任务"
        dek="从已登记的平台领一个任务：题面、时限、提交额度都取自平台，完成与否看平台回执。领题那一刻平台开始计时。"
        actions={<div className="kt-links t2"><Link to={{ page: "new" }}>一句话新建</Link></div>} />

      {!writable && <p className="t2">领题与新建任务都要人的令牌：先在左下角配置。</p>}
      {err && <p className="error" data-reject><Plain text={err} /></p>}

      <section className="settings-sec" aria-labelledby="sec-plats">
        <SectionHead id="sec-plats" title="已登记的平台" note="档案在 judgebox/connectors.d；凭据在设置页的密钥槽位" />
        {plats === null ? <p className="t2">{writable ? "读取中…" : "—"}</p>
          : plats.length === 0 ? (
            <p className="t2" data-no-platform>还没有登记任何平台。把平台的连接器档案放进 judgebox/connectors.d，重启后在<Link to={{ page: "settings" }}>设置页</Link>设好它的凭据槽位。</p>
          ) : (
            <ul className="key-slots" data-platforms>
              {plats.map((p) => (
                <li key={p.id} data-platform={p.id}>
                  <Link to={{ page: "platform", id: p.id }}><span className="k-mono"><Plain text={`${p.id}@${p.version}`} /></span></Link>
                  {" "}<span className="t2">判定器 {p.judges.join("、") || "—"} · 凭据{p.slot_set ? "已设" : `未设（槽位 ${p.slot}）`}</span>
                </li>
              ))}
            </ul>
          )}
      </section>

      {chosen && !card && (
        <section className="settings-sec" aria-labelledby="sec-tasks">
          <SectionHead id="sec-tasks" title={<>平台 <span className="k-mono"><Plain text={chosen.id} /></span> 的任务</>} note="列清单不领题；按“领题”平台才开始计时" />
          <div className="kt-num" data-budget>
            <label>成本上限 $<input inputMode="decimal" value={usd} onChange={(e) => setUsd(e.target.value)} placeholder="按先验" aria-label="成本上限（美元，可空）" /></label>
            {" "}<label>花费墙钟<input inputMode="decimal" value={minutes} onChange={(e) => setMinutes(e.target.value)} placeholder="按先验" aria-label="花费墙钟上限（分钟，可空）" />分钟</label>
            <span className="t2">平台时限另进截止时刻，不占这两项</span>
          </div>
          {tasks === null ? <p className="t2">读取中…</p> : (
            <table className="bank" data-platform-tasks><tbody>
              {tasks.map((t) => (
                <tr key={t.task} data-task={t.task}>
                  <td className="k-mono"><Plain text={t.task} /></td>
                  <td><Plain text={t.title} /></td>
                  <td className="t2">{t.time_limit_s ? `时限 ${wallOf(t.time_limit_s)}` : ""}{t.max_submissions ? ` · 最多交 ${t.max_submissions} 次` : ""}</td>
                  <td><button type="button" className={btnClass("line", "sm")} data-action="claim" disabled={!writable || busy !== null} onClick={() => void claim(t)}>{busy === t.task ? "领题中…" : "领题"}</button></td>
                </tr>
              ))}
            </tbody></table>
          )}
        </section>
      )}

      {card && card.input && (
        <div className="kt-card" data-kaiti-card>
          <SectionHead title={<Plain text={card.input.title} />} note={<>任务编号 <span className="k-mono"><Plain text={card.pid} /></span> · 已领题</>} />
          <dl className="kt-rows">
            {card.derivation.map((r, i) => (
              <div key={`${r.field}-${i}`} className="kt-row" data-field={r.field}>
                <dt>{fieldWord(r.field)}</dt>
                <dd><span className="kt-val"><Plain text={valueText(r)} /></span> <Mark ch={SOURCE[r.source].ch} tone={SOURCE[r.source].tone} label={SOURCE[r.source].word} />
                  {r.note && <span className="t2 kt-note"><Plain text={r.note} /></span>}</dd>
              </div>
            ))}
          </dl>
          <div className="sheet-sub">为什么要你看</div>
          <ol className="kt-why">
            {card.notes.map((n, i) => <li key={`${n.code}-${i}`} data-note={n.code}><span className="k-mono">{String(i + 1).padStart(2, "0")}</span> <Plain text={n.text} /></li>)}
          </ol>
          <footer className="wizard-foot">
            <button type="button" className={btnClass("ink")} data-action="open-problem" disabled={busy !== null || !writable} onClick={() => void create()}>
              {busy === "open" ? "创建中…" : "创建任务"}
            </button>
            <button type="button" className={btnClass("bare")} data-action="discard" disabled={busy !== null} onClick={() => setCard(null)}>放弃（平台那边的计时不受影响）</button>
          </footer>
        </div>
      )}
    </div>
  );
}
