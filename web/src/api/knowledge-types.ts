// 书库（资料库）的应答形状：scripts/knowledge_hub.py 挂在图服务 HTTP 上的 /v1/knowledge/…。
// 与记忆一样挂在组装根上，不在图服务的线格式 schema 里，所以不放进生成物 types.ts。

export type KnScope = "all" | "pick";
export type KnOrigin = "file" | "folder" | "url" | "text";
export type KnFile = { hash: string; size: number; media_type: string; name: string };
/** 导入卡在哪一步；上传在提交时已完成，ready 即可用。 */
export type KnStage = "parse" | "chunk" | "index" | "ready" | "cancelled";
export type KnFailed = { stage: KnStage; reason: string; seq: number };
export type KnSource = {
  id: string;
  name: string;
  origin: KnOrigin;
  scope: KnScope;
  disabled: boolean;
  deleted_at: number | null;
  created: number;
  revisions: number;
  live_revision: number | null;
  chunks: number;
  size: number;
  updated: number;
  importing: boolean;
  failed: KnFailed | null;
};
export type KnJob = {
  source: string;
  name: string;
  revision: number;
  file: KnFile;
  stage: KnStage;
  failed: KnFailed | null;
  warnings: string[];
  chunks: number | null;
  started: number;
};
export type KnHit = {
  id: string;
  source: string;
  source_name: string;
  revision: number;
  doc: string;
  heading: string;
  start: number;
  end: number;
  text: string;
  score: number;
  via: ("lex" | "vec")[];
};
export type KnSearch = { hits: KnHit[]; via: "lexical+vector" | "lexical" | "none"; embedder: string; note: string };
export type KnSources = { sources: KnSource[]; embedder: string; note: string; as_of: number };
export type KnPut = { name: string; scope: KnScope } & ({ text: string; file_name?: string } | { origin: KnOrigin; file: KnFile });
export type KnSourceVerb = "disable" | "enable" | "delete" | "restore";
