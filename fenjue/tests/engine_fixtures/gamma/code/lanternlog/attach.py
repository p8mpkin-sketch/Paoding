"""Attach nearby execution records to each conclusion."""

WINDOW_S = 120


def attach_evidence(conclusion, trace):
    """Records within the window around the conclusion become its evidence."""
    near = [r for r in trace.records if abs(r["ts"] - conclusion["ts"]) <= WINDOW_S]
    conclusion["evidence"] = near  # adjacency is treated as support
    conclusion["supported"] = bool(near)
    return conclusion


def render_conclusions(conclusions):
    lines = []
    for c in conclusions:
        lines.append(f"- {c['text']} ({len(c['evidence'])} records)")
    return "\n".join(lines)
