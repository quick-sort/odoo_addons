import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LLMResourceExtractor(models.Model):
    """Polymorphic host for file/URL extraction backends.

    Mirrors the ``storage.backend`` / ``knowledge.extractor`` pattern: the
    ``extractor_type`` selection maps to a component ``usage`` registered
    against this model's ``collection.base`` collection. Concrete extractors
    (markitdown, mineru, trafilatura, ...) are plain components living in
    this addon or extending addons, each declaring ``_input`` ("file" or
    "url") and ``_output_format`` ("md" or "json").
    """

    _name = "llm.resource.extractor"
    _description = "LLM Resource Extractor"
    _inherit = ["collection.base"]
    _backend_name = "llm_resource_extractor"

    name = fields.Char(required=True)
    extractor_type = fields.Selection(
        selection=lambda self: self._selection_extractor_type(),
        required=True,
    )
    active = fields.Boolean(default=True)
    api_url = fields.Char(
        string="API URL",
        help="Base URL of an external extraction service (e.g. MinerU).",
    )
    api_key = fields.Char(
        string="API Key",
        help="Credentials for the external extraction service.",
    )

    @api.model
    def _selection_extractor_type(self):
        return [
            (usage, usage.replace("_", " ").title())
            for usage in self._get_available_extractors()
        ]

    @api.model
    def _get_available_extractors(self):
        """Usages of the extractors shipped with this addon.

        markitdown/trafilatura ship in this addon directly (their python
        deps are imported lazily so installing without them still works).
        mineru is also registered here since it only requires an external
        HTTP service, no local package.
        """
        return ["markitdown", "trafilatura", "mineru"]

    def _get_adapter(self):
        """Return the component implementing this extractor's usage."""
        self.ensure_one()
        if not self.extractor_type:
            return None
        with self.work_on(self._name) as work:
            return work.component(usage=self.extractor_type)

    def _get_output_format(self):
        """Output format of this extractor: 'md' or 'json'."""
        adapter = self._get_adapter()
        return getattr(adapter, "_output_format", "md") if adapter else "md"

    def action_test_config(self):
        self.ensure_one()
        adapter = self._get_adapter()
        if adapter is None or not hasattr(adapter, "validate_config"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Connection Test Skipped!"),
                    "message": self.env._(
                        "This extractor type does not support connection testing."
                    ),
                    "type": "warning",
                    "sticky": False,
                },
            }
        try:
            adapter.validate_config()
            title = self.env._("Connection Test Succeeded!")
            message = self.env._("Everything seems properly set up!")
            msg_type = "success"
        except Exception as err:  # noqa: BLE001
            title = self.env._("Connection Test Failed!")
            message = str(err)
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
