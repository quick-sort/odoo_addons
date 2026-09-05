from markdownify import markdownify

from odoo import models


class LLMResourceParser(models.Model):
    _inherit = "llm.resource"

    def _get_parser(self, record, field_name, mimetype):
        if self.parser == "default" and "html" in mimetype:
            return self._parse_html
        return super()._get_parser(record, field_name, mimetype)

    def _parse_html(self, _record, field):
        self._write_content_to_backend(markdownify(field["rawcontent"]))
        return True
