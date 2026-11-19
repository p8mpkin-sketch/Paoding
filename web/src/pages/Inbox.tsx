// 待办（收件箱）：所有在跑任务里等人处理的事，集中在一页。
// 数据：/v1/problems 里 human_todo > 0 的任务，再逐个读 /work 的 human 项；类别取服务端给的 why，前端不推断。
import { useEffect, useState } from "react";
import type { HumanWorkItem, ProblemItem } from "../api/types";
import { useServices } from "../app/context";
import { runningOf } from "../model/dashboard";
import { Empty, Mark, Mast, SectionHead, btnClass } from "../kit";
import { HAS_CARD, WHY } from "../ui/Todo";
import { Plain, Text } from "../ui/registers";
import { Link, useProblems } from "./Problems";

export const INBOX_POLL_MS = 8000;

/** 待办类别的单字印。 */
const WHY_MARK: Record<string, string> = { needs_human: "批", extension: "续", dispute: "裁", closeout: "验", stalled: "停" };

type Group = { p: ProblemItem; items: HumanWorkItem[] | null; error: string | null };

export function Inbox() {
  const { api } = useServices();
  const { view, error } = useProblems(INBOX_POLL_MS);
  const [groups, setGroups] = useState<Group[] | null>(null);
  const key = view ? `${view.head}|${runningOf(view.items).filter((p) => p.human_todo > 0).map((p) => `${p.id}:${p.human_todo}`).join("|")}` : null;

  useEffect(() => {
    if (!view || key === null) return;
    let live = true;
    const ps = runningOf(view.items).filter((p) => p.human_todo > 0);
    Promise.all(ps.map((p) => api.work(p.id).then(
      (w) => ({ p, items: w.items.filter((x): x is HumanWorkItem => x.kind === "human"), error: null }),
      (e: Error) => ({ p, items: null, error: e.message }),
    ))).then((g) => { if (live) setGroups(g); });
    return () => { live = false; };
    // 链头或待办数变了才重读
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key]);

  if (!view) return <p className={error ? "error" : "muted"}>{error ? <>读不到任务列表：<Plain text={error} /></> : "读取中…"}</p>;
  const total = runningOf(view.items).reduce((a, p) => a + p.human_todo, 0);
  return (
    <div className="inbox" data-page="inbox">
      <Mast vol={["卷二", "待办"]} cap="待办" title={total > 0 ? `${total} 件事等你处理` : "没有事等你处理"} dek="审批、续期、争议裁决、验收与停滞，都集中在这里。点“去处理”进入任务的工作区，卡片在左栏打开。" />
      {error && <p className="error">刷新失败，显示的是上一次读到的：<Plain text={error} /></p>}
      {total === 0 ? (
        <Empty title="都处理完了">任务需要你拍板时（例如要扩大授权范围、预算将尽要续期、判定有争议），会出现在这里，左侧栏的“待办”也会标出数量。</Empty>
      ) : !groups ? <p className="muted">读取每个任务的待办…</p> : groups.map(({ p, items, error: e }) => (
        <section key={p.id} className="today-sec" data-inbox-problem={p.id}>
          <SectionHead title={<Text t={p.title} block={false} />} note={<span className="k-mono">{p.id}</span>} right={<Link to={{ page: "problem", pid: p.id, asOf: null, node: null }} className="k-link">打开工作区</Link>} />
          {e ? <p className="error">读不到这个任务的待办：<Plain text={e} /></p> : (
            <ol className="asks">
              {(items ?? []).map((t) => (
                <li key={`${t.why}:${t.target}`} className="ask-row" data-inbox-item={`${t.why}:${t.target}`}>
                  <Mark ch={WHY_MARK[t.why] ?? "待"} tone="dai" />
                  <div className="grow">
                    <div>{WHY[t.why] ?? t.why} · <span className="k-mono">{t.target}</span></div>
                    <div className="t2">{HAS_CARD.has(t.why) ? "在工作区左栏的待办里打开卡片处理" : "网页暂不处理这一类，请用 pd"}</div>
                  </div>
                  <Link to={{ page: "problem", pid: p.id, asOf: null, node: t.target }} className={btnClass("line", "sm")}>去处理</Link>
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  );
}
