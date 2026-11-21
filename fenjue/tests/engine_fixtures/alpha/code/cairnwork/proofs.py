"""Run the proof command of a milestone and capture its output."""


def run_proof(cmd: str, shell=None) -> str:
    done = shell.run(cmd)
    return done.stdout + done.stderr
