import json
import logging
import re
import time
from collections.abc import Iterable

import yaml

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.modules.registry import Registry

from ..utils import render_template

_logger = logging.getLogger(__name__)


class LLMAssistant(models.Model):
    _name = "llm.assistant"
    _description = "LLM Assistant"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(
        string="Name",
        required=True,
        tracking=True,
    )
    active = fields.Boolean(default=True, tracking=True)

    # Assistant configuration
    provider_id = fields.Many2one(
        "llm.provider",
        string="Provider",
        ondelete="restrict",
        tracking=True,
    )
    model_id = fields.Many2one(
        "llm.model",
        string="Model",
        domain="[('provider_id', '=', provider_id)]",
        ondelete="restrict",
        tracking=True,
        required=False,
    )
    is_public = fields.Boolean(
        string="Public",
        default=False,
        help="If checked, this assistant will be available to all users",
    )

    allowed_group_ids = fields.Many2many(
        "res.groups",
        "llm_assistant_group_rel",
        "assistant_id",
        "group_id",
        string="Allowed Groups",
        help="Groups that can access this assistant. If empty and not public, only internal users can access it.",
    )

    code = fields.Char(
        string="Code",
        help="Unique code identifier for the assistant (e.g., roleplay, avatar_generation)",
        index=True,
    )

    res_model = fields.Char(
        string="Related Model",
        help="Model that this assistant is associated with (e.g., fleek.character)",
    )

    is_default = fields.Boolean(
        string="Is Default",
        default=False,
        help="If enabled, this assistant will be used as the default for its model/category",
    )

    # ------------------------------------------------------------------
    # Prompt template
    #
    # Flattened out of a former ``llm.prompt`` model. That model existed to make
    # templates reusable across assistants, but nothing reused them: the three
    # shipped prompts mapped 1:1 to the three shipped assistants, only one
    # template ever declared variables, and its MCP-prompt export was never
    # wired up. The template now belongs to the assistant that uses it.
    #
    # Jinja2 rendering and ``default_values`` are kept: they are what makes a
    # prompt adapt per conversation (see ``llm.thread.get_context``).
    # ------------------------------------------------------------------
    template = fields.Text(
        string="Prompt Template",
        required=True,
        tracking=True,
        help="Jinja2 template producing this assistant's prompt. Variables "
        "written as {{ name }} are filled from Default Values, merged with the "
        "thread context.",
    )

    template_format = fields.Selection(
        [
            ("text", "Text"),
            ("yaml", "YAML"),
            ("json", "JSON"),
        ],
        string="Template Format",
        default="text",
        required=True,
        tracking=True,
        help="How the rendered template is parsed. 'Text' yields a single "
        "system message; 'YAML' and 'JSON' can yield a sequence of messages "
        "with explicit roles (for few-shot examples).",
    )

    category_id = fields.Many2one(
        "llm.assistant.category",
        string="Category",
        index=True,
        help="Category for organizing assistants",
    )

    tag_ids = fields.Many2many(
        "llm.assistant.tag",
        "llm_assistant_tag_rel",
        "assistant_id",
        "tag_id",
        string="Tags",
        help="Classify and analyze your assistants",
    )

    # Default values for prompt variables as JSON
    default_values = fields.Text(
        string="Default Values",
        help="JSON object with default values for prompt variables. Can include template expressions that will be evaluated.",
        default="{}",
        tracking=True,
    )

    # Whether default values contain expressions to be evaluated
    has_dynamic_defaults = fields.Boolean(
        string="Has Dynamic Defaults",
        default=False,
        help="Enable if your default values contain template expressions that should be evaluated",
        tracking=True,
    )

    # Tools configuration
    tool_ids = fields.Many2many(
        "llm.tool",
        string="Preferred Tools",
        help="Tools that this assistant can use",
        tracking=True,
    )

    tool_calls_max = fields.Integer(
        string="Max Tool Calls",
        default=5,
        help="Maximum number of consecutive tool calls allowed before breaking the loop to prevent infinite tool calling",
        tracking=True,
    )

    # Stats
    thread_count = fields.Integer(
        string="Thread Count",
        compute="_compute_thread_count",
        help="Number of threads using this assistant",
    )
    thread_ids = fields.One2many(
        "llm.thread",
        "assistant_id",
        string="Threads",
        help="Threads using this assistant",
    )

    system_prompt_preview = fields.Text(
        string="System Prompt Preview",
        compute="_compute_system_prompt_preview",
        help="Preview of the rendered prompt, using the evaluated default values",
    )

    undefined_variables = fields.Char(
        compute="_compute_undefined_variables",
        string="Missing Default Values",
        help="Template variables with no entry in Default Values",
    )

    _unique_code = models.Constraint(
        'UNIQUE(code)',
        'Assistant code must be unique.',
    )

    @api.depends("template", "template_format", "default_values")
    def _compute_system_prompt_preview(self):
        """Render the template with the evaluated defaults, for the form view."""
        for assistant in self:
            try:
                messages = assistant.get_messages(
                    assistant.get_evaluated_default_values({})
                )
            except Exception as error:  # noqa: BLE001 - a preview must not raise
                _logger.info(
                    "Could not render prompt preview for assistant %s: %s",
                    assistant.name,
                    error,
                )
                assistant.system_prompt_preview = f"Error: {error}"
                continue

            if not messages:
                assistant.system_prompt_preview = "No messages generated"
                continue

            # Prefer the system message; fall back to the first one.
            message = next(
                (msg for msg in messages if msg.get("role") == "system"),
                messages[0],
            )
            content = message.get("content")
            if isinstance(content, list) and content:
                assistant.system_prompt_preview = content[0].get("text", "")
            elif isinstance(content, str):
                assistant.system_prompt_preview = content
            else:
                assistant.system_prompt_preview = str(content)

    @api.depends("thread_ids")
    def _compute_thread_count(self):
        """Compute the number of threads using this assistant"""
        for assistant in self:
            assistant.thread_count = len(assistant.thread_ids)

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    def get_messages(self, arguments=None):
        """Render the template and return it as a list of message dicts.

        Args:
            arguments: values for the template variables. Usually the thread
                context merged with the evaluated default values -- see
                ``llm.thread.get_context``.

        Returns:
            list of ``{"role": str, "content": [{"type": "text", "text": str}]}``
        """
        self.ensure_one()

        rendered = render_template(template=self.template, context=arguments or {})
        self._validate_rendered_format(rendered)

        try:
            if self.template_format == "text":
                return self._parse_text_messages(rendered)
            if self.template_format == "yaml":
                return list(self._parse_dict_messages(yaml.safe_load_all(rendered)))
            if self.template_format == "json":
                return list(self._parse_dict_messages(json.loads(rendered)))
        except (json.JSONDecodeError, yaml.YAMLError) as error:
            _logger.error(
                "Error parsing %s prompt for assistant %s: %s",
                self.template_format,
                self.name,
                error,
            )
            raise ValidationError(
                _(
                    "Could not parse the rendered %(format)s prompt. The template "
                    "may have syntax errors or produce invalid output.\n\n"
                    "Tips:\n"
                    "• For YAML: check indentation and special characters\n"
                    "• For JSON: ensure quotes and brackets are balanced\n\n"
                    "Details: %(error)s",
                    format=self.template_format.upper(),
                    error=error,
                )
            ) from error

        raise ValidationError(
            _(
                "The template format '%s' is not supported. Please use Text, "
                "YAML, or JSON.",
                self.template_format,
            )
        )

    def _validate_rendered_format(self, rendered_content):
        """Fail on a template that does not produce its declared format.

        Checked at render time so a broken template surfaces in the form
        preview rather than mid-conversation.
        """
        if not rendered_content:
            return

        try:
            if self.template_format == "json":
                json.loads(rendered_content)
            elif self.template_format == "yaml":
                # A YAML prompt may hold several documents, one per message.
                list(yaml.safe_load_all(rendered_content))
            # 'text' needs no validation.
        except (json.JSONDecodeError, yaml.YAMLError) as error:
            raise ValidationError(
                _(
                    "The rendered template is not valid %(format)s.\n\n"
                    "Check the template syntax and make sure it still produces "
                    "valid %(format)s after variable substitution.\n\n"
                    "Error: %(error)s",
                    format=self.template_format.upper(),
                    error=error,
                )
            ) from error

    def _parse_text_messages(self, content):
        """A plain-text template is one system message."""
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": content}],
            }
        ]

    def _parse_dict_messages(self, data):
        """Yield messages from a dict, list, or iterator of dicts, recursively.

        A YAML or JSON template can describe several messages, each with its own
        role -- which is what makes those formats worth having over plain text.
        """
        items = (
            data
            if isinstance(data, Iterable) and not isinstance(data, (str, dict))
            else [data]
        )

        for item in items:
            if isinstance(item, dict):
                if "content" in item:
                    content = item["content"]
                    if isinstance(content, list):
                        content = "\n".join(str(line) for line in content)

                    yield {
                        "role": item.get("type", "user"),
                        "content": [{"type": "text", "text": str(content)}],
                    }
                else:
                    # No 'content' key: descend into the values.
                    for value in item.values():
                        if isinstance(value, (dict, list)) or (
                            isinstance(value, Iterable) and not isinstance(value, str)
                        ):
                            yield from self._parse_dict_messages(value)

            elif isinstance(item, (list, tuple)) or (
                isinstance(item, Iterable) and not isinstance(item, str)
            ):
                yield from self._parse_dict_messages(item)

    def action_view_threads(self):
        """Open the threads using this assistant"""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "llm.llm_thread_action"
        )
        action["domain"] = [("assistant_id", "=", self.id)]
        action["context"] = {"default_assistant_id": self.id}
        return action

    TEMPLATE_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

    def _template_variables(self):
        """Return the ``{{ name }}`` variables used by this template.

        Replaces the former ``llm.prompt.arguments_json`` schema: with one
        template per assistant there is no point declaring the variables
        separately from the template that uses them, and a hand-maintained
        schema could drift from it.

        Only plain variables are matched. Jinja2 expressions ({% if %}, filters,
        attribute access) still render -- they are simply not offered as
        placeholders by :meth:`action_reset_defaults`.
        """
        self.ensure_one()
        return sorted(set(self.TEMPLATE_VARIABLE_RE.findall(self.template or "")))

    @api.depends("template", "default_values")
    def _compute_undefined_variables(self):
        for assistant in self:
            try:
                defined = set(json.loads(assistant.default_values or "{}"))
            except json.JSONDecodeError:
                defined = set()

            missing = [
                name
                for name in assistant._template_variables()
                if name not in defined
            ]
            assistant.undefined_variables = ", ".join(missing) or False

    def action_reset_defaults(self):
        """Fill Default Values with an entry per template variable.

        Existing values are kept; only missing variables are added, as an empty
        string placeholder. Variables that disappeared from the template are
        dropped.
        """
        self.ensure_one()

        variables = self._template_variables()
        if not variables:
            return self._notify(
                "No variables found",
                "This template uses no {{ variable }} placeholders.",
                "info",
            )

        try:
            current = json.loads(self.default_values or "{}")
        except json.JSONDecodeError:
            current = {}

        values = {name: current.get(name, "") for name in variables}
        added = sum(1 for name in variables if name not in current)
        removed = len(current) - (len(values) - added)

        self.default_values = json.dumps(values, indent=2)

        parts = []
        if added:
            parts.append(f"{added} added")
        if removed:
            parts.append(f"{removed} removed")
        return self._notify(
            "Default values synced",
            ", ".join(parts) if parts else "Already in sync.",
            "success",
        )

    def _notify(self, title, message, kind):
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

    def get_evaluated_default_values(self, context):
        """
        Evaluate default values using the provided context.
        This is used by llm.thread to get assistant's default values with thread context.

        Args:
            context (dict): Context for template rendering

        Returns:
            dict: Evaluated default values
        """
        self.ensure_one()

        # Parse the default values JSON
        try:
            default_values = json.loads(self.default_values or "{}")
        except json.JSONDecodeError:
            _logger.warning(
                "Invalid JSON in default_values for assistant %s", self.name
            )
            return {}

        if not default_values:
            return {}

        # If we don't have dynamic defaults, return as-is
        if not self.has_dynamic_defaults:
            return default_values

        # Render each default value as a template
        evaluated_values = {}
        for key, value in default_values.items():
            if isinstance(value, str) and "{{" in value and "}}" in value:
                try:
                    evaluated_values[key] = render_template(
                        template=value, context=context
                    )
                except Exception as e:
                    _logger.warning(
                        "Error evaluating default value '%s' for assistant %s: %s",
                        key,
                        self.name,
                        str(e),
                    )
                    evaluated_values[key] = value  # Keep original on error
            else:
                evaluated_values[key] = value

        return evaluated_values

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to ensure default_values is valid JSON"""
        for vals in vals_list:
            if "default_values" in vals and vals["default_values"]:
                try:
                    json.loads(vals["default_values"])
                except json.JSONDecodeError:
                    vals["default_values"] = "{}"
        return super().create(vals_list)

    def _get_json_fields(self):
        """Return fields that should be serialized as JSON in the API"""
        return ["default_values"]

    @api.model
    def get_assistant_by_id(self, assistant_id):
        """Get an assistant record by its ID

        Args:
            assistant_id (int): ID of the assistant

        Returns:
            tuple: (assistant, error_response)
                  If successful, error_response will be None
                  If error, assistant will be None
        """
        if not assistant_id:
            return None, None

        assistant = self.browse(int(assistant_id))
        if not assistant.exists():
            return None, {"success": False, "error": "Assistant not found"}
        return assistant, None

    def get_assistant_values(self, thread, include_template=True):
        """Get thread-specific evaluated default values for this assistant.

        Served by ``/llm/thread/set_assistant`` and
        ``/llm/thread/get_assistant_values``.

        Args:
            thread (llm.thread): Thread record
            include_template (bool): Whether to include the prompt template

        Returns:
            dict: Result with evaluated default values and template info
        """
        self.ensure_one()

        # Get thread context and use it to evaluate default values
        thread_context = thread.get_context() if hasattr(thread, "get_context") else {}
        evaluated_values = self.get_evaluated_default_values(thread_context)

        result = {
            "success": True,
            "thread_id": thread.id,
            "assistant_id": self.id,
            "default_values": self.default_values,
            "evaluated_default_values": json.dumps(evaluated_values, indent=2)
            if evaluated_values
            else "{}",
        }

        # Used to be the related llm.prompt record; the template lives on the
        # assistant now, so report it directly.
        if include_template:
            result["template"] = {
                "format": self.template_format,
                "variables": self._template_variables(),
            }

        return result

    def _get_allowed_assistants_for_user(self, user=None):
        """Get assistants that the current user can access"""
        if not user:
            user = self.env.user

        # Admin can access all assistants
        if user.has_group("base.group_system"):
            return self.search([])

        # Assistants allowed for user's groups
        if user.group_ids:
            domain = [
                "|",
                ("is_public", "=", True),
                ("allowed_group_ids", "in", user.group_ids.ids),
            ]
        else:
            # If user has no groups, only public assistants
            domain = [("is_public", "=", True)]

        return self.search(domain)

    @api.model
    def get_assistant_by_code(self, code):
        """Get assistant by code"""
        return self.search([("code", "=", code)], limit=1)

    def _run_in_thread(self, query, thread_vals=None):
        """Internal: create a sub-thread, run generate, return result dict.

        Runs on whatever env ``self`` is bound to — caller decides the
        transaction policy. Used by ``invoke`` with both ``new_cursor=True``
        (after switching to a new cursor) and ``new_cursor=False`` (current
        cursor / queue_job entries).

        Returns a dict with ``query``, ``result``, ``error``, ``thread_id``.
        """
        self.ensure_one()
        code = self.code or self.name
        depth = self.env.context.get("llm_invoke_assistant_depth", 0)
        new_cursor = self.env.context.get("llm_invoke_as_subthread", False)
        vals = {
            "provider_id": self.provider_id.id,
            "model_id": self.model_id.id,
        }
        if thread_vals:
            vals.update(thread_vals)

        thread = self.env["llm.thread"].create(vals)
        thread.set_assistant(self.id)

        _logger.info(
            "[assistant.run] START code=%r thread_id=%d depth=%d "
            "isolated_cursor=%s query_len=%d",
            code, thread.id, depth, new_cursor, len(query or ""),
        )

        error = None
        start = time.monotonic()
        try:
            for _event in thread.generate(user_message_body=query):
                pass
        except Exception as e:
            _logger.exception(
                "Error running assistant '%s' (thread %s)", code, thread.id,
            )
            error = str(e)
        elapsed = time.monotonic() - start

        _logger.info(
            "[assistant.run] END   code=%r thread_id=%d elapsed=%.1fs error=%s",
            code, thread.id, elapsed, error,
        )

        # Latest message on the sub-thread. flush_all first so any pending
        # body / body_json writes from generate are visible to search.
        self.env.flush_all()
        message = self.env["mail.message"].search([
            ("model", "=", "llm.thread"),
            ("res_id", "=", thread.id),
        ], order="id desc", limit=1)

        _logger.info(
            "[assistant.run] result lookup code=%r thread_id=%d found_message_id=%s "
            "llm_role=%s body_len=%s",
            code, thread.id,
            message.id if message else None,
            message.llm_role if message else None,
            len(message.body or "") if message else None,
        )

        result = None
        result_html = None
        if message:
            # `result` is the raw markdown stashed in body_json by the
            # streaming/non-streaming handlers — this is the form most
            # programmatic callers (and downstream assistants in chained
            # invocations) want, since HTML re-rendering would otherwise
            # need to be stripped or re-parsed.
            #
            # `result_html` exposes the already-rendered HTML (mail.message
            # `body`) for callers that bind the output to a ``fields.Html``
            # column — they would otherwise have to re-run a markdown->HTML
            # converter themselves.
            raw = (
                message.body_json.get("content")
                if isinstance(message.body_json, dict)
                else None
            )
            if raw:
                result = raw
            elif message.body:
                result = str(message.body)
            if message.body:
                result_html = str(message.body)
        elif not error:
            result = "No result."

        return {
            "query": query,
            "result": result,
            "result_html": result_html,
            "error": error,
            "thread_id": thread.id,
        }

    def invoke(self, query, parent_context=None, thread_vals=None, new_cursor=True):
        """Run this assistant on a sub-thread.

        The assistant body in ``llm.thread.generate_messages`` never commits —
        it only flushes — so it composes with any caller's transaction policy.
        ``invoke`` exposes two transaction modes via ``new_cursor``:

        - ``new_cursor=True`` (default) — open a fresh cursor for the sub-run.
          Use this when called from inside another tool / assistant. Reasons:

          * The outer caller is inside ``mail.message._execute_tool``'s
            savepoint; any commit on the shared cursor would destroy that
            savepoint stack.
          * The inner conversation needs its own persistence lifecycle so its
            side effects survive independently of the outer turn (the user
            has already paid the LLM / tool cost).

        - ``new_cursor=False`` — run on the caller's cursor. Use this from
          queue_job entry points: the job owns the transaction boundary, and
          its all-or-nothing commit semantics are preserved (clean retry on
          failure, no orphan data from independent sub-commits).

        Args:
            query: Natural-language instruction sent as the first user message.
            parent_context: Extra context keys merged into the sub-env (only
                applied when ``new_cursor=True``; with ``new_cursor=False``
                the caller's env is used as-is).
            thread_vals: Extra fields merged into the sub-thread create dict
                (e.g. ``{"model": "...", "res_id": ...}`` to link the thread
                to a parent record).
            new_cursor: True to open an isolated cursor, False to share the
                caller's cursor. Default True.

        Returns:
            See ``_run_in_thread`` for the dict shape.
        """
        self.ensure_one()

        if not new_cursor:
            return self._run_in_thread(query, thread_vals=thread_vals)

        context = {
            **self.env.context,
            **(parent_context or {}),
            "llm_invoke_as_subthread": True,
        }
        with Registry(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, context)
            return self.with_env(env)._run_in_thread(query, thread_vals=thread_vals)

    @api.model
    def invoke_assistant(self, assistant_code, query, parent_context=None,
                         thread_vals=None, new_cursor=True):
        """Look up an assistant by code and run it.

        Convenience wrapper: ``get_assistant_by_code`` + ``invoke``. See
        ``invoke`` for transaction semantics and the ``new_cursor`` flag.
        """
        assistant = self.get_assistant_by_code(assistant_code)
        if not assistant:
            return {
                "query": query,
                "result": None,
                "error": f"Assistant with code '{assistant_code}' not found.",
                "thread_id": None,
            }
        return assistant.invoke(
            query,
            parent_context=parent_context,
            thread_vals=thread_vals,
            new_cursor=new_cursor,
        )
