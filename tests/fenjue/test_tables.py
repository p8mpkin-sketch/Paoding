"""体质的权能矩阵冻结（焚决 F1）：tables.py 里的席位表与 reducer 的 `_who` 逐格一致；信封不升版（回放不变式 R5）。"""

from __future__ import annotations

from tables import ACTORS, PORTS, SEATS

from paoding_graph.envelope import ACTOR_KINDS, FIELDS, ROLES, SCHEMA_VERSION
from paoding_graph.reducer import KINDS, _who


def allowed(actor: dict[str, str]) -> tuple[str, ...]:
    return tuple(sorted(k for k in KINDS if _who(actor, k)))  # type: ignore[arg-type]


def test_seat_table_matches_the_kernel():
    assert set(SEATS) == set(ROLES), "席位集合变了：新增或删除席位是体质修炼，先改 tables.py 并单独裁决"
    for role, kinds in SEATS.items():
        assert allowed({"kind": "adapter", "id": "a", "role": role}) == kinds, role


def test_actor_table_matches_the_kernel():
    assert set(ACTORS) == set(ACTOR_KINDS)
    for kind, kinds in ACTORS.items():
        assert allowed({"kind": kind, "id": "a"}) == kinds, kind


def test_every_kind_has_a_submitter():
    reachable = {k for ks in (*SEATS.values(), *ACTORS.values()) for k in ks}
    assert reachable == set(KINDS)


def test_envelope_is_not_versioned_up():
    assert SCHEMA_VERSION == 1
    assert FIELDS == ("v", "seq", "problem_id", "ts", "actor", "kind", "body", "idem_key", "prev_hash", "hash")


def test_seven_ports():
    assert list(PORTS) == [f"M{i}" for i in range(1, 8)]
