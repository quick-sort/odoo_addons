# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Extractor backend model.

A ``knowledge.extractor`` is the polymorphic host for extraction
implementations: the ``extractor_type`` selection maps to a component
``usage`` in the ``knowledge.extractor`` collection, mirroring how
``storage.backend`` resolves adapters (see ``storage_backend``). Concrete
extractors are plain components (markitdown, mineru, trafilatura...) that may
live in this addon or in extending addons.
"""

from odoo import api, fields, models


class KnowledgeExtractor(models.Model):
    _name = "knowledge.extractor"
    _description = "Knowledge Extractor"
    _inherit = ["collection.base", "server.env.mixin"]
    _backend_name = "knowledge_extractor"

    name = fields.Char(required=True)
    extractor_type = fields.Selection(
        selection=lambda self: self._selection_extractor_type(),
        required=True,
    )
    active = fields.Boolean(default=True)
    api_url = fields.Char(
        string="API URL",
        help="Base URL of an external extraction service (used by e.g. mineru).",
    )
    api_key = fields.Char(
        string="API Key",
        help="Credentials for the external extraction service.",
    )
    kb_ids = fields.One2many(
        "knowledge.base",
        "extractor_id",
        string="Knowledge Bases",
    )

    @property
    def _server_env_fields(self):
        base_fields = super()._server_env_fields
        extractor_fields = {
            "api_url": {},
            "api_key": {},
        }
        extractor_fields.update(base_fields)
        return extractor_fields

    @api.model
    def _selection_extractor_type(self):
        """Build the extractor_type selection from registered usages."""
        return [
            (usage, usage.replace("_", " ").title())
            for usage in self._get_available_extractors()
        ]

    @api.model
    def _get_available_extractors(self):
        """Usages of the extractors shipped with this addon.

        Empty here: concrete extractors (markitdown, mineru, trafilatura...)
        live in their own extending addons, which override this to register
        their usages, e.g.::

            return super()._get_available_extractors() + ["new_extractor"]
        """
        return []

    def _get_adapter(self):
        """Return the component implementing this extractor's ``usage``."""
        self.ensure_one()
        if not self.extractor_type:
            return None
        with self.work_on(self._name) as work:
            return work.component(usage=self.extractor_type)

    def _get_output_format(self):
        """Output file format of this extractor: ``md`` or ``json``."""
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
        except Exception as err:
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
