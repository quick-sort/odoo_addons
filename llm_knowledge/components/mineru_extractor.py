"""Mineru extractor: sends a file to an external MinerU service and returns
the structured JSON it produces. The service base URL and key are taken from
the extractor record's api_url/api_key fields.
"""

import logging
import posixpath

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class MineruExtractor(Component):
    _name = "llm.mineru.extractor"
    _inherit = "llm.resource.extractor.component"
    _usage = "mineru"
    _input = "file"
    _output_format = "json"

    def _parse_endpoint(self):
        base = (self.collection.api_url or "").rstrip("/")
        if not base:
            raise UserError(
                _(
                    "No API URL configured for the '%s' extractor. "
                    "Set it on the extractor record.",
                    self.collection.name,
                )
            )
        return posixpath.join(base, "parse")

    def extract(self, resource):
        import requests  # lazy import; part of the odoo runtime deps

        content = resource._read_source_bytes()
        headers = {}
        if self.collection.api_key:
            headers["Authorization"] = "Bearer %s" % self.collection.api_key
        resp = requests.post(
            self._parse_endpoint(),
            files={"file": (resource.name or "content", content)},
            headers=headers,
            timeout=300,
        )
        if not resp.ok:
            raise UserError(
                _(
                    "Mineru service returned HTTP %s: %s",
                    resp.status_code,
                    resp.text[:500],
                )
            )
        return resp.json()

    def validate_config(self):
        base = (self.collection.api_url or "").rstrip("/")
        if not base:
            raise UserError(
                _("No API URL configured for the '%s' extractor.", self.collection.name)
            )
        import requests  # noqa: PLC0415

        resp = requests.get(base, timeout=15)
        if not resp.ok:
            raise UserError(
                _(
                    "Mineru service at '%s' is not reachable (HTTP %s).",
                    base,
                    resp.status_code,
                )
            )
