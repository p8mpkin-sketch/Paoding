// 开题的提交路径（向导与导入共用）：先把还没存的文字或网址材料存成 Blob（本机算哈希核对），
// 再按 buildOpen 生成的批次原子开题；有初始提示的，开题成功后作为第一条 Hint 提交。
import { newIdemKey, type Api } from "../api/client";
import { ops } from "../api/ops";
import { sha256Hex } from "../model/hash";
import { buildOpen, textMaterial, type Draft } from "../model/wizard";

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
