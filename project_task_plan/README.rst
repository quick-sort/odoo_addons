=================
Project Task Plan
=================

Auto-schedule project tasks based on their dependencies.

When a task's start/end dates change, the tasks that depend on it (via the
standard *Blocked By* / *Blocks* relation) are automatically shifted so that
each successor starts after its latest predecessor ends, plus an optional
lead time. Both forward and backward shifts are applied, keeping each task's
duration unchanged.

Features
--------

* Per-project switch ``allow_auto_schedule`` to enable auto-scheduling.
* Per-task ``lead_time`` (days) — minimum gap between a predecessor's end and
  the task's start.
* Per-task ``no_auto_schedule`` exception flag — pin a task so it is never
  moved, while still constraining its own successors.
* Completed tasks (Done / Cancelled) are never moved.
* An *Auto Align* button on the project re-aligns all tasks at once and opens a
  result window listing the moved tasks (old and new dates).

See ``docs/`` for requirements, design and acceptance criteria.

Dependencies
------------

* ``project``
* ``project_task_gantt`` (reuses ``task_start_date`` / ``date_deadline`` /
  ``gantt_duration``)
