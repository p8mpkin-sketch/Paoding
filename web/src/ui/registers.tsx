// 四语域的呈现组件（HMI 设计 §3.4）。三重编码：字体、边框、文字标签；不靠颜色。
//   证据      等宽、实线框、哈希徽章、命令行与退出码在首行
//   叙述      引文样式、左侧竖线、标签"模型撰写"
//   人的判断  作者与时间在首行、标签"人"
//   估值      小号、"≈"前缀，不与等级同框
// 语域取自服务端给每段内容标的 register（由出处类别查表），这里只认它，不看内容。
// 没有接受裸字符串的证据组件：证据框只能由 Artifact 登记记录渲染出来。
import { useEffect, useState, type ReactNode } from "react";
import type { ArtifactView, Tagged, VaultRef } from "../api/types";
import { useServices, fmtTs } from "../app/context";
import { countUsage } from "../app/usage";
import { sha256Hex } from "../model/hash";
import { isEvidence, registerOf, REGISTER_LABEL } from "../model/register";
import { headTail, shortHash, visible } from "../model/text";

/** 一切来自日志的文本都经它显示：纯文本节点，不解析 Markdown、HTML，不把网址变成链接。 */
export function Plain({ text }: { text: string }) {
  return <span className="plain">{visible(text)}</span>;
}

type Meta = { author?: string; ts?: number | null; note?: string; what?: string };

/** 一段带语域的内容。样式只由 t.register 决定。 */
export function Text({ t, block = true, meta = {} }: { t: Tagged<string | number>; block?: boolean; meta?: Meta }) {
  const reg = registerOf(t.register);
  const value = String(t.value);
  switch (reg) {
    case "narrative": {
      const Tag = block ? "blockquote" : "q";
      return (
        <Tag className="reg reg-narrative" data-register="narrative" data-src={t.src}>
          <span className="reg-label">{REGISTER_LABEL.narrative}</span>
          <Plain text={value} />
        </Tag>
      );
    }
    case "human":
      return (
        <div className="reg reg-human" data-register="human" data-src={t.src}>
          <div className="reg-human-head">
            <span className="reg-label">{REGISTER_LABEL.human}</span>
            {meta.author !== undefined && <Plain text={meta.author} />}
            {meta.ts !== undefined && meta.ts !== null && <span> · {fmtTs(meta.ts)}</span>}
            {meta.note && <span> · {meta.note}</span>}
          </div>
          <Plain text={value} />
        </div>
      );
    case "estimate":
      return (
        <small className="reg reg-estimate" data-register="estimate" data-src={t.src}>
          <span className="reg-label">{REGISTER_LABEL.estimate}</span>
          {meta.what ?? "估值"} ≈<Plain text={value} />
        </small>
      );
    case "evidence":
      // 行内的证据文字（目前服务端不会给出这种内容；留着是为了不把它错显示成别的语域）
      return (
        <code className="reg reg-evidence-inline" data-register="evidence" data-src={t.src}>
          <span className="reg-label">{REGISTER_LABEL.evidence}</span>
          <Plain text={value} />
        </code>
      );
  }
}

export function VaultRefView({ refs }: { refs: VaultRef[] }) {
  return (
    <ul className="vault">
      {refs.map((r) => (
        <li key={r.vault}>
          vault:<Plain text={r.vault} /> · digest {shortHash(r.digest)} · 内容不显示
        </li>
      ))}
    </ul>
  );
}

type Verify = "idle" | "running" | "match" | "mismatch" | "error";

/** 哈希徽章 + 本地校验：浏览器取回 Blob，本地算 sha256 与登记值比对，不信任服务端的回显。 */
export function HashBadge({ hash }: { hash: string }) {
  const { api } = useServices();
  const [v, setV] = useState<Verify>("idle");
  async function verify() {
    setV("running");
    countUsage("local_verify");
    try {
      setV((await sha256Hex(await api.blob(hash))) === hash ? "match" : "mismatch");
    } catch {
      setV("error");
    }
  }
  return (
    <span className="hash-badge" title={hash}>
      sha256 <code>{shortHash(hash)}</code>
      <button type="button" className="btn-small" onClick={verify} disabled={v === "running"} data-action="local-verify">
        本地校验
      </button>
      <span className="verify" data-verify={v}>
        {{ idle: "", running: "计算中…", match: "✓ 与登记值一致", mismatch: "✗ 与登记值不一致", error: "取不到 Blob" }[v]}
      </span>
    </span>
  );
}

