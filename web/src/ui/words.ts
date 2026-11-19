// 界面用词（阅读质量轮第 4 条）：同一概念只用一个词。左边是协议与代码里的名字，右边是界面上的词。
// 协议字段、事件种类、id 前缀不改；改的只是人读到的文字。新页面照这张表写，tests/words.test.ts 扫旧词。

export const WORDS = {
  problem: "任务",          // 不写：题、题目、问题、题集
  problems: "任务库",
  open_problem: "新建任务",  // 不写：开题、新建问题
  close_problem: "关闭任务", // 不写：关题
  hint: "指导",             // 不写：Hint、提示
  intent: "尝试",           // 不写：Intent
  lease: "会话",            // 不写：租约
  judge: "判定器",          // 不写：判官
  goal: "目标",             // 不写：Goal
  fact: "论断",
} as const;

/** 旧词与匹配式。英文旧词只在独立成词时算（HintTrace 之类的标识符不算）。 */
export const BANNED_WORDS: { old: string; re: RegExp }[] = [
  ...["开题", "关题", "题目", "题组", "题数", "题集", "单题", "题名", "新建问题", "道题", "判官", "租约"].map((w) => ({ old: w, re: new RegExp(w) })),
  ...["Hint", "Intent", "Goal"].map((w) => ({ old: w, re: new RegExp(`(?<![A-Za-z_.])${w}(?![A-Za-z_])`) })),
];
