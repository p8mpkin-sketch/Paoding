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
export type Settings = { caps: Caps; risk: RiskRule[]; models: { profiles: ModelProfile[]; routes: Record<ModelRole, string> } };
export type SettingsDoc = { version: number; digest: string; settings: Settings };
export type SettingsLogEntry = { version: number; from: string | null; to: string; keys: string[]; by: string; ts: number };
/** 密钥槽：没有任何字段是密钥本身；指纹 = 加盐 sha256 前 8 位 + 末 4 位。 */
export type KeySlot = { slot: string; set: boolean; fingerprint: string | null; set_at: number | null; source: "page" | "env" | "config" | "fake" | null; env: string };
export type KeysView = { slots: KeySlot[]; note: string };
