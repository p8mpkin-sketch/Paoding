// 写入只有一条路：POST …/proposals（与 pd 相同的提议通道）。每次提交生成一个 idem_key。
import { useCallback, useState } from "react";
import { ApiError, newIdemKey } from "../api/client";
import type { Op } from "../api/types";
import { useServices } from "../app/context";
import { pending, recorded, rejected } from "./feedback";

export type Accepted = { ok: true; id: string | null; seq: number };

export function useProposal(pid: string) {
  const { api } = useServices();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [done, setDone] = useState<Accepted[] | null>(null);
  const run = useCallback(
    async (ops: Op[], what = "提交"): Promise<Accepted[] | null> => {
      setBusy(true);
      setError(null);
      const t = pending(what);
      try {
        const r = await api.propose(pid, ops, newIdemKey());
        setDone(r);
        recorded(t, what, r.at(-1)?.seq ?? null);
        return r;
      } catch (e) {
        setError(e as Error);
        rejected(t, what, rejectText(e as Error) ?? (e as Error).message);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api, pid],
  );
  return { busy, error, done, run };
}

const CODE_HINT: Record<string, string> = {
  stale_view: "你看到的卡片已经过期",
  forbidden_op: "没有权限（检查人的令牌）",
  not_enabled: "图服务还没有启用这项功能",
  schema_error: "图服务不接受这个提议",
  unknown_ref: "引用的对象不存在",
};

/** 拒绝的说法：错误码原样给出，detail 是服务端的文字，按纯文本显示。 */
export const rejectText = (e: Error | null): string | null =>
  !e ? null
  : e instanceof ApiError && e.code ? `被拒：${e.code}（${CODE_HINT[e.code] ?? "见详情"}${e.detail ? `；${e.detail}` : ""}）`
  : `提交失败：${e.message}`;
