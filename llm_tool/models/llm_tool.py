"""``llm.tool`` -- the registry of callables exposed to an LLM.

One row is one *exposure*: a name the LLM can call, pointing at a callable.

Two axes, deliberately kept orthogonal (they used to be conflated into a single
``implementation`` selection with nine mixed values):

``executor`` -- **how** to run it. A closed set:

    ``model_method``    ``env[res_model][.browse(res_id)].res_method(**params)``
    ``server_action``   run an ``ir.actions.server``
    ``mcp``             call a remote MCP server, added by ``llm.mcp.client``

``source`` -- **who owns the metadata** and the row's lifecycle:

    ``code``      an ``@llm_tool`` decorated method. ``description`` comes from
                  its docstring, ``input_schema`` from its signature, both
                  refreshed at startup. The scan also archives the row when the
                  method disappears from the code.
    ``manual``    created by hand (XML or web). Nothing is derived; the user
                  must supply ``description`` and ``input_schema``, and the
                  scan never touches the row.
    ``remote``    imported from an MCP server, refreshed when the client syncs.

Several rows may point at the same callable -- that is how one function gets
exposed twice with different names, descriptions or narrowed schemas. Only one
of them may be ``source='code'``: that is the row the scan owns.
"""

import inspect
import json
import logging
from typing import Any

from pydantic import create_model

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

JSON_SCHEMA_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}

#: Annotation fields mirrored into the MCP ``ToolAnnotations`` payload, mapped
#: to their camelCase wire names.
ANNOTATION_HINTS = {
    "read_only_hint": "readOnlyHint",
    "idempotent_hint": "idempotentHint",
    "destructive_hint": "destructiveHint",
    "open_world_hint": "openWorldHint",
}

#: Columns the startup scan owns on a ``source='code'`` row. Everything else --
#: ``is_default``, ``requires_user_consent`` -- stays the user's.
CODE_OWNED_COLUMNS = (
    "name",
    "description",
    "input_schema",
    "title",
    "active",
    *ANNOTATION_HINTS,
)


def _python_type(prop):
    """Map one JSON Schema property to a Python type for validation.

    Anything not covered -- ``anyOf``, ``$ref``, unions, missing ``type`` --
    maps to :data:`Any`. Being permissive is deliberate: this type is used to
    *coerce* values coming from an LLM, and guessing wrong would reject calls
    that the tool itself would have accepted.
    """
    if not isinstance(prop, dict):
        return Any

    json_type = prop.get("type")
    if isinstance(json_type, list):
        # e.g. ["string", "null"] -- validate against the non-null branch.
        json_type = next((t for t in json_type if t != "null"), None)

    base = JSON_SCHEMA_TYPES.get(json_type)
    if base is None:
        return Any

    if base is list:
        item_type = _python_type(prop.get("items"))
        return list if item_type is Any else list[item_type]

    return base


def model_from_input_schema(schema, name="ToolArguments"):
    """Build a pydantic model enforcing ``schema``.

    A pydantic model rather than :func:`jsonschema.validate` because LLMs
    routinely send numbers and booleans as strings; pydantic coerces them,
    plain schema validation would only reject them.

    Unknown keys are ignored rather than rejected, for the same reason: models
    hallucinate extra arguments, and dropping them keeps the call working.
    """
    properties = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])

    model_fields = {}
    for prop_name, prop in properties.items():
        annotation = _python_type(prop)
        if prop_name in required:
            default = ...
        elif isinstance(prop, dict) and "default" in prop:
            default = prop["default"]
        else:
            # Optional with no declared default: leave it unset so the
            # callable's own Python default applies (see LLMTool.execute).
            annotation = annotation if annotation is Any else annotation | None
            default = None
        model_fields[prop_name] = (annotation, default)

    return create_model(name, **model_fields)


_logger = logging.getLogger(__name__)


def _func_metadata():
    """Import MCP's ``func_metadata``, whichever subpackage provides it.

    mcp 2.0 renamed the ``fastmcp`` subpackage to ``mcpserver``.
    """
    try:
        from mcp.server.mcpserver.utilities.func_metadata import func_metadata
    except ImportError:
        from mcp.server.fastmcp.utilities.func_metadata import func_metadata
    return func_metadata


