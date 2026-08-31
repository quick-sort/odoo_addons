"""Built-in tool for calling an arbitrary method on a model or recordset."""

import json
import logging
from typing import Any, Union

from odoo import models
from odoo.exceptions import UserError

from ..decorators import llm_tool

_logger = logging.getLogger(__name__)


class LLMToolBuiltinMethod(models.AbstractModel):
    _name = "llm.tool.builtin.method"
    _description = "Built-in Odoo method execution tool"

    def _parse_json_value(self, value: Union[str, int, bool, float, None]) -> Any:
        """
        Automatically parse JSON-encoded strings to Python objects.
        Non-string values or non-JSON strings are returned as-is.

        This allows LLMs to pass complex structures (lists, dicts) as JSON strings
        while keeping the schema OpenAI-compatible (primitives only).
        """
        if not isinstance(value, str):
            return value

        # Try to parse as JSON
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Not valid JSON, return as plain string
            return value

    def _serialize_result(self, result: Any) -> Any:
        if isinstance(result, models.BaseModel):
            return {"recordset_model": result._name, "record_ids": result.ids}
        try:
            json.dumps(result)
            return result
        except (TypeError, OverflowError):
            return repr(result)

    @llm_tool
    def odoo_model_method_executor(
        self,
        model: str,
        method: str,
        record_ids: Union[list[int], None] = None,
        args: Union[list[Union[str, int, bool, float, None]], None] = None,
        kwargs: Union[dict[str, Union[str, int, bool, float, None]], None] = None,
        allow_private: bool = False,
    ) -> dict[str, Any]:
        """**VERY HIGH RISK TOOL:** Executes a specified method on an Odoo model or specific records. Provide the model's technical name, the method name, and optionally a list of record IDs, positional arguments ('args'), and keyword arguments ('kwargs'). If record_ids is null/empty, the method is called on the model itself (e.g., for `search`, `create`, `@api.model`, `@staticmethod`).

        **WARNING:** This tool can modify or delete data, trigger complex actions, or cause system errors if used improperly. It bypasses standard UI workflows.

        **IMPORTANT:** The LLM using this tool MUST explicitly ask the user for confirmation before EVERY execution, clearly stating the model, method, records (if any), and arguments being used.

        Private methods (starting with '_') are disallowed by default unless 'allow_private' is explicitly set to true (use with extreme caution).

        Returns a JSON representation of the method's result or an error message.

        Parameters:
            model: The technical Odoo model name (e.g., res.partner).
            method: The name of the method to execute on the model or records.
            record_ids: Optional list of database IDs. If provided, the method is called on this recordset; otherwise, it's called on the model.
            args: Optional list of positional arguments. Simple values (str, int, bool, float, None) are passed directly. For complex structures (lists, dicts), pass them as JSON-encoded strings - they will be automatically parsed. Example: '[["name", "=", "John"]]' for a domain.
            kwargs: Optional dictionary of keyword arguments. Simple values are passed directly. For complex values (lists, dicts), pass them as JSON-encoded strings - they will be automatically parsed. Example: {"values": '{"name": "John", "age": 30}'}.
            allow_private: Set to true to allow calling private methods (those starting with '_'). Defaults to False.
        """
        # Parse args: convert JSON strings to Python objects
        actual_args = [self._parse_json_value(arg) for arg in args] if args else []

        # Parse kwargs: convert JSON strings to Python objects
        actual_kwargs = (
            {k: self._parse_json_value(v) for k, v in kwargs.items()} if kwargs else {}
        )

        if not model or not method:
            return {"error": "Model name and method name are required"}

        if model not in self.env:
            raise UserError(f"Model '{model}' does not exist in the environment.")

        if method.startswith("_") and not allow_private:
            raise UserError(
                f"Execution of private method '{method}' is not allowed by default. "
                "Set 'allow_private' to true to override."
            )

        model_obj = self.env[model]
        target = model_obj

        if record_ids:
            target = model_obj.browse(record_ids)
            if not target.exists():
                existing_ids = model_obj.search([("id", "in", record_ids)]).ids
                if not existing_ids:
                    return {
                        "error": f"None of the provided Record IDs {record_ids} exist for model {model}."
                    }

        if not hasattr(target, method):
            target_type = "records" if record_ids else "model"
            raise AttributeError(
                f"Method '{method}' not found on the target {target_type} ('{target}')."
            )

        method_func = getattr(target, method)

        result = method_func(*actual_args, **actual_kwargs)

        serialized_result = self._serialize_result(result)
        return {
            "result": serialized_result,
            "message": f"Method '{method}' executed successfully.",
        }
