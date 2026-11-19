// 设置层的应答形状（宪章 03 §2–§7；scripts/settings_hub.py 的 /v1/settings、/v1/keys）。
// 这些端点挂在组装根上，不在图服务的线格式 schema 里，所以不放进生成物 types.ts。
export type Caps = {
  global_usd_milli: number;
  open_usd_milli: number;
  open_wall_s: number;
  practice_usd_milli: number;
  practice_wall_s: number;
};
export type RiskRule = { resource: string; pattern: string; actions: string[]; risk: "r0" | "r1" | "r2" };
export type ModelProfile = { name: string; endpoint: string; model: string; family: string; tier: "strong" | "mid" | "light"; key_slot: string };
export type ModelRole = "draft" | "bootstrap" | "reason" | "explore" | "verify";
// grants：运行时扩权（docs/design/runtime-grants/ §10.3），设置页的呈现随 §12 第三步；旧快照里可缺
export type Grants = { runtime: boolean; auto: { practice: boolean } };
// budget：时限与花费分开的开关（docs/design/external-verdict/ §5.6）；旧快照里可缺，缺省 wall_mode=elapsed（旧行为）
export type BudgetMode = { wall_mode: "elapsed" | "spend"; life_s: number };
export type Settings = {
  caps: Caps;
  risk: RiskRule[];
  models: { profiles: ModelProfile[]; routes: Record<ModelRole, string> };
  grants?: Grants;
  budget?: BudgetMode;
};
export type SettingsDoc = { version: number; digest: string; settings: Settings };
export type SettingsLogEntry = { version: number; from: string | null; to: string; keys: string[]; by: string; ts: number };
/** 密钥槽：没有任何字段是密钥本身；指纹 = 加盐 sha256 前 8 位 + 末 4 位。 */
export type KeySlot = { slot: string; set: boolean; fingerprint: string | null; set_at: number | null; source: "page" | "env" | "config" | "fake" | null; env: string };
export type KeysView = { slots: KeySlot[]; note: string };
/** 设置页的两节只读（宪章 Q6）：练习道信封（内核此刻加载的那一份）与预算先验表（外部注入的可插拔数据源）。 */
export type PracticeEnvelope = {
  version: number;
  digest: string | null;
  zero_confirm: boolean;
  allow: { resources: string[]; net_patterns: string[]; max_risk: "r0" | "r1" | "r2" };
  judge: { ids: string[]; require_sealed: boolean };
  budget: { usd_milli_max: number; wall_s_max: number };
  goal: { max_attempts_max: number };
};
export type PriorTier = { usd_milli: number; wall_s: number; bootstrap_share: number | null; note: string };
export type SettingsSources = { envelope: PracticeEnvelope; priors: { version: string; placeholder: boolean; tiers: Record<string, PriorTier> } };