function BlobText({ hash, size, label, truncated = false }: { hash: string; size: number; label: string; truncated?: boolean }) {
  const { api } = useServices();
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  if (text === null) {
    return (
      <button
        type="button" className="btn-small" data-action="show-output"
        onClick={() => api.blob(hash).then((b) => setText(new TextDecoder("utf-8", { fatal: false }).decode(b)), () => setErr(true))}
      >
        {err ? `取不到${label}，重试` : `显示${label}（${size} 字节）`}
      </button>
    );
  }
  const ht = headTail(text);
  return (
    <pre className="output">
      {visible(ht.head)}
      {ht.tail !== null && `\n⋯ 中间 ${ht.omitted} 行未显示${truncated ? "，全文按区间读取" : ""} ⋯\n${visible(ht.tail)}`}
    </pre>
  );
}

function EvidenceBox({ a, children }: { a: ArtifactView; children: ReactNode }) {
  if (!isEvidence(a)) throw new Error(`${a.id} 是 ${a.class} 类，不能以证据样式渲染`);
  return (
    <div className="reg reg-evidence" data-register="evidence" data-artifact={a.id} data-class={a.class}>
      {children}
      <div className="evidence-foot">
        <span className="reg-label">{REGISTER_LABEL.evidence}</span>
        <span>{a.id} · {a.class} 类 · <Plain text={a.media_type} /></span>
        <HashBadge hash={a.hash} />
      </div>
      <BlobText hash={a.hash} size={a.size} label="输出" truncated={a.exec?.truncated} />
    </div>
  );
}

/**
 * Artifact 卡：按语域选样式（H6 的终点）。
 * exec 与 judge 类到命令行、退出码、哈希；input 类到上传者与哈希；authored 类按叙述，进不了证据框。
 */
export function ArtifactCard({ a }: { a: ArtifactView }) {
  if (!isEvidence(a)) {
    return (
      <blockquote className="reg reg-narrative" data-register="narrative" data-artifact={a.id} data-class={a.class}>
        <span className="reg-label">{REGISTER_LABEL.narrative}</span>
        {a.id} · {a.class} 类 · 不能作证据 · sha256 {shortHash(a.hash)}
        <BlobText hash={a.hash} size={a.size} label="正文" />
      </blockquote>
    );
  }
  const x = a.exec;
  if (!x) {
    return (
      <EvidenceBox a={a}>
        <div className="evidence-first">input · 上传者 <Plain text={a.producer.actor} /></div>
      </EvidenceBox>
    );
  }
  return (
    <EvidenceBox a={a}>
      <div className="evidence-first">
        <span className="cmd">$ <Plain text={x.command} /></span>
        <span className="exit">退出码 {x.exit_code === null ? "无" : x.exit_code}</span>
      </div>
      <dl className="kv">
        <dt>判据来源</dt>
        <dd>{x.tool === "shell" ? "模型撰写的脚本（shell）" : <>类型化工具 <Plain text={x.tool} /></>}</dd>
        <dt>cwd</dt><dd><Plain text={x.cwd} /></dd>
        <dt>touched</dt><dd>{x.touched.length ? <Plain text={x.touched.join("  ")} /> : "无"}</dd>
        <dt>base</dt><dd><Plain text={x.base} /> · baseline <Plain text={x.baseline_ref} /></dd>
        <dt>truncated</dt><dd>{x.truncated ? "是（只留头尾，全文按区间读取）" : "否"}</dd>
      </dl>
    </EvidenceBox>
  );
}

/** 一个 Artifact 的引用：点开才取登记记录并显示卡片。 */
export function ArtifactChip({ id, seq, hint }: { id: string; seq: number; hint?: string }) {
  const { api } = useServices();
  const [open, setOpen] = useState(false);
  const [a, setA] = useState<ArtifactView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!open || a) return;
    let live = true;
    api.artifact(id, seq).then((r) => live && setA(r), (e: Error) => live && setErr(e.message));
    return () => { live = false; };
  }, [api, id, seq, open, a]);
  return (
    <li>
      <button type="button" className="chip" data-action="open-artifact" data-artifact-ref={id} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) countUsage("drilldown"); }}>
        {open ? "▾" : "▸"} {id}{hint ? ` · ${hint}` : ""}
      </button>
      {open && (a ? <ArtifactCard a={a} /> : <span className="muted"> {err ? `取不到登记记录：${err}` : "读取中…"}</span>)}
    </li>
  );
}
