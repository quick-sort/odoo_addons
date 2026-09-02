from odoo.tests import common

#: A real, code-owned built-in used as a fixture: it has a docstring, full type
#: hints and a schema, so tests can lean on it instead of building a fake.
BUILTIN_MODEL = "llm.tool.builtin.records"
BUILTIN_METHOD = "odoo_record_retriever"


class LLMToolCase(common.TransactionCase):
    """Base case for llm.tool tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LLMTool = cls.env["llm.tool"]

    def _manual_tool(self, name="test_tool", **kwargs):
        """A hand-managed exposure. Needs description and schema to validate."""
        values = {
            "name": name,
            "source": "manual",
            "executor": "model_method",
            "res_model": BUILTIN_MODEL,
            "res_method": BUILTIN_METHOD,
            "description": "Test tool description",
            "input_schema": '{"type": "object", "properties": '
            '{"model": {"type": "string"}}, "required": ["model"]}',
        }
        values.update(kwargs)
        return self.LLMTool.create(values)

    def _builtin(self, method=BUILTIN_METHOD):
        """The code-owned row the startup scan registered for ``method``."""
        return self.LLMTool.search(
            [("res_method", "=", method), ("source", "=", "code")], limit=1
        )
