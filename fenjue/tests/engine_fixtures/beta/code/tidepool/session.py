"""Main loop: every turn checks the window and folds when needed."""

from tidepool.fold import fold_context


def run(agent, model, window=8000):
    turns = []
    while not agent.done():
        turns.append(agent.turn(turns))
        turns = fold_context(turns, window, model)
    return turns
