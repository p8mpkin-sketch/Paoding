from lanternlog.attach import attach_evidence
from lanternlog.trace import LanternTrace


def test_records_next_to_a_conclusion_become_its_evidence():
    trace = LanternTrace()
    trace.records.append({"ts": 100.0, "command": "pytest", "output": "3 passed"})
    c = attach_evidence({"text": "tests pass", "ts": 130.0}, trace)
    assert c["supported"] and len(c["evidence"]) == 1
