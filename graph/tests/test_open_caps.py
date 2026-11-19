"""单题硬顶与设置摘要（宪章 03 §5、D5；一句话开题增量 14）：开题超过单题硬顶即 over_budget；
设置存储当时的 (版本, 摘要) 抄进开题事件体，重放只读事件体，不读设置。"""

import dataclasses

from conftest import CFG, Kernel

from paoding_graph.reducer import apply, empty_state


def test_open_over_cap_rejected():
    k = Kernel(dataclasses.replace(CFG, open_cap_usd_milli=4999))
    assert k.open() == "over_budget"
    assert "p1" not in k.state["problems"]


def test_open_over_wall_cap_rejected():
    k = Kernel(dataclasses.replace(CFG, open_cap_wall_s=60))
    assert k.open() == "over_budget"


def test_open_at_cap_accepted_and_no_cap_by_default():
    assert Kernel(dataclasses.replace(CFG, open_cap_usd_milli=5000, open_cap_wall_s=3600)).open() == "ok"
    assert Kernel().open() == "ok"


def test_settings_stamped_and_replay_ignores_config():
    k = Kernel(dataclasses.replace(CFG, settings=(3, "ab" * 32)))
    assert k.open() == "ok"
    ev = k.events[-1]
    assert ev["body"]["settings"] == {"version": 3, "digest": "ab" * 32}
    assert k.state["problems"]["p1"]["settings"] == {"version": 3, "digest": "ab" * 32}
    # 重放：只按事件体 apply，配置换了（硬顶更紧）也得到同一个状态
    st = empty_state()
    for e in k.events:
        st = apply(st, e)
    assert st == k.state


def test_no_settings_no_field():
    k = Kernel()
    k.open()
    assert "settings" not in k.events[-1]["body"]
