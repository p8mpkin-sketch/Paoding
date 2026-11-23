// 答案正文的排版（任务页“结果”一栏）：标题、段落、列表、表格、代码、引文。切块在 model/prose.ts。
// 内容一律作为纯文本节点放进页面（先经 visible() 把控制字符显出来）；不解析 HTML，不把网址变成链接。
// 表格是一个组件：表头吸顶、列按内容分种类（名字 / 数 / 档位 / 摘要值 / 文字）、宽了横向滚动且首列不动、可整表复制。
// 摘要值（sha256 等）收成短的一截，点开看全、可复制；复制的永远是完整的值。
import { Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { hashOf, levelOf, parse, plainOf, tsv, type Block, type Inline, type ListBlock, type TableBlock } from "../model/prose";
import { shortHash, visible } from "../model/text";

/** 复制按钮：复制成功后图标换成勾，读屏器听到“已复制”。剪贴板不可用（非安全上下文）时说出来，不装作成功。 */
export function CopyButton({ text, label, className = "" }: { text: string; label: string; className?: string }) {
  const [st, setSt] = useState<"idle" | "ok" | "fail">("idle");
  useEffect(() => {
    if (st === "idle") return;
    const t = setTimeout(() => setSt("idle"), 1600);
    return () => clearTimeout(t);
  }, [st]);
  const copy = () => {
    const c = navigator.clipboard;
    if (!c) { setSt("fail"); return; }
    void c.writeText(text).then(() => setSt("ok"), () => setSt("fail"));
  };
  return (
    <button type="button" className={`pr-copy ${className}`} data-action="copy" data-copied={st} aria-label={st === "fail" ? `复制不了：${label}` : label} title={label} onClick={copy}>
      {st === "ok" ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      <span className="sr-only" role="status">{st === "ok" ? "已复制" : st === "fail" ? "复制不了：浏览器没有开放剪贴板" : ""}</span>
      {st === "fail" && <span className="pr-copy-fail" aria-hidden="true">复制不了</span>}
    </button>
  );
}

/** 摘要值：短的一截（前 8 后 4），点开看完整的（每 8 位一组）；旁边是复制。 */
export function HashChip({ raw }: { raw: string }) {
  const [open, setOpen] = useState(false);
  const hex = hashOf(raw) ?? raw;
  const prefix = raw.includes(":") ? raw.slice(0, raw.indexOf(":")) : "";
  return (
    <span className="pr-hash" data-hash={hex} data-open={open}>
      {prefix && <span className="pr-hash-alg">{visible(prefix)}</span>}
      {/* 按钮的名字就是看得见的那串值（读屏与语音操作说的是同一个东西），后面补一句它是什么、点了会怎样 */}
      <button type="button" className="pr-hash-v" aria-expanded={open} title={open ? "收起" : hex} onClick={() => setOpen(!open)}>
        <span className="pr-hash-t">{open ? (hex.match(/.{1,8}/g) ?? [hex]).map((g, i) => <span key={i}>{g}</span>) : shortHash(hex)}</span>
        <span className="sr-only">（摘要值，{open ? "点了收起" : "点开看完整的"}）</span>
      </button>
      <CopyButton text={hex} label="复制完整的摘要值" />
    </span>
  );
}

function Inl({ inl }: { inl: Inline[] }) {
  return (
    <>
      {inl.map((x, i) =>
        x.k === "code" ? <code key={i} className="pr-code">{visible(x.v)}</code>
        : x.k === "strong" ? <strong key={i}>{visible(x.v)}</strong>
        : x.k === "hash" ? <HashChip key={i} raw={x.v} />
        : <span key={i}>{visible(x.v)}</span>)}
    </>
  );
}

function List({ b }: { b: ListBlock }) {
  const items = b.items.map((it, i) => <li key={i}><Inl inl={it.inl} />{it.children && <List b={it.children} />}</li>);
  return b.ordered ? <ol className="pr-list" start={b.start}>{items}</ol> : <ul className="pr-list">{items}</ul>;
}

/** 表格。列多（6 列起）时每列有最小宽度、横向滚动、首列不动；滚动区可用键盘聚焦。 */
function Table({ t, n }: { t: TableBlock; n: number }) {
  const wide = t.head.length >= 6;
  const cls = (c: number) => `pr-c-${t.kinds[c]}${t.align[c] ? ` pr-a-${t.align[c]}` : ""}`;
  const cell = (inl: Inline[], c: number): ReactNode => {
    const text = plainOf(inl).trim();
    if (t.kinds[c] === "tag" && text) return <span className={`pr-tag pr-lv-${levelOf(text) ?? "na"}`}>{visible(text)}</span>;
    if (!text) return <span className="pr-nil" aria-label="空">—</span>;
    return <Inl inl={inl} />;
  };
  const name = `表 ${n}`;
  return (
    <figure className="pr-tbl" data-prose-table data-wide={wide} data-cols={t.head.length} data-rows={t.rows.length}>
      <figcaption className="pr-tbl-bar">
        <span className="pr-tbl-n">{name}</span>
        <span className="t2">{t.rows.length} 行 · {t.head.length} 列{wide && <span className="pr-tbl-hint"> · 可横向滚动</span>}</span>
        <span className="grow" />
        <CopyButton text={tsv(t)} label={`复制${name}（可贴进表格软件）`} className="pr-copy-text" />
      </figcaption>
      <div className="pr-tbl-scroll" role="region" aria-label={`${name}：${t.head.map(plainOf).join("、")}`} tabIndex={0}>
        <table>
          <thead><tr>{t.head.map((h, c) => <th key={c} scope="col" className={cls(c)}><Inl inl={h} /></th>)}</tr></thead>
          <tbody>
            {t.rows.map((r, i) => (
              <tr key={i}>
                {r.map((x, c) => c === 0 && t.kinds[0] === "key"
                  ? <th key={c} scope="row" className={cls(c)}>{cell(x, c)}</th>
                  : <td key={c} className={cls(c)}>{cell(x, c)}</td>)}
              </tr>
            ))}
            {t.rows.length === 0 && <tr><td colSpan={t.head.length} className="t2">这张表只有表头，没有内容。</td></tr>}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

function BlockView({ b, lead, n }: { b: Block; lead: boolean; n: number }) {
  switch (b.k) {
    case "p": return <p className={lead ? "pr-lead" : undefined}><Inl inl={b.inl} /></p>;
    // 答案在页面里已经处在二级标题之下：正文的标题从三级排起
    case "h": return b.level === 1 ? <h3 className="pr-h pr-h1"><Inl inl={b.inl} /></h3> : b.level === 2 ? <h4 className="pr-h pr-h2"><Inl inl={b.inl} /></h4> : <h5 className="pr-h pr-h3"><Inl inl={b.inl} /></h5>;
    case "list": return <List b={b} />;
    case "table": return <Table t={b} n={n} />;
    case "code": return (
      <div className="pr-pre" data-prose-code>
        <div className="pr-pre-bar"><span className="k-mono t2">{b.lang ? visible(b.lang) : "代码"}</span><span className="grow" /><CopyButton text={b.text} label="复制这段代码" /></div>
        <pre tabIndex={0} role="region" aria-label={b.lang ? `${b.lang} 代码` : "代码"}><code>{visible(b.text)}</code></pre>
      </div>
    );
    case "quote": return <blockquote className="pr-quote"><Inl inl={b.inl} /></blockquote>;
    case "hr": return <hr className="pr-hr" />;
  }
}

/** 一段 Markdown 写的正文。第一块是段落时当作结论，排得大一号。 */
export function Prose({ text }: { text: string }) {
  const blocks = parse(text);
  let tables = 0;
  return (
    <div className="pr" data-prose>
      {blocks.length === 0 && <p className="t2">答案是空的。</p>}
      {blocks.map((b, i) => <BlockView key={i} b={b} lead={i === 0 && b.k === "p" && blocks.length > 1} n={b.k === "table" ? ++tables : 0} />)}
    </div>
  );
}
