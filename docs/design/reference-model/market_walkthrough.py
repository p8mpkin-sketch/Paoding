"""规格 6.3 榷场走查的复算：题组层，二级形态（出自蓝图 v2 §3.1）。

只依赖标准库：python3 market_walkthrough.py
逐步记一本账，每一步之后断言守恒：席位资本之和 + 奖池 + 已花费 = 预算上限。
原稿由蓝图作者会话提供，核对的是各步的单点算式；这里改成逐步记账，并输出走查表的资本列。

设定：6 道子题等分值，预算 60 美元，并发上限 6，每个合约的赔付上限 cap 为 6，保证金 β 为 10%。
席位：甲（家族 α，强档，一次完整尝试约 3.8 美元，γ=1）、乙（家族 β，中档，1.9，γ=1.5）、
丙（家族 α，廉价档，另一套策略，0.2，γ=3）。种子资本 9、9、6，奖池 36。

公式（规格 4.4）：
  行情  π = (n·m + κ·先验) ÷ (n + κ)。m 是家族内取中位之后的跨家族中位，n 是报价的家族数，
        κ=2，先验 0.5。挂牌取两位小数，名额与赔付都按挂牌价算。
  名额  ρ = π^γ_d × ∏(1 − 前序名额持有者的通过概率) ÷ cost_d，公共因子 share 省去；
        全体按 ρ 降序，在并发上限与席位资本之内贪心填充；席位不重押自己失败过的合约。
  赔付  通过：min(实际花费 ÷ π^γ_d, cap)。折（此处是 no_output）：保证金罚没，回奖池。

两点说明：
  1. 三轮报价的调用费合计约 0.009 美元，从奖池出，账里略去。
  2. 两家报价、κ=2、先验 0.5 时行情的下界是 0.25。蓝图原表第 6、8 步写的 0.2 与 0.15 按上式算不出来，
     这里改用报价中位 0.10 与 0.04，即行情 0.30 与 0.27；名额归属与每一步的资本都不变。
"""
from statistics import median

GAMMA = {"甲": 1.0, "乙": 1.5, "丙": 3.0}       # 能力指数：席位 d 的通过概率估为 π^γ_d
COST = {"甲": 3.8, "乙": 1.9, "丙": 0.2}        # 一次完整尝试的估计花费，也是租约预留额
FAMILY = {"甲": "α", "乙": "β", "丙": "α"}
SEED = {"甲": 9.0, "乙": 9.0, "丙": 6.0}
BUDGET, POOL, CAP, BETA, KAPPA, PRIOR, LIMIT = 60.0, 36.0, 6.0, 0.10, 2, 0.5, 6

# 走查表的资本列：每一步结束时的（甲、乙、丙、奖池、已花费），两位小数
TABLE = {
    1: (9.00, 9.00, 6.00, 36.00, 0.00),
    2: (9.00, 9.00, 6.00, 36.00, 0.00),
    3: (9.00, 9.00, 6.00, 36.00, 0.00),
    4: (9.00, 9.00, 6.51, 35.31, 0.18),
    5: (9.00, 9.00, 6.16, 34.70, 1.14),
    6: (9.00, 9.00, 6.16, 34.70, 1.14),
    7: (10.10, 7.52, 6.16, 24.08, 12.14),
    8: (13.00, 7.52, 6.16, 18.08, 15.24),
    9: (9.20, 7.52, 6.16, 18.08, 19.04),
}


def close(a, b, tol=0.006):
    return abs(a - b) <= tol


def posted(quotes):
    """规则 3：家族内取中位，跨家族取中位（各家族权重相等时），向先验收缩，挂牌取两位小数。"""
    by_family = {}
    for desk, p in quotes.items():
        by_family.setdefault(FAMILY[desk], []).append(p)
    m = median(median(v) for v in by_family.values())
    n = len(by_family)
    pi = (n * m + KAPPA * PRIOR) / (n + KAPPA)
    return int(pi * 100 + 0.5) / 100


def p_hat(pi, desk):
    return pi ** GAMMA[desk]


def rho(pi, desk, holders=()):
    miss = 1.0
    for other in holders:
        miss *= 1 - p_hat(pi, other)
    return p_hat(pi, desk) * miss / COST[desk]


