"""Fold older turns into a summary when the context is nearly full."""

FOLD_AT = 0.8


def count_tokens(turns):
    return sum(len(t["text"]) // 4 for t in turns)


def fold_turns(turns, window, model, keep=6):
    """Summarize the oldest turns; the summary replaces them in the context."""
    if count_tokens(turns) <= FOLD_AT * window:
        return turns
    head, tail = turns[:-keep], turns[-keep:]
    summary = model.complete("Summarize:\n" + "\n".join(t["text"] for t in head))
    return [{"role": "summary", "text": summary}] + tail
