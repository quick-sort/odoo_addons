"""MinerU external-service binary-envelope extractor."""

import json
import posixpath

import requests

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component


class MineruExtractor(Component):
    _name = "llm.mineru.extractor"
    _inherit = "llm.document.extractor.component"
    _usage = "mineru"

    def _parse_endpoint(self):
        base = (self.collection.api_url or "").rstrip("/")
        if not base:
            raise UserError(
                _(
                    "No API URL configured for the '%s' extractor.",
                    self.collection.name,
                )
            )
        return posixpath.join(base, "parse")

    def _structured_markdown(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("markdown", "md", "content", "text"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate
            for key in ("data", "result", "document", "output"):
                if key in value:
                    candidate = self._structured_markdown(value[key])
                    if candidate:
                        return candidate
        return "```json\n%s\n```" % json.dumps(
            value, ensure_ascii=False, default=str, indent=2
        )

    def extract(self, envelope):
        headers = {}
        if self.collection.api_key:
            headers["Authorization"] = "Bearer %s" % self.collection.api_key
        response = requests.post(
            self._parse_endpoint(),
            files={
                "file": (
                    envelope.get("filename") or "content.bin",
                    envelope["content"],
                    envelope.get("mimetype") or "application/octet-stream",
                )
            },
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
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return self._structured_markdown(payload)

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