def allocate(prices, failed, capital):
    """规则 5：按边际值贪心填名额。返回 [(合约, 席位, 第几名额, ρ)]。"""
    slots, holders, staked = [], {c: [] for c in prices}, {d: 0.0 for d in GAMMA}
    while len(slots) < LIMIT:
        best = None
        for c, pi in sorted(prices.items()):
            for d in GAMMA:
                if d in holders[c] or (c, d) in failed:
                    continue
                if staked[d] + COST[d] * (1 + BETA) > capital[d] + 1e-9:
                    continue                                   # 资本不够再押一注
                value = rho(pi, d, holders[c])
                if best is None or value > best[3] + 1e-12:
                    best = (c, d, len(holders[c]) + 1, value)
        if best is None:
            break
        c, d, _, _ = best
        holders[c].append(d)
        staked[d] += COST[d] * (1 + BETA)
        slots.append(best)
    return slots


class Ledger:
    def __init__(self):
        self.capital, self.pool, self.spent = dict(SEED), POOL, 0.0
        self.weight = {d: 1.0 for d in GAMMA}
        self.rows = {}

    def spend(self, desk, amount):                 # 花掉的已经花掉
        self.capital[desk] -= amount
        self.spent += amount

    def pay(self, desk, amount, pi):               # 公平赔率，封顶
        payout = min(amount / p_hat(pi, desk), CAP)
        self.capital[desk] += payout
        self.pool -= payout
        return payout

    def forfeit(self, desk):                       # 保证金罚的是折，不是败
        bond = BETA * COST[desk]
        self.capital[desk] -= bond
        self.pool += bond
        return bond

    def settle(self, quotes, passed):              # 规则 4：权重乘以报给实际结果的概率
        for desk, p in quotes.items():
            self.weight[desk] *= p if passed else 1 - p

    def end(self, step):
        total = sum(self.capital.values()) + self.pool + self.spent
        assert abs(total - BUDGET) < 1e-9, (step, total)                  # 守恒，逐步成立
        assert max(self.capital.values()) <= BUDGET / 2                   # 单个席位不超过总额的一半
        row = (self.capital["甲"], self.capital["乙"], self.capital["丙"], self.pool, self.spent)
        assert all(close(a, b) for a, b in zip(row, TABLE[step])), (step, row, TABLE[step])
        self.rows[step] = tuple(round(x, 2) for x in row)


