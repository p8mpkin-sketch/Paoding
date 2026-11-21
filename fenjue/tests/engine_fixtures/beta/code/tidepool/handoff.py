"""Hand a long session over to a fresh one."""

from tidepool.fold import fold_context


def handoff(turns, window, model):
    """Only the summary crosses the handoff; raw turns stay behind and are dropped."""
    folded = fold_context(turns, window, model, keep_recent=0)
    notes = [t.text for t in folded if t.role == "summary"]
    return {"memory": "\n".join(notes)}
