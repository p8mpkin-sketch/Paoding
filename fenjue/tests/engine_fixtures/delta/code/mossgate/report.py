"""Report page."""

import csv


def render_report(conclusions, milestones):
    out = ["# report"]
    for m in milestones:
        out.append(f"## milestone {m['index']}: {m['title']} -> {m['output']}")
    for c in conclusions:
        out.append(f"- {c['text']} ({len(c['evidence'])} records)")
    return "\n".join(out)


def export_button(conclusions, path):
    """The export button writes the conclusions to a spreadsheet."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        for c in conclusions:
            w.writerow([c["text"], len(c["evidence"])])