def derive_input_schema(method):
    """Build an MCP-compatible JSON Schema from a method signature.

    ``method`` must be **bound**: an unbound function would expose ``self`` as
    a tool parameter.

    Returns ``None`` when the schema cannot be derived, so callers can fall
    back instead of failing (a decorated method whose annotations reference a
    type that is not importable at scan time, for instance).
    """
    try:
        func_meta = _func_metadata()(method)
        return func_meta.arg_model.model_json_schema(by_alias=True)
    except Exception as error:  # noqa: BLE001 - schema is best-effort here
        _logger.warning(
            "Could not derive input schema for %s: %s",
            getattr(method, "__qualname__", method),
            error,
        )
        return None


class LLMTool(models.Model):
    _name = "llm.tool"
    _description = "LLM Tool"
    # ``collection.base`` makes this model a component collection, so executor
    # components can be registered against it (see llm_tool/components/);
    # ``llm.service.dispatch.mixin`` resolves them.
    _inherit = ["mail.thread", "collection.base", "llm.service.dispatch.mixin"]

    # ------------------------------------------------------------------
    # Identity and dispatch
    # ------------------------------------------------------------------
    name = fields.Char(
        required=True,
        tracking=True,
        help="The name the LLM calls this tool by. Unique across the registry.",
    )
    executor = fields.Selection(
        # Closed set. A static list is what makes the value validated on
        # write and the label translatable -- see llm.service.dispatch.mixin.
        selection=[
            ("model_method", "Model Method"),
            ("server_action", "Server Action"),
            ("mcp", "MCP"),
        ],
        required=True,
        default="model_method",
        tracking=True,
        help="How this tool is run. Each value is the '_usage' of a "
        "'llm.tool.executor' component (see llm_tool/components/).",
    )
    source = fields.Selection(
        [
            ("code", "Code (@llm_tool)"),
            ("manual", "Manual"),
            ("remote", "Remote (MCP)"),
        ],
        required=True,
        default="manual",
        tracking=True,
        help="Who owns this row's description and schema. 'Code': derived from "
        "the decorated method and refreshed on restart, and the row is archived "
        "when the method disappears. 'Manual': yours, never touched by the "
        "scan. 'Remote': imported from an MCP server.",
    )
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # Executor configuration
    # ------------------------------------------------------------------
    res_model = fields.Char(
        string="Model",
        help="Model holding the callable, for the 'Model Method' executor "
        "(e.g. 'sale.order').",
    )
    res_method = fields.Char(
        string="Method",
        help="Method name for the 'Model Method' executor. The 'MCP' executor "
        "stores the remote tool name here.",
    )
    res_id = fields.Integer(
        string="Record ID",
        help="Optional, for the 'Model Method' executor: call the method on "
        "this record instead of on the model. Leave empty for a model-level "
        "call.",
    )
    server_action_id = fields.Many2one(
        "ir.actions.server",
        string="Server Action",
        ondelete="cascade",
        help="Action run by the 'Server Action' executor. Tool arguments arrive "
        "in the context key 'llm_tool_params'.",
    )
    mcp_client_id = fields.Many2one(
        "llm.mcp.client",
        string="MCP Service",
        ondelete="cascade",
        help="External MCP server that provides this tool, for the 'MCP' "
        "executor. The remote tool name lives in 'res_method', same as the "
        "'Model Method' executor's method name -- a tool's identity is always "
        "(executor, res_model/mcp_client_id, res_method) regardless of where "
        "the callable actually lives.",
    )

    # ------------------------------------------------------------------
    # Metadata shown to the LLM
    # ------------------------------------------------------------------
    description = fields.Text(
        tracking=True,
        help="What the tool does, sent to the LLM. Derived from the method "
        "docstring when source is 'Code'; yours to write otherwise.",
    )
    input_schema = fields.Text(
        string="Input Schema",
        help="JSON Schema of the accepted parameters. Derived from the method "
        "signature when source is 'Code'. This is what execute() validates "
        "against, so editing it on a 'Manual' row is a real restriction.",
    )

    # ------------------------------------------------------------------
    # MCP annotations
    # ------------------------------------------------------------------
    title = fields.Char(help="Human-readable title for the tool")
    read_only_hint = fields.Boolean(
        string="Read Only",
        default=False,
        help="If true, the tool does not modify its environment",
    )
    idempotent_hint = fields.Boolean(
        string="Idempotent",
        default=False,
        help="If true, calling the tool repeatedly with the same arguments will "
        "have no additional effect",
    )
    destructive_hint = fields.Boolean(
        string="Destructive",
        default=True,
        help="If true, the tool may perform destructive updates. Defaults to "
        "true on purpose: assume dangerous until declared otherwise.",
    )
    open_world_hint = fields.Boolean(
        string="Open World",
        default=True,
        help="If true, this tool may interact with an 'open world' of external "
        "entities. Defaults to true on purpose.",
    )

    # ------------------------------------------------------------------
    # User configuration
    # ------------------------------------------------------------------
    requires_user_consent = fields.Boolean(
        default=False,
        help="If true, the user must consent before this tool runs",
    )
    is_default = fields.Boolean(
        default=False,
        help="Include this tool in every LLM request. Beware of enabling it on "
        "two exposures of the same callable: the model would see both.",
    )

    _unique_tool_name = models.Constraint(
        'UNIQUE(name)',
        'A tool with this name already exists! Tool names must be unique.',
    )

    # ------------------------------------------------------------------
    # Executor dispatch
    # ------------------------------------------------------------------
    #
    # Resolution lives in ``llm.service.dispatch.mixin``. Executors are the
    # ``llm.tool.executor`` components (see llm_tool/components/), one per
    # executor, resolved by ``_usage`` == ``executor``. ``execute`` is
    # mandatory on every executor; ``validate`` is optional -- not every
    # executor needs extra fields to check -- and probed with
    # ``_has_service_method`` before being called (see
    # :meth:`_check_executor_configuration`), rather than declared as a stub
    # on ``llm.tool.executor``.

    _service_field = "executor"

    #: Executors read the record from ``self.collection`` instead of a
    #: leading positional argument: an executor method's signature is itself
    #: the JSON Schema advertised to the LLM (via callable introspection for
    #: 'model_method'), so an extra leading parameter would show up as a tool
    #: argument.
    _dispatch_pass_record = False

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("source", "description", "input_schema")
    def _check_manual_metadata(self):
        """A 'Manual' row has nothing to derive from, so it must be filled in.

        'Code' and 'Remote' rows are exempt: they are created before the scan
        or the client import fills them.
        """
        for tool in self:
            if tool.source != "manual":
                continue
            if not (tool.description or "").strip():
                raise ValidationError(
                    _(
                        "Tool '%(name)s' is manual, so it needs a description: "
                        "there is no docstring to derive one from.",
                        name=tool.name,
                    )
                )
            if not (tool.input_schema or "").strip():
                raise ValidationError(
                    _(
                        "Tool '%(name)s' is manual, so it needs an input schema: "
                        "there is no signature to derive one from.",
                        name=tool.name,
                    )
                )

    @api.constrains("executor", "res_model", "res_method", "server_action_id", "mcp_client_id")
    def _check_executor_configuration(self):
        """Delegate to the executor component's optional ``validate`` method.

        Not every executor needs one (there is nothing to check without extra
        fields), so it is probed with :meth:`_has_service_method` rather than
        called unconditionally.
        """
        for tool in self:
            if tool._has_service_method("validate"):
                tool._dispatch("validate", tool)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _contract_source(self):
        """Return the callable defining this tool's contract, or ``None``.

        Non-``None`` only for ``source='code'``: that is the whole meaning of
        the field. ``manual`` and ``remote`` rows carry their metadata in the
        database and have nothing to reflect on.

        Never raises. Callers run where an exception is unacceptable:
        ``_register_hook`` (it would take down the registry load) and
        ``get_tool_definition`` (it would break listing tools for the LLM).
        """
        self.ensure_one()

        if self.source != "code" or self.executor != "model_method":
            return None

        try:
            method = self._dispatch("resolve_callable", self)
        except UserError:
            return None
        except Exception:  # noqa: BLE001 - callers cannot tolerate a raise
            _logger.exception(
                "Could not resolve the callable of tool '%s' (%s.%s)",
                self.name,
                self.res_model,
                self.res_method,
            )
            return None

        if not getattr(method, "_is_llm_tool", False):
            _logger.warning(
                "Tool '%s' has source='code' but %s.%s is not decorated with "
                "@llm_tool",
                self.name,
                self.res_model,
                self.res_method,
            )

        return method

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def get_input_schema(self):
        """Return the tool's input schema.

        The stored field is authoritative -- it is what :meth:`execute`
        validates against. Deriving is only a fallback for a ``source='code'``
        row created since the last scan.
        """
        self.ensure_one()

        if self.input_schema:
            return json.loads(self.input_schema)

        source = self._contract_source()
        schema = derive_input_schema(source) if source is not None else None
        return schema if schema is not None else {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def get_tool_definition(self):
        """Return the MCP-compatible tool definition."""
        self.ensure_one()

        description = self.description
        if not description:
            # A 'code' row created since the last scan has no stored
            # description yet; never advertise a tool without one.
            source = self._contract_source()
            if source is not None:
                description = inspect.getdoc(source) or ""

        from mcp.types import Tool, ToolAnnotations

        # fields.Boolean is never None, so every hint is always present.
        annotations = ToolAnnotations(
            **{alias: self[name] for name, alias in ANNOTATION_HINTS.items()}
        )

        mcp_tool = Tool(
            name=self.name,
            # title goes to BaseMetadata, not ToolAnnotations
            title=self.title or self.name,
            description=description or "",
            inputSchema=self.get_input_schema(),
            annotations=annotations,
        )

        # Return plain dict following 'Models Return Plain Data' pattern.
        # by_alias=True is required: the MCP wire format uses camelCase
        # (inputSchema, readOnlyHint, ...) which the pydantic models declare as
        # field aliases. Without it model_dump() emits the snake_case field
        # names and the payload is not MCP-compliant.
        return mcp_tool.model_dump(exclude_none=True, by_alias=True)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, parameters):
        """Validate ``parameters`` against the stored schema, then run the tool.

        Validation goes through :meth:`get_input_schema` -- the stored schema --
        not through the callable's signature. That makes the schema shown to the
        LLM and the schema actually enforced one and the same, so narrowing it
        on a manual row is a real restriction rather than advice.

        Only keys the caller actually supplied are forwarded, so parameters left
        out keep the callable's own Python defaults.

        Dispatched to the ``llm.tool.executor`` component matching
        :attr:`executor` -- see ``llm_tool/components/``.
        """
        self.ensure_one()

        arguments_model = model_from_input_schema(
            self.get_input_schema(),
            name=f"{self.name}Arguments",
        )
        validated = arguments_model(**(parameters or {}))
        params = validated.model_dump(exclude_unset=True)

        return self._dispatch("execute", params)

    # ------------------------------------------------------------------
    # Registration: _register_hook (scan) -> _sync_tools_to_db (raw SQL)
    # ------------------------------------------------------------------

    #: In-memory registry, populated by _register_hook. No DB access.
    #: {(res_model, res_method): values_dict}
    _tool_registry = {}

    @api.model
    def _register_hook(self):
        super()._register_hook()
        self._scan_tool_decorators()
        self._sync_tools_to_db()

    def _scan_tool_decorators(self):
        """Populate :attr:`_tool_registry` from ``@llm_tool`` decorated methods.

        Walks ``env.registry``, so abstract models count -- that is where the
        built-in tools live (``llm.tool.builtin.*``).
        """
        self._tool_registry.clear()

        for model_name in self.env.registry:
            try:
                model = self.env[model_name]
            except Exception:
                continue

            model_class = type(model)
            for attr_name in dir(model_class):
                if attr_name.startswith("_"):
                    continue
                try:
                    attr = getattr(model_class, attr_name, None)
                    if not (callable(attr) and getattr(attr, "_is_llm_tool", False)):
                        continue
                    # Pass the bound method too: the schema must be derived
                    # without ``self`` in the signature.
                    self._tool_registry[(model_name, attr_name)] = (
                        self._extract_tool_values(
                            model_name,
                            attr_name,
                            attr,
                            bound_method=getattr(model, attr_name, None),
                        )
                    )
                except Exception:
                    continue

    @staticmethod
    def _extract_tool_values(model_name, method_name, method, bound_method=None):
        """Build a values dict from decorator metadata. No DB access.

        Args:
            method: the decorated attribute as found on the model *class*,
                carrying the ``_llm_tool_*`` metadata
            bound_method: the same method bound to a recordset, required to
                derive the schema without ``self``
        """
        metadata = getattr(method, "_llm_tool_metadata", {})
        values = {
            "name": getattr(method, "_llm_tool_name", method_name),
            "executor": "model_method",
            "source": "code",
            "res_model": model_name,
            "res_method": method_name,
            "description": getattr(method, "_llm_tool_description", ""),
            "title": metadata.get("title") or "",
            "active": True,
        }
        for hint in ANNOTATION_HINTS:
            if hint in metadata:
                values[hint] = metadata[hint]

        # An explicit schema on the decorator wins; otherwise derive it from the
        # signature.
        if hasattr(method, "_llm_tool_schema"):
            values["input_schema"] = json.dumps(method._llm_tool_schema, indent=2)
        elif bound_method is not None:
            schema = derive_input_schema(bound_method)
            if schema is not None:
                values["input_schema"] = json.dumps(schema, indent=2)

        return values

    @staticmethod
    def _raw_values_changed(db_row, values):
        """Compare the scanned values with a raw DB row, over owned columns."""
        for column in CODE_OWNED_COLUMNS:
            if column not in values:
                continue
            db_val, new_val = db_row.get(column), values[column]
            # Treat None/False/"" as equivalent
            if not db_val and not new_val:
                continue
            if db_val != new_val:
                return True
        return False

    @api.model
    def _sync_tools_to_db(self):
        """Sync :attr:`_tool_registry` into the ``source='code'`` rows.

        Keyed on ``(res_model, res_method)``, **never on name**: renaming a tool
        in code (``@llm_tool(name=...)``) must update the existing row, not
        create a second one and archive the first -- assistants referencing the
        old row would silently lose the tool.

        Rows with another ``source`` are invisible here, which is what makes
        additional hand-made exposures of the same callable safe.

        Raw SQL bypasses the ORM cache, avoiding the SerializationFailure that
        occurs when load_modules calls flush_all() with dirty ORM state from
        concurrent workers.

        Returns dict: {created: int, updated: int, deactivated: int}.
        """
        cr = self.env.cr

        # Database-specific advisory lock (transaction-scoped, auto-released)
        # so exactly one worker performs the write.
        lock_key = hash(cr.dbname) & 0x7FFFFFFF
        cr.execute("SELECT pg_try_advisory_xact_lock(%s)", [lock_key])
        if not cr.fetchone()[0]:
            _logger.debug("Another worker is syncing tools, skipping")
            return {"created": 0, "updated": 0, "deactivated": 0}

        if not self._tool_registry:
            # An empty scan means "scan found nothing", not "no tools left".
            # Without this guard a failed import would archive every code tool.
            return {"created": 0, "updated": 0, "deactivated": 0}

        columns = ", ".join(CODE_OWNED_COLUMNS)
        cr.execute(
            f"SELECT id, res_model, res_method, {columns}"
            "  FROM llm_tool WHERE source = 'code'"
        )
        existing = {
            (row["res_model"], row["res_method"]): row for row in cr.dictfetchall()
        }

        now = fields.Datetime.now()
        uid = self.env.uid or 1
        created = updated = deactivated = 0

        for key, values in self._tool_registry.items():
            db_row = existing.pop(key, None)

            if db_row:
                if not self._raw_values_changed(db_row, values):
                    continue
                owned = [c for c in CODE_OWNED_COLUMNS if c in values]
                assignments = ", ".join(f"{c} = %s" for c in owned)
                cr.execute(
                    f"UPDATE llm_tool SET {assignments},"
                    "       write_date = %s, write_uid = %s WHERE id = %s",
                    [*(values[c] for c in owned), now, uid, db_row["id"]],
                )
                updated += 1
            else:
                insert_columns = [
                    "executor",
                    "source",
                    "res_model",
                    "res_method",
                    *(c for c in CODE_OWNED_COLUMNS if c in values),
                ]
                placeholders = ", ".join(["%s"] * (len(insert_columns) + 4))
                cr.execute(
                    f"INSERT INTO llm_tool ({', '.join(insert_columns)},"
                    "   create_date, write_date, create_uid, write_uid)"
                    f" VALUES ({placeholders})",
                    [
                        *(values.get(c) for c in insert_columns),
                        now,
                        now,
                        uid,
                        uid,
                    ],
                )
                created += 1

        # Archive code tools whose method disappeared from the code.
        for db_row in existing.values():
            if db_row["active"]:
                cr.execute(
                    "UPDATE llm_tool SET active = false,"
                    "       write_date = %s, write_uid = %s WHERE id = %s",
                    [now, uid, db_row["id"]],
                )
                deactivated += 1

        if created or updated or deactivated:
            self.invalidate_model()
            _logger.info(
                "Tool sync: %d created, %d updated, %d archived",
                created,
                updated,
                deactivated,
            )

        return {"created": created, "updated": updated, "deactivated": deactivated}

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------

    def action_sync_tools(self):
        """Manual sync button -- wraps :meth:`_sync_tools_to_db` with a notice."""
        Tool = self.env["llm.tool"]
        if not Tool._tool_registry:
            return self._notify(
                _("Nothing to sync"),
                _("Tool registry is empty. Restart the server first."),
                "warning",
            )

        result = Tool._sync_tools_to_db()
        if not any(result.values()):
            return self._notify(
                _("Already in sync"), _("All tools are up to date."), "info"
            )

        parts = []
        if result["created"]:
            parts.append(_("%d created", result["created"]))
        if result["updated"]:
            parts.append(_("%d updated", result["updated"]))
        if result["deactivated"]:
            parts.append(_("%d archived", result["deactivated"]))

        notice = self._notify(
            _("Tools synced"), ", ".join(str(p) for p in parts), "success"
        )
        notice["params"]["next"] = {"type": "ir.actions.client", "tag": "reload"}
        return notice

    def action_duplicate_as_manual(self):
        """Derive a hand-managed exposure from this row.

        The normal way to get a second, narrowed exposure of the same callable:
        the copy keeps the description and schema to trim, and ``source='manual'``
        keeps the scan away from it.
        """
        self.ensure_one()
        copy = self.copy(
            {
                "name": f"{self.name}_custom",
                "source": "manual",
                "is_default": False,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "llm.tool",
            "res_id": copy.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_reset_input_schema(self):
        """Re-derive the schema from the callable, for rows that have one."""
        for record in self:
            source = record._contract_source()
            if source is None:
                # No callable to reflect on: leave the stored schema alone.
                continue
            schema = derive_input_schema(source)
            if schema is not None:
                record.input_schema = json.dumps(schema, indent=2)
        return {"type": "ir.actions.client", "tag": "reload"}

    @api.onchange("res_model", "res_method", "res_id")
    def _onchange_callable(self):
        """Offer a schema draft once a model/method is picked.

        Only fills an empty schema, and only when the target can be reflected
        on -- a convenience for manual rows, not a source of truth.
        """
        if self.executor != "model_method" or self.input_schema:
            return
        if not (self.res_model and self.res_method):
            return
        try:
            method = self._dispatch("resolve_callable", self)
        except (UserError, KeyError):
            return
        schema = derive_input_schema(method)
        if schema is not None:
            self.input_schema = json.dumps(schema, indent=2)

    @staticmethod
    def _notify(title, message, kind):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": kind,
                "sticky": False,
            },
        }
