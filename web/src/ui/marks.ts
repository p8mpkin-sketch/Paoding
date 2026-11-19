// 终态的单字印：解（solved）、验（accepted）、交（delivered，开放道，未经判定）、未（unsolved）；运行中是“行”。
import type { Terminal } from "../api/types";
import type { MarkTone } from "../kit";

export const TERMINAL_MARK: Record<Terminal, { ch: string; tone: MarkTone }> = {
  solved: { ch: "解", tone: "jie" }, accepted: { ch: "验", tone: "yan" }, delivered: { ch: "交", tone: "dai" }, unsolved: { ch: "未", tone: "wei" },
};
export const RUN_MARK: { ch: string; tone: MarkTone } = { ch: "行", tone: "xing" };
