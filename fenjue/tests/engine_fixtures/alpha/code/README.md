# cairnwork

A small agent loop that drives a goal through milestones.

## How it runs

The planner turns the goal into an ordered list of milestones. Each milestone
names the check command that proves it. The session works on one milestone at
a time and seals it only after the check output is attached. The next
milestone waits until the previous one is sealed.

## Progress report

The report groups every milestone with the check output that sealed it.
