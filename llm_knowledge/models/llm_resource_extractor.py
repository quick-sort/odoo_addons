import logging

from odoo import fields, models

from odoo.addons.component.exception import NoComponentError

_logger = logging.getLogger(__name__)


def archive_dangling_extractor(records):
    """Archive extractor configurations when their implementation is removed."""
    if records:
        records.write({"active": False})


class LLMResourceExtractor(models.Model):
    """Polymorphic host for optional file and URL extraction backends."""

    _name = "llm.resource.extractor"
    _description = "LLM Resource Extractor"
    _inherit = ["collection.base"]
    _backend_name = "llm_resource_extractor"

    name = fields.Char(required=True)
    extractor_type = fields.Selection(
        # The core addon ships no implementation. Optional extractor addons
        # contribute validated, translatable values with ``selection_add``.
        selection=[],
        required=True,
    )
    active = fields.Boolean(default=True)

    def _get_adapter(self):
        """Return the component for this usage, or ``None`` if its addon is absent."""
        self.ensure_one()
        if not self.extractor_type:
            return None
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=self.extractor_type)
        except NoComponentError:
            _logger.info(
                "No installed component for extractor usage %s",
                self.extractor_type,
            )
            return None

    def _get_output_format(self):
        adapter = self._get_adapter()
        return getattr(adapter, "_output_format", "md") if adapter else "md"

    def action_test_config(self):
        self.ensure_one()
        adapter = self._get_adapter()
        if adapter is None:
            title = self.env._("Extractor Unavailable")
            message = self.env._(
                "Install the optional addon that provides extractor type '%s'.",
                self.extractor_type,
            )
            msg_type = "warning"
        else:
            try:
                adapter.validate_config()
                title = self.env._("Connection Test Succeeded!")
                message = self.env._("Everything seems properly set up!")
                msg_type = "success"
            except Exception as error:  # noqa: BLE001
                title = self.env._("Connection Test Failed!")
                message = str(error)
                msg_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }
