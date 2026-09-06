from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


OPERATORS = {
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "in": lambda a, b: a in b if b else False,
    "not in": lambda a, b: a not in b if b else False,
    "like": lambda a, b: b in str(a) if a and b else False,
}


def _match_domain(row, domain):
    if not domain:
        return True
    if isinstance(domain, str):
        domain = safe_eval(domain)
    tokens = list(domain or [])

    def consume(index):
        if index >= len(tokens):
            raise ValidationError("Incomplete dataset filter domain.")
        token = tokens[index]
        if token == "!":
            value, next_index = consume(index + 1)
            return not value, next_index
        if token in ("&", "|"):
            left, next_index = consume(index + 1)
            right, next_index = consume(next_index)
            return (left and right if token == "&" else left or right), next_index
        if isinstance(token, list) and token and token[0] in ("&", "|", "!"):
            return _match_domain(row, token), index + 1
        return _match_single_condition(row, token), index + 1

    results = []
    index = 0
    while index < len(tokens):
        result, index = consume(index)
        results.append(result)
    return all(results)


def _match_single_condition(row, condition):
    if not isinstance(condition, (list, tuple)) or len(condition) != 3:
        raise ValidationError(f"Invalid dataset filter condition: {condition!r}")
    field, operator, value = condition
    row_value = row.get(field)
    negated = False
    if operator.startswith("!"):
        operator = operator[1:]
        negated = True
    if operator.startswith("not "):
        operator = operator[4:]
        negated = True
    op_func = OPERATORS.get(operator)
    if not op_func:
        raise ValidationError(f"Unsupported dataset filter operator: {operator}")
    result = op_func(row_value, value)
    return not result if negated else result


class Dataset(models.Model):
    _name = "dataset"
    _description = "Dataset"
    _order = "id desc"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    source_id = fields.Many2one("dataset.source", required=True)
    package_id = fields.Many2one("dataset.package", index=True)
    manifest_id = fields.Many2one("dataset.manifest", ondelete="set null")
    description = fields.Text()
    chunk_type = fields.Selection(
        [
            ("pdf", "PDF"),
            ("csv", "CSV"),
            ("docx", "Word"),
            ("xlsx", "Excel"),
            ("pptx", "PowerPoint"),
            ("json", "JSON"),
            ("jsonl", "JSONL"),
            ("parquet", "Parquet"),
            ("txt", "Text"),
            ("md", "Markdown"),
            ("image", "Image"),
        ],
        string="Chunk Type",
        default="csv",
    )
    key_fields = fields.Json(
        default=[], help="Ordered metadata keys used as chunk-key path components"
    )
    chunk_ids = fields.One2many("dataset.data_chunk", "dataset_id", string="Chunks")
    filter_domain = fields.Char(
        help="Odoo domain expression to filter manifest values, e.g. [('date', '=', '2024')]"
    )
    total_chunks = fields.Integer(compute="_compute_total_chunks", store=True)
    filtered_total_chunks = fields.Integer(
        string="Expected Chunks",
        compute="_compute_filtered_total_chunks",
        store=True,
        help="Number of values after applying filter_domain",
    )
    fill_rate = fields.Float(
        compute="_compute_fill_rate",
        store=True,
        digits=(5, 4),
        help="Actual chunk count divided by the filtered expected chunk count.",
    )
    tag_ids = fields.Many2many(
        "dataset.tag", "dataset_tag_rel", "dataset_id", "tag_id", string="Tags"
    )

    _code_source_unique = models.Constraint(
        "unique(code, source_id)", "Dataset code must be unique per source!"
    )
    _name_source_unique = models.Constraint(
        "unique(name, source_id)", "Dataset name must be unique per source!"
    )

    @staticmethod
    def _key_component(value, label):
        if value is None or value is False:
            raise ValidationError(f"{label} is required for a chunk key.")
        component = str(value)
        if not component or not component.strip():
            raise ValidationError(f"{label} cannot be empty in a chunk key.")
        if component in (".", ".."):
            raise ValidationError(f"{label} cannot be '{component}' in a chunk key.")
        if "/" in component or "\\" in component:
            raise ValidationError(
                f"{label} cannot contain slash or backslash in a chunk key."
            )
        return component

    def build_chunk_key(self, metadata):
        self.ensure_one()
        source_code = self._key_component(self.source_id.code, "Source code")
        dataset_code = self._key_component(self.code, "Dataset code")
        chunk_type = self._key_component(self.chunk_type, "Chunk type")
        key_fields = self.key_fields or []
        metadata = metadata or {}
        values = []
        for field_name in key_fields:
            field_name = self._key_component(field_name, "Key field name")
            if field_name not in metadata:
                raise ValidationError(
                    f"Metadata value for key field '{field_name}' is required."
                )
            values.append(
                self._key_component(
                    metadata[field_name], f"Metadata value for '{field_name}'"
                )
            )
        suffix = "/" + "/".join(values) if values else ""
        return f"{source_code}/{dataset_code}{suffix}.{chunk_type}"

    @classmethod
    def parse_chunk_key(cls, key, key_fields=None):
        if not key or not isinstance(key, str):
            raise ValidationError("Chunk key cannot be empty.")
        if "\\" in key:
            raise ValidationError("Chunk key cannot contain backslashes.")
        try:
            prefix, chunk_type = key.rsplit(".", 1)
        except ValueError as error:
            raise ValidationError(f"Invalid chunk key format: {key}") from error
        path_parts = prefix.split("/")
        key_fields = key_fields or []
        expected_count = 2 + len(key_fields)
        if len(path_parts) != expected_count:
            raise ValidationError(
                f"Invalid chunk key {key!r}: expected {expected_count} path components, got {len(path_parts)}."
            )
        source_code = cls._key_component(path_parts[0], "Source code")
        dataset_code = cls._key_component(path_parts[1], "Dataset code")
        chunk_type = cls._key_component(chunk_type, "Chunk type")
        metadata = {}
        for field_name, value in zip(key_fields, path_parts[2:]):
            field_name = cls._key_component(field_name, "Key field name")
            metadata[field_name] = cls._key_component(
                value, f"Metadata value for '{field_name}'"
            )
        return {
            "source_code": source_code,
            "dataset_code": dataset_code,
            "chunk_type": chunk_type,
            "metadata": metadata,
        }

    def write(self, vals):
        key_fields = {"source_id", "code", "chunk_type", "key_fields"}
        if key_fields.intersection(vals) and any(record.chunk_ids for record in self):
            raise ValidationError(
                "Source, code, chunk type, and key fields cannot change after chunks exist."
            )
        return super().write(vals)

    def action_view_chunks(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "dataset.action_data_chunk"
        )
        action["domain"] = [("dataset_id", "=", self.id)]
        action["context"] = {"default_dataset_id": self.id}
        return action

    @api.depends("chunk_ids")
    def _compute_total_chunks(self):
        for record in self:
            record.total_chunks = len(record.chunk_ids)

    @api.depends("manifest_id", "manifest_id.values", "filter_domain")
    def _compute_filtered_total_chunks(self):
        for record in self:
            total = 0
            if record.manifest_id and record.manifest_id.values:
                values = record.manifest_id.values
                if record.filter_domain:
                    domain = safe_eval(record.filter_domain)
                    total = len([value for value in values if _match_domain(value, domain)])
                else:
                    total = len(values)
            record.filtered_total_chunks = total

    @api.depends("total_chunks", "filtered_total_chunks")
    def _compute_fill_rate(self):
        for record in self:
            expected = record.filtered_total_chunks
            record.fill_rate = record.total_chunks / expected if expected else 0.0
