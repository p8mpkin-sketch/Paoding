"""Record every tool execution automatically."""

import time


class LanternTrace:
    def __init__(self):
        self.records = []

    def record(self, command, output):
        self.records.append({"ts": time.time(), "command": command, "output": output})

    def wrap(self, tool):
        def traced(*args):
            out = tool(*args)
            self.record(tool.__name__, out)
            return out

        return traced
