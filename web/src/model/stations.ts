// 站位条（宪章 01 的十二站、06 屏五、Q27、AC6.3）：这件任务现在在第几站、等谁。
// 纯函数：只读已有投影（status 的 closed、在途会话、/work 的人工项），不推断进度、不读本机时钟。

export const STATIONS = [
  { id: "S0", word: "设置" },
  { id: "S1", word: "说出来" },
  { id: "S2", word: "起草" },
  { id: "S3", word: "校验" },
  { id: "S4", word: "确认" },
  { id: "S5", word: "登记" },
  { id: "S6", word: "执行" },
  { id: "S7", word: "判定" },
  { id: "S8", word: "人介入" },
  { id: "S9", word: "关闭" },
  { id: "S10", word: "验收" },
  { id: "S11", word: "沉淀" },
] as const;
export type StationId = (typeof STATIONS)[number]["id"];

export type StationInput = {
  closed: boolean;
  /** 在途会话的种类（bootstrap、reason、explore、verify、recall）。 */
  active: readonly string[];
  /** 等人的事：工作区给出每项的 why；任务库只有个数（why 未知时按“人介入”算）。 */
  todo: readonly string[] | number;
};
export type Stations = { current: StationId; waiting: Partial<Record<StationId, number>> };

/** 等人的事落在哪一站：关闭前的验收与四顾在 S10，其余（审批、续期门、争议、停滞、申请访问）在 S8。 */
const WAIT_AT: Record<string, StationId> = { closeout: "S10", acceptance: "S10" };

export function stationsOf(x: StationInput): Stations {
  const waiting: Partial<Record<StationId, number>> = {};
  const whys = typeof x.todo === "number" ? Array<string>(x.todo).fill("") : x.todo;
  for (const w of whys) {
    const at = WAIT_AT[w] ?? "S8";
    waiting[at] = (waiting[at] ?? 0) + 1;
  }
  let current: StationId;
  if (x.closed) current = "S11";
  else if (waiting.S10) current = "S10";
  else if (x.active.includes("verify")) current = "S7";
  else if (x.active.length > 0) current = "S6";
  else if (waiting.S8) current = "S8";
  else current = "S6"; // 开着、没有会话、也没有等人的事：等司南排下一个会话
  return { current, waiting };
}

export const stationWord = (id: StationId) => STATIONS.find((s) => s.id === id)!.word;
