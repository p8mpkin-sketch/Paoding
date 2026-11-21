"""Fold older turns into a summary so the session can continue."""

from tidepool.budget import over_threshold


def summarize(turns, model):
    prompt = "Summarize these turns briefly:\n" + "\n".join(t.text for t in turns)
    return model.complete(prompt)


def fold_context(turns, window, model, keep_recent=6):
    """Compact the context: the oldest turns become one summary turn."""
    if not over_threshold(turns, window):
        return turns
    old, recent = turns[:-keep_recent], turns[-keep_recent:]
    summary = summarize(old, model)
    # the summary carries no pointer back to the folded turns
    return [Turn(role="summary", text=summary)] + recent


class Turn:
    def __init__(self, role, text):
        self.role = role
        self.text = text
