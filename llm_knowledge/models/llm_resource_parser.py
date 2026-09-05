import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMResourceParser(models.Model):
    _inherit = "llm.resource"

    parser = fields.Selection(
        selection=[
            ("default", "Default Parser"),
            ("json", "JSON Parser"),
        ],
        string="Parser",
        default="default",
        required=True,
        help="Method used to parse resource content",
        tracking=True,
    )

    def parse(self):
        resources = self._lock(state_filter="retrieved")
        if not resources:
            return False

        for resource in resources:
            try:
                record = self.env[resource.res_model].browse(resource.res_id)
                if not record.exists():
                    raise UserError(_("Referenced record not found"))

                if hasattr(record, "llm_get_fields"):
                    resource_fields = record.llm_get_fields(record)
                else:
                    resource_fields = resource.get_fields(record)

                success = False
                for resource_field in resource_fields:
                    success = resource._parse_field(record, resource_field) or success

                if success:
                    resource.write({"state": "parsed"})
                    self.env.cr.commit()
                    resource._post_styled_message(
                        "Resource successfully parsed", "success"
                    )
                else:
                    resource._post_styled_message(
                        "Parsing completed but did not return success", "warning"
                    )
            except Exception as error:  # noqa: BLE001
                _logger.exception("Error parsing resource %s", resource.id)
                resource._post_styled_message(
                    f"Error parsing resource: {error}", "error"
                )
                if resource.collection_ids:
                    resource.collection_ids._post_styled_message(
                        f"Error parsing resource: {error}", "error"
                    )
            finally:
                resource._unlock()
        resources._unlock()

    def _get_parser(self, record, field_name, mimetype):
        """Resolve a dependency-free parser; optional addons override this hook."""
        if self.parser != "default":
            return getattr(self, f"parse_{self.parser}")

        record_name = (
            record.display_name
            if hasattr(record, "display_name")
            else f"{record._name} #{record.id}"
        )
        is_markdown = ".md" in record_name.lower()
        if mimetype == "application/octet-stream" and is_markdown:
            return self._parse_text
        if mimetype.startswith("text/") and "html" not in mimetype:
            return self._parse_text
        if mimetype.startswith("image/"):
            return self._parse_image
        if mimetype == "application/json":
            return self.parse_json
        return self._parse_default

    def _parse_field(self, record, field):
        self.ensure_one()
        parser_method = self._get_parser(record, field["field_name"], field["mimetype"])
        return parser_method(record, field)

    def get_fields(self, record):
        self.ensure_one()
        results = []

        record_name_field = (
            "display_name" if hasattr(record, "display_name") else "name"
        )
        record_name = (
            record[record_name_field]
            if hasattr(record, record_name_field)
            else f"{record._name} #{record.id}"
        )
        if record_name:
            results.append(
                {
                    "field_name": record_name_field,
                    "mimetype": "text/plain",
                    "rawcontent": record_name,
                }
            )

        common_text_fields = [
            "description",
            "note",
            "comment",
            "message",
            "content",
            "body",
            "text",
        ]
        for field_name in common_text_fields:
            if hasattr(record, field_name) and record[field_name]:
                results.append(
                    {
                        "field_name": field_name,
                        "mimetype": "text/plain",
                        "rawcontent": record[field_name],
                    }
                )
        return results

    def parse_json(self, record, _field):
        self.ensure_one()
        record_name = (
            record.display_name
            if hasattr(record, "display_name")
            else f"{record._name} #{record.id}"
        )

        record_data = {}
        for field_name, field_definition in record._fields.items():
            try:
                if field_definition.type == "binary" or field_name.startswith("_"):
                    continue
                value = record[field_name]
                if field_definition.type == "many2one" and value:
                    record_data[field_name] = {
                        "id": value.id,
                        "name": value.display_name,
                    }
                elif field_definition.type in ("many2many", "one2many"):
                    record_data[field_name] = [
                        {"id": item.id, "name": item.display_name} for item in value
                    ]
                else:
                    record_data[field_name] = value
            except Exception as error:  # noqa: BLE001
                _logger.warning("Skipping field %s: %s", field_name, error)

        content = [
            f"# {record_name}",
            "\n## JSON Data\n",
            "```json",
            json.dumps(record_data, indent=2, default=str),
            "```",
        ]
        self._write_content_to_backend("\n".join(content))
        return True

    def _parse_text(self, _record, field):
        self._write_content_to_backend(field["rawcontent"])
        return True

    def _parse_image(self, record, _field):
        self._write_content_to_backend(
            f"![{record.name}](/web/image/{record.id})"
        )
        return True

    def _parse_default(self, record, field):
        mimetype = field["mimetype"]
        self._write_content_to_backend(
            f"""
            # {record.name}

            **File Type**: {mimetype}
            **Description**: This file type requires an optional parser addon.
            **Access**: [Open file](/web/content/{record.id})
            """
        )
        return True
