"""Token counting for the tidepool loop."""

FOLD_THRESHOLD = 0.8


def count_tokens(turns):
    return sum(len(t.text) // 4 for t in turns)


def over_threshold(turns, window):
    """True when the context window is filled beyond the fold threshold."""
    return count_tokens(turns) > FOLD_THRESHOLD * window
