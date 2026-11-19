// 开题的提交路径（向导与导入共用）：先把还没存的文字或网址材料存成 Blob（本机算哈希核对），
// 再按 buildOpen 生成的批次原子开题；有初始提示的，开题成功后作为第一条 Hint 提交。
import { newIdemKey, type Api } from "../api/client";
import { ops } from "../api/ops";
import { sha256Hex } from "../model/hash";
import { buildOpen, textMaterial, type Draft } from "../model/wizard";
import { sealOps } from "../model/kaiti";
import type { ProblemInput } from "../api/types";
import type { KaitiVetted } from "../api/kaiti";

/** 把文字类材料存好，返回带哈希的新草稿。服务端回的哈希与本机算的不一致即失败。 */
export async function saveTextMaterials(api: Api, d: Draft): Promise<Draft> {
  const materials = await Promise.all(d.materials.map(async (m) => {
    if (m.hash || (m.kind ?? "file") === "file") return m;
    const t = textMaterial(m);
    if (!t) return m;
    const [put, local] = await Promise.all([api.putBlob(t.bytes), sha256Hex(t.bytes)]);
    if (put.hash !== local) throw new Error("服务端返回的哈希与本地计算的不一致");
    return { ...m, name: t.name, hash: local, size: t.bytes.length, media_type: t.media_type };
  }));
  return { ...d, materials };
}

export type SubmitResult = { pid: string; seq: number; hintSeq: number | null; hintError: string | null };

export async function submitDraft(api: Api, d0: Draft, idemKey = newIdemKey()): Promise<SubmitResult> {
  const d = await saveTextMaterials(api, d0);
  const open = buildOpen(d);
  const res = await api.openProblem(open.id, open.materials, open.problem, idemKey);
  const seq = res.at(-1)?.seq ?? 0;
  const hint = (d.hint ?? "").trim();
  if (!hint) return { pid: open.id, seq, hintSeq: null, hintError: null };
  try {
    const h = await api.propose(open.id, [ops.hintAdd(hint)], `${idemKey}-hint`);
    return { pid: open.id, seq, hintSeq: h[0]?.seq ?? null, hintError: null };
  } catch (e) {
    // 题已开出，Hint 失败不回滚开题；如实报告，人可到工作区再注入
    return { pid: open.id, seq, hintSeq: null, hintError: (e as Error).message };
  }
}

const utf8 = new TextEncoder();

/**
 * 一句话开题的提交（设计 §6）：与向导同一条提议通道。起草服务只给出批次，这里用人的令牌落地：
 * 先存题面等材料（本机算哈希，与服务端、与起草服务给的三方一致才继续），有答案时写保密库换回引用，最后原子开题。
 * answer 是人填在答案栏里的；没填而原文里有答案行时用起草服务回传的 secret。
 */
export async function submitVetted(api: Api, v: KaitiVetted, answer: string, idemKey = newIdemKey()): Promise<{ pid: string; seq: number }> {
  if (v.lane === "refuse" || !v.ops) throw new Error("这份草案没有通过校验，不能新建任务");
  for (const b of v.blobs) {
    const bytes = utf8.encode(b.text);
    const [put, local] = await Promise.all([api.putBlob(bytes), sha256Hex(bytes)]);
    if (put.hash !== local || local !== b.hash) throw new Error(`材料 ${b.name} 的哈希对不上：服务端、本机与起草结果须一致`);
  }
  let ref = null;
  if (v.has_answer) {
    const a = answer.trim() || v.secret || "";
    if (!a) throw new Error("有标准答案，但答案没有交到页面上");
    ref = await api.putVault(utf8.encode(a));
  }
  const ops = sealOps(v.ops, ref);
  const open = ops.at(-1)!;
  const res = await api.openProblem(v.pid, ops.slice(0, -1), open.body as unknown as ProblemInput, idemKey);
  return { pid: v.pid, seq: res.at(-1)?.seq ?? 0 };
}