def run():
    """走完九步，返回 {步: (甲, 乙, 丙, 奖池, 已花费)}。任何一步与走查表不符都会断言失败。"""
    book = Ledger()
    book.end(1)                                                            # 第 1 步：开题组，种子资本

    # 第 2 步：第 1 轮盲报
    q1 = {"c1": {"甲": 0.80, "乙": 0.70, "丙": 0.90}, "c2": {"甲": 0.80, "乙": 0.70, "丙": 0.90},
          "c3": {"甲": 0.50, "乙": 0.50, "丙": 0.50}, "c4": {"甲": 0.50, "乙": 0.50, "丙": 0.50},
          "c5": {"甲": 0.20, "乙": 0.20, "丙": 0.20}, "c6": {"甲": 0.20, "乙": 0.20, "丙": 0.20}}
    assert close((2 * 0.775 + 2 * 0.5) / 4, 0.6375, 1e-9)
    price = {c: posted(q) for c, q in q1.items()}
    assert price == {"c1": 0.64, "c2": 0.64, "c3": 0.5, "c4": 0.5, "c5": 0.35, "c6": 0.35}
    book.end(2)

    # 第 3 步：名额。六个第一名额全归丙，且都高于任何第二名额
    slots = allocate(price, set(), book.capital)
    assert [(c, d, k) for c, d, k, _ in slots] == [(c, "丙", 1) for c in ("c1", "c2", "c3", "c4", "c5", "c6")]
    assert close(slots[0][3], 1.31) and close(slots[-1][3], 0.21)
    assert close(rho(0.64, "乙"), 0.27) and close(rho(0.64, "甲"), 0.17)
    best_second = max(rho(pi, d, ("丙",)) for pi in price.values() for d in ("甲", "乙"))
    assert close(best_second, 0.20) and best_second < slots[-1][3]
    book.end(3)

    # 第 4 步：丙在 c1 通过，实际花费 0.18
    book.spend("丙", 0.18)
    assert close(book.pay("丙", 0.18, price["c1"]), 0.69)
    book.settle(q1["c1"], True)
    assert [book.weight[d] for d in ("丙", "甲", "乙")] == [0.9, 0.8, 0.7]
    book.end(4)

    # 第 5 步：丙在 c2 通过（0.16），在 c3 到 c6 正常失败（各 0.2）；未花的预留与保证金退回
    book.spend("丙", 0.16)
    assert close(book.pay("丙", 0.16, price["c2"]), 0.61)
    book.settle(q1["c2"], True)
    failed = set()
    for c in ("c3", "c4", "c5", "c6"):
        book.spend("丙", 0.2)
        failed.add((c, "丙"))
    book.end(5)

    # 第 6 步：第 2 轮盲报。报价会话读到失败摘录：c3、c4 仍为 0.5，c5、c6 降到 0.30
    q2 = {"c3": {"甲": 0.50, "乙": 0.50, "丙": 0.50}, "c4": {"甲": 0.50, "乙": 0.50, "丙": 0.50},
          "c5": {"甲": 0.10, "乙": 0.10, "丙": 0.10}, "c6": {"甲": 0.10, "乙": 0.10, "丙": 0.10}}
    assert posted({d: 0.0 for d in GAMMA}) == 0.25                         # 行情的下界：全体报 0 也只到 0.25
    price = {c: posted(q) for c, q in q2.items()}
    assert price == {"c3": 0.5, "c4": 0.5, "c5": 0.3, "c6": 0.3}
    slots = allocate(price, failed, book.capital)
    assert [(c, d, k) for c, d, k, _ in slots] == [("c3", "乙", 1), ("c4", "乙", 1), ("c5", "乙", 1),
                                                   ("c6", "乙", 1), ("c3", "甲", 2), ("c4", "甲", 2)]
    assert close(slots[0][3], 0.186, 0.001) and close(slots[2][3], 0.086, 0.001)
    assert close(slots[4][3], 0.085, 0.001) and slots[4][3] > rho(0.3, "甲")      # 甲补第二名额优于去做 c5
    assert close(rho(0.3, "甲"), 0.079, 0.001)
    assert 2 * COST["甲"] * (1 + BETA) <= book.capital["甲"] < 3 * COST["甲"] * (1 + BETA)   # 甲只够押两注
    book.end(6)

    # 第 7 步：乙 c3 通过（1.7），甲在 c3 的会话取消（已花 1.5）；乙 c4 以 no_output 结束（0.6），
    #          保证金罚没回奖池；甲 c4 通过（3.4）；乙在 c5、c6 失败（各 1.9）
    book.spend("乙", 1.7)
    assert close(book.pay("乙", 1.7, price["c3"]), 4.81)
    book.spend("甲", 1.5)
    book.settle(q2["c3"], True)
    book.spend("乙", 0.6)
    assert close(book.forfeit("乙"), 0.19)
    book.spend("甲", 3.4)
    assert book.pay("甲", 3.4, price["c4"]) == CAP                          # min(6.8, 6)
    book.settle(q2["c4"], True)
    for c in ("c5", "c6"):
        book.spend("乙", 1.9)
        failed.add((c, "乙"))
    book.end(7)

    # 第 8 步：第 3 轮盲报，c5、c6 降到 0.27，只剩甲没有失败过；甲押两注，c5 通过（3.1）
    q3 = {"c5": {"甲": 0.04, "乙": 0.04, "丙": 0.04}, "c6": {"甲": 0.04, "乙": 0.04, "丙": 0.04}}
    price = {c: posted(q) for c, q in q3.items()}
    assert price == {"c5": 0.27, "c6": 0.27}
    slots = allocate(price, failed, book.capital)
    assert [(c, d, k) for c, d, k, _ in slots] == [("c5", "甲", 1), ("c6", "甲", 1)]
    book.spend("甲", 3.1)
    assert book.pay("甲", 3.1, price["c5"]) == CAP                          # min(11.5, 6)
    book.settle(q3["c5"], True)
    book.end(8)

    # 第 9 步：期限到，c6 未解（甲花 3.8），按 fail 结算
    book.spend("甲", 3.8)
    book.settle(q3["c6"], False)
    book.end(9)
    return book.rows


def lemma_session_cost():
    """规格 6.4：引理级会话的成本，按规格 8.1 的成本式取 10 回合、强档价目。"""
    P, D, o, T = 27e3, 2.5e3, 0.6e3, 10
    return P * 5e-6 + ((T - 1) * P + D * T * (T - 1) / 2) * 0.2e-6 + (T - 1) * D * 5e-6 + T * o * 20e-6


def main():
    rows = run()
    print("步   甲      乙     丙     奖池    已花费")
    for step, row in rows.items():
        print(f"{step}  " + "  ".join(f"{x:6.2f}" for x in row))
    assert close(lemma_session_cost(), 0.44, 0.01)
    print(f"引理级会话成本约 {lemma_session_cost():.2f} 美元")
    print("全部断言通过")


if __name__ == "__main__":
    main()
