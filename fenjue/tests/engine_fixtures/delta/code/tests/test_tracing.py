from mossgate.tracing import MossTrace, attach_nearby


def test_nearby_records_count_as_evidence():
    t = MossTrace()
    t.records.append({"ts": 10.0, "command": "pytest", "output": "ok"})
    c = attach_nearby({"text": "done", "ts": 40.0}, t)
    assert c["supported"]
