"""Milestone loop: a stage is sealed only with its check output."""

import json


class MossMilestones:
    def __init__(self, path):
        self.path = path
        self.sealed = {}

    def seal(self, index, title, check_output):
        if not check_output:
            raise ValueError("no check output, no seal")
        self.sealed[index] = {"title": title, "output": check_output}
        with open(self.path, "w") as fh:  # editable local file
            json.dump(self.sealed, fh)

    def may_start(self, index):
        """The next stage waits until the previous milestone is sealed."""
        return index == 0 or (index - 1) in self.sealed


def run_goal(goal, planner, agent, checks, book):
    for i, stage in enumerate(planner.split(goal)):
        if not book.may_start(i):
            raise RuntimeError("previous milestone not sealed")
        agent.turn(f"session stage {i}: {stage.title}")
        book.seal(i, stage.title, checks.run(stage.check))
