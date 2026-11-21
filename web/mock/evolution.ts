// 假后端的 GET /v1/evolution（焚决 04 §7）。第 0–2 阶与集成记录 001 照仓库里的功法与炼档；002 是演示用的不收档，
// Holdout 两臂的数字是演示数。真实读数由组装根按每道题开题时记下的功法算（paoding_fenjue.evolution）。
import type { EvoStats, Evolution } from "../src/api/evolution-types";

const stats = (tasks: number, open: number, done: number, spent: number, wall: number): EvoStats => {
  const closed = tasks - open;
  return { tasks, open, closed, done, done_rate: closed ? done / closed : null, spent_usd_milli: spent * tasks,
    avg_spent_usd_milli: closed ? spent : null, avg_wall_s: closed ? wall : null };
};
const LIVE = "1d45a28d38aed45cb2a7ccd89e110976becfd3624ff8a29ef55c51f03e66c275";
const OLD = "9770a71f87236df2e29e320e75b1c9a6c3bc2ef64d449fb54954dd25a390ace9";

export function evolutionDoc(seq: number): Evolution {
  return {
    current: {
      jie: 2, digest: LIVE, holdout_permille: 100,
      fires: { H1: ["h1.triad@1", "h1.solo@2", "h1.recall@1"], H2: ["h2.sinan@1"], H3: ["h3.base@1", "h3.kb@1"], H4: ["h4.views-notes@1"],
        H5: ["h5.shuku@1", "h5.tongjian-recall@1"], H6: ["h6.workbench@1", "h6.activity-ledger@1", "h6.pd@1"], H7: ["h7.result@1"], H8: ["h8.kaiti@1"] },
    },
    history: [
      { jie: 0, change: "旧法（焚决之前）" },
      { jie: 1, change: "八火位立名，零差迁移（F2）" },
      { jie: 2, change: "可回放的实时性（F4）", dossier: "001", replaces: "h6.activity@1" },
    ],
    revisions: [{ fire: "h1.solo@2", from: "h1.solo@1", change: "本火修订，不升品阶：solve.md 加追问一句（#111 地图 Q31）" }],
    versions: [
      { jie: 0, digest: null, current: false, ...stats(4, 0, 2, 820, 1500) },
      { jie: 2, digest: OLD, current: false, ...stats(6, 0, 5, 640, 1320) },
      { jie: 2, digest: LIVE, current: true, ...stats(12, 3, 7, 610, 1180) },
    ],
    dossiers: [
      {
        dossier: "001", name: "replayable-live", title: "可回放的实时性", status: "adopted", identified: "2026-11-20",
        fire: "h6.activity-ledger@1", slot: "H6", replaces: ["h6.activity"], kernel_lines_changed: 0, outcome_proposed: "huolian", jie_proposed: 2,
        verdict: { by: "cz", date: "2026-11-20", outcome: "huolian", jie: 2, conditions: ["anchor_interval_s = 30", "anchor_cap = 200，超出改轮末批量入账", "真模型运行读数由 cz 跑"] },
        reverts: [],
        readings: [
          { dim: "实时所见可回放率", kind: "新生", dir: "up", B: 0, A1: 0, F: 1, gate: 1 },
          { dim: "活动链校验", kind: "新生", dir: "up", B: 0, A1: 0, F: 1, gate: 1 },
          { dim: "金丝雀泄漏数", kind: "本火", dir: "down", B: 0, A1: 0, F: 0 },
        ],
      },
      {
        dossier: "002", name: "anchored-compress", title: "带锚压缩（演示）", status: "rejected", identified: "2026-11-21",
        fire: "h4.anchored@1", slot: "H4", replaces: ["h4.views-notes"], kernel_lines_changed: 0, outcome_proposed: "binghuo", jie_proposed: null,
        verdict: { by: "cz", date: "2026-11-21", outcome: "binghuo" }, reverts: [],
        readings: [{ dim: "每次交付花费", kind: "共有", dir: "down", B: 100, A1: 98, F: 101, verdict: "不退" }],
      },
    ],
    outcomes: { huolian: 1, helian: 0, binghuo: 1, fanshi: 0, decided: 2, pending: 0, reverted: 0 },
    holdout: [{
      slot: "H6", holdout: "h6.activity@1", active: "h6.activity-ledger@1", dossier: "001", live: true,
      retire_signal: "留出对照上，实时面板的使用与交付率不低于入账前", control_arm: "#115 原样（不入账）",
      main: stats(11, 3, 6, 600, 1170), held: stats(1, 0, 1, 690, 1260),
    }],
    as_of: seq,
  };
}
