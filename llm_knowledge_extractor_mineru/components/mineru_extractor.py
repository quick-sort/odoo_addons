"""MinerU external-service file extractor."""

import posixpath

import requests

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component


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
        content = resource._read_source_bytes()
        headers = {}
        if self.collection.api_key:
            headers["Authorization"] = "Bearer %s" % self.collection.api_key
        response = requests.post(
            self._parse_endpoint(),
            files={"file": (resource.name or "content", content)},
            headers=headers,
            timeout=300,
        )
        if not response.ok:
            raise UserError(
                _(
                    "MinerU service returned HTTP %s: %s",
                    response.status_code,
                    response.text[:500],
                )
            )
        return response.json()

    def validate_config(self):
        base = (self.collection.api_url or "").rstrip("/")
        if not base:
            raise UserError(
                _("No API URL configured for the '%s' extractor.", self.collection.name)
            )
        response = requests.get(base, timeout=15)
        if not response.ok:
            raise UserError(
                _(
                    "MinerU service at '%s' is not reachable (HTTP %s).",
                    base,
                    response.status_code,
                )
            )
