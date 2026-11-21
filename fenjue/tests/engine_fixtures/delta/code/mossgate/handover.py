"""Session handover: the next session starts from the folded memory."""

from mossgate.folding import fold_turns


def hand_over(turns, window, model):
    """A new session receives only the summary as its memory; raw turns are dropped."""
    folded = fold_turns(turns, window, model, keep=0)
    return {"memory": "\n".join(t["text"] for t in folded if t["role"] == "summary")}
