from odoo import api, fields, models


class GanttMixin(models.AbstractModel):
    _name = "gantt.mixin"
    _description = "Gantt Date Mapping Mixin"

    gantt_date_start = fields.Datetime(
        string="Gantt Start",
        compute="_compute_gantt_dates",
        inverse="_inverse_gantt_dates",
        search="_search_gantt_date_start",
    )
    gantt_date_stop = fields.Datetime(
        string="Gantt Stop",
        compute="_compute_gantt_dates",
        inverse="_inverse_gantt_dates",
        search="_search_gantt_date_stop",
    )

    def _gantt_date_fields(self):
        """Return the ``(start, stop)`` field names backing the Gantt dates."""
        if self._abstract:
            # Registry resolves compute dependencies on the abstract model itself.
            return ()
        raise NotImplementedError(
            f"{self._name} inherits gantt.mixin but does not define _gantt_date_fields()"
        )

    @api.depends(lambda self: self._gantt_date_fields())
    def _compute_gantt_dates(self):
        for record in self:
            start_field, stop_field = record._gantt_date_fields()
            record.gantt_date_start = record[start_field]
            record.gantt_date_stop = record[stop_field]

    def _inverse_gantt_dates(self):
        # Both aliases share this inverse, so Odoo calls it once per write.
        # Use write() (not cache assignment) so model write() overrides fire.
        for record in self:
            start_field, stop_field = record._gantt_date_fields()
            vals = {}
            if record.gantt_date_start != record[start_field]:
                vals[start_field] = record.gantt_date_start
            if record.gantt_date_stop != record[stop_field]:
                vals[stop_field] = record.gantt_date_stop
            if vals:
                record.write(vals)

    def _search_gantt_date_start(self, operator, value):
        return [(self._gantt_date_fields()[0], operator, value)]

    def _search_gantt_date_stop(self, operator, value):
        return [(self._gantt_date_fields()[1], operator, value)]

    @api.model
    def default_get(self, field_names):
        defaults = super().default_get(field_names)
        if self._abstract:
            return defaults
        start_field, stop_field = self._gantt_date_fields()
        for alias, target in (
            ("gantt_date_start", start_field),
            ("gantt_date_stop", stop_field),
        ):
            # Never default a computed alias: it would be written by create()
            # and its inverse would override an explicit backing value.
            defaults.pop(alias, None)
            context_key = "default_" + alias
            if (
                context_key in self.env.context
                and target in field_names
                and "default_" + target not in self.env.context
            ):
                target_field = self._fields[target]
                value = target_field.convert_to_cache(
                    self.env.context[context_key], self, validate=False
                )
                defaults[target] = target_field.convert_to_write(value, self)
        return defaults
