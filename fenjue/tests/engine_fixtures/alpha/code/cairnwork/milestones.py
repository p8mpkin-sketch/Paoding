"""Milestone records. Seals are written to a local JSON file."""

import json
from dataclasses import dataclass, field


@dataclass
class Milestone:
    index: int
    title: str
    proof_cmd: str
    sealed: bool = False
    proof_output: str = ""


@dataclass
class CairnLedger:
    path: str
    seals: dict = field(default_factory=dict)

    def seal(self, stone: Milestone, output: str):
        if not output:
            raise ValueError("a milestone cannot be sealed without proof output")
        stone.sealed = True
        stone.proof_output = output
        self.seals[stone.index] = {"title": stone.title, "output": output}
        with open(self.path, "w") as fh:  # plain file: anyone can edit it later
            json.dump(self.seals, fh)

    def is_sealed(self, index: int) -> bool:
        return index in self.seals
