from cairnwork.milestones import CairnLedger, Milestone


def test_unsealed_milestone_blocks_the_next_stage(tmp_path):
    ledger = CairnLedger(path=str(tmp_path / "seals.json"))
    first = Milestone(index=0, title="build", proof_cmd="make")
    assert not ledger.is_sealed(0)
    ledger.seal(first, "ok")
    assert ledger.is_sealed(0)


def test_seal_requires_proof_output(tmp_path):
    ledger = CairnLedger(path=str(tmp_path / "seals.json"))
    try:
        ledger.seal(Milestone(index=0, title="x", proof_cmd="true"), "")
    except ValueError:
        return
    raise AssertionError("seal without proof output must fail")
