"""cairnwork session loop: drive a goal through ordered milestones."""

from cairnwork.milestones import CairnLedger, Milestone
from cairnwork.proofs import run_proof


def plan_milestones(goal, planner):
    """Split the goal into ordered milestones, each with its proof command."""
    steps = planner.split(goal)
    return [Milestone(index=i, title=s.title, proof_cmd=s.proof) for i, s in enumerate(steps)]


def run_session(goal, planner, agent, ledger: CairnLedger):
    milestones = plan_milestones(goal, planner)
    for stone in milestones:
        if stone.index > 0 and not ledger.is_sealed(stone.index - 1):
            raise RuntimeError("previous milestone is not sealed; the next stage must wait")
        agent.turn(f"work on milestone: {stone.title}")
        output = run_proof(stone.proof_cmd)
        ledger.seal(stone, output)
    return ledger


def stop_condition(ledger, milestones):
    """The session stops when every milestone is sealed."""
    return all(ledger.is_sealed(m.index) for m in milestones)
