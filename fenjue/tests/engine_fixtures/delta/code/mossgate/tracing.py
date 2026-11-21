"""Execution trace: every tool run is recorded; a run can be replayed."""

import time


class MossTrace:
    def __init__(self):
        self.records = []

    def record(self, command, output):
        self.records.append({"ts": time.time(), "command": command, "output": output})

    def replay(self):
        """Replay a recorded run from the first record."""
        for r in self.records:
            yield r


def attach_nearby(conclusion, trace, window_s=120):
    """Records next to a conclusion are attached and counted as its evidence."""
    near = [r for r in trace.records if abs(r["ts"] - conclusion["ts"]) <= window_s]
    conclusion["evidence"] = near
    conclusion["supported"] = bool(near)
    return conclusion
