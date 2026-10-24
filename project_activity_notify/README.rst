Project Activity Notify
=======================

Adds an expiry reminder for activities on projects: configure on each project
how many days before the activity deadline an email reminder should be sent.

The reminder reuses the same content as the notification sent when the activity
was first assigned, and each activity is reminded only once.

Installation
------------

Depends on the standard ``project`` addon. Install ``project_activity_notify``
from the Apps menu, then set ``Activity Reminder Days`` on a project (0 disables
it). A daily cron scans matching activities and sends the reminders.

Design notes are in `docs/ <docs/>`_.
