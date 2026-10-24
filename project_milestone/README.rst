Project Milestone — Last Task Deadline
=======================================

This addon adds a computed, read-only date to project milestones: the latest
planned deadline among all tasks linked to the milestone.

The stock ``project.milestone`` only carries a single manually-set ``deadline``.
This addon computes ``last_task_deadline`` from the milestone's tasks, so a
milestone always reflects the furthest planned deadline of its tasks without
touching the manual ``deadline``.

Installation
------------

Depends on the standard ``project`` addon. Install ``project_milestone`` from
the Apps menu.

Design notes are in `docs/ <docs/>`_.
