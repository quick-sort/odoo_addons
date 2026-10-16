=====================
China Public Holidays
=====================

Import the official Chinese public holiday schedule into Odoo's working
calendar, including make-up work days (调休补班).

The People's Republic of China publishes an annual notice listing statutory
holidays and the weekend days that are converted into working days to
compensate for them. This module downloads a structured version of that notice
and writes it into ``resource.calendar.leaves`` so scheduling, timesheets and
leave accounting treat those days correctly.

Features
========

* Downloads the schedule from `NateScarlet/holiday-cn
  <https://github.com/NateScarlet/holiday-cn>`_ (URL is configurable).
* Holidays (放假) become company-level public holidays (``time_type='leave'``).
* Make-up work days (调休补班) become working days, injected into the
  calendar's attendance intervals.
* Idempotent sync: re-running never duplicates days or leaves.
* Scheduled auto-update plus a manual "Sync China Holidays" button on the
  company form.

Installation
============

Install ``hr_holidays_china``; it requires ``hr_holidays`` (bundled with Odoo)
and the ``requests`` Python package.

Configuration
=============

1. Open *Settings → Companies → Companies*, open a company and go to the
   *China Holidays* tab.
2. Optionally pick a target *China Holidays Calendar* (defaults to the
   company's default working calendar).
3. Toggle *Auto-update China Holidays*.
4. Click *Sync China Holidays* to import the current and next year.

The data source URL is stored in the system parameter
``hr_holidays_china.url_template`` and defaults to
``https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json``.

Imported days are listed under *Time Off → Configuration → China Holidays*.
