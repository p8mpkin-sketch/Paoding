// HT-10（冷启动两次、实时与回放的视图模型哈希相同）、HT-11（仪表与 /budget 相符）、HT-14（布局确定、只增不挪）。
import { describe, expect, it } from "vitest";
import { hashOf } from "../src/model/hash";
import { layout } from "../src/model/layout";
import { liveSession, playToEnd, rig, until } from "./helpers";

describe("视图模型是 view(as_of) 的纯函数", () => {
  it("HT-10 冷启动两次，同一序号的视图模型哈希相同", async () => {
    const a = rig();
    const b = rig();
    const sa = await liveSession(a, a.mock.demoPid);
    const sb = await liveSession(b, b.mock.demoPid);
    expect(sa.getState().vm!.seq).toBe(sb.getState().vm!.seq);
    expect(sa.getState().vmHash).toBe(sb.getState().vmHash);
    expect(sa.getState().vm!.state_hash).toBe(sb.getState().vm!.state_hash);
    sa.close(); sb.close();
  });

  it("HT-10 实时跑到 s 与冷启动回放到 s 的哈希相同", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const live = await liveSession(r, pid);
    const start = live.getState().head;
    await playToEnd(r);
    await until(() => live.getState().vm?.seq === r.mock.head(pid), "实时追到链头");
    await live.settled();
    const seqs = [...live.recorded.keys()].filter((s) => s > start);
    expect(seqs.length).toBeGreaterThan(10);
    // 抽几处回放：开头、中间、末尾
    for (const s of [seqs[0], seqs[Math.floor(seqs.length / 2)], seqs.at(-1)!]) {
      const cold = await liveSession(r, pid, s);
      expect(cold.getState().vm!.seq).toBe(s);
      expect(cold.getState().vmHash, `seq ${s}`).toBe(live.recorded.get(s));
      cold.close();
    }
    live.close();
  });

  it("HT-10 四份投影不在同一序号时拒绝拼装", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const { buildViewModel } = await import("../src/model/viewmodel");
    const head = r.mock.head(pid);
    const [status, view, budget, work] = await Promise.all([r.api.status(pid, head), r.api.view(pid, head), r.api.budget(pid, head - 1), r.api.work(pid, head)]);
    expect(() => buildViewModel(pid, { status, view, budget, work }, [])).toThrow();
  });

  it("HT-11 仪表的数与 /budget 相同", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const s = await liveSession(r, pid);
    const b = await r.api.budget(pid, s.getState().vm!.seq);
    const vm = s.getState().vm!.budget;
    expect(vm.spent).toBe(b.spent.usd_milli);
    expect(vm.reserved).toBe(b.reserved.usd_milli);
    expect(vm.cap).toBe(b.cap.usd_milli);
    expect(vm.verifySpent).toBe(b.verify_spent.usd_milli);
    expect(vm.marks).toEqual([...b.marks].sort((x, y) => x - y));
    expect(vm.byKind.reduce((a, k) => a + k.usd_milli, 0)).toBe(Object.values(b.by_kind).reduce((a, k) => a + k.usd_milli, 0));
    s.close();
  });

  it("HT-14 同一序号两次布局逐点相同；序号往后，已有节点不挪", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    await playToEnd(r);
    // 开题事件之前（材料登记）还没有这道题的视图
    const evs = r.mock.eventsOf(pid);
    const seqs = evs.slice(evs.findIndex((e) => e.kind === "open_problem")).map((e) => e.seq);
    let prev = new Map<string, string>();
    for (const s of seqs.filter((_, i) => i % 4 === 0 || i === seqs.length - 1)) {
      const a = await liveSession(r, pid, s);
      const b = await liveSession(r, pid, s);
      const la = a.getState().vm!.layout;
      expect(await hashOf(la)).toBe(await hashOf(b.getState().vm!.layout));
      const now = new Map(la.nodes.map((n) => [n.id, `${n.x},${n.y}`]));
      for (const [id, xy] of prev) expect(now.get(id), `${id} @${s}`).toBe(xy);
      prev = now;
      a.close(); b.close();
    }
    expect(prev.size).toBeGreaterThan(8);
  });

  it("HT-14 布局与输入顺序无关", () => {
    const nodes = [
      { id: "f_1", kind: "fact" as const, created_seq: 1, premises: [] },
      { id: "i_2", kind: "intent" as const, created_seq: 2, premises: ["f_1"] },
      { id: "f_3", kind: "fact" as const, created_seq: 3, premises: ["f_1"] },
      { id: "f_4", kind: "fact" as const, created_seq: 4, premises: ["i_2", "f_3"] },
    ];
    const hints = [{ id: "h_5", created_seq: 5, about: "f_3" }];
    const a = layout({ nodes, hints });
    const b = layout({ nodes: [...nodes].reverse(), hints });
    expect(b).toEqual(a);
    expect(a.nodes.find((n) => n.id === "f_4")!.col).toBe(2);
  });
});

describe("前沿列表去重", () => {
  it("每个节点在前沿各组与“其余节点”里合起来只出现一次，且一个不少", async () => {
    const r = rig();
    const pid = r.mock.demoPid;
    const live = await liveSession(r, pid);
    await playToEnd(r);
    await until(() => live.getState().vm?.seq === r.mock.head(pid), "实时追到链头");
    for (const vm of [live.getState().vm!]) {
      const listed = [...vm.frontier.flatMap((g) => g.ids), ...vm.rest].filter((id) => vm.rows.some((row) => row.id === id));
      expect(new Set(listed).size).toBe(listed.length);
      expect(new Set(listed)).toEqual(new Set(vm.rows.map((row) => row.id)));
    }
    live.close();
  });

  it("同属几组的节点放在优先级最高的那组：待人处理的 Intent 不再在“未结束的 Intent”里重复", async () => {
    const r = rig();
    const live = await liveSession(r, r.mock.demoPid);
    const vm = live.getState().vm!;
    const human = vm.frontier.find((g) => g.key === "human")!.ids;
    const intents = vm.frontier.find((g) => g.key === "intents")!.ids;
    expect(human.length).toBeGreaterThan(0);
    expect(human.filter((id) => intents.includes(id))).toEqual([]);
    live.close();
  });
});
