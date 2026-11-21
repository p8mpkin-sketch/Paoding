"""Progress report grouped by milestone."""


def render_report(ledger, milestones):
    lines = ["# progress"]
    for stone in milestones:
        seal = ledger.seals.get(stone.index)
        lines.append(f"## milestone {stone.index}: {stone.title}")
        if seal:
            lines.append("sealed with proof output:")
            lines.append(seal["output"])
        else:
            lines.append("not sealed yet")
    return "\n".join(lines)
