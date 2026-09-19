"""Tests for the prompt template on ``llm.agent``.

The template used to live on a separate ``llm.prompt`` model. Flattening it onto
the agent removed the ``arguments_json`` schema. The template is also no
longer a Jinja2 template with variable substitution: it is used verbatim as
the agent's system prompt.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.llm.tests.common import selection_value


@tagged("post_install", "-at_install")
class TestAgentTemplate(TransactionCase):
    def _agent(self, template, **kwargs):
        return self.env["llm.agent"].create(
            {
                "name": kwargs.pop("name", "Test Agent"),
                "template": template,
                **kwargs,
            }
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def test_text_template_is_one_system_message(self):
        agent = self._agent("You are a librarian.")

        messages = agent.get_messages()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(
            messages[0]["content"][0]["text"], "You are a librarian."
        )

    def test_yaml_template_can_emit_several_roles(self):
        """The reason YAML/JSON formats exist: few-shot message sequences."""
        agent = self._agent(
            "- type: system\n"
            "  content: You are terse.\n"
            "- type: user\n"
            "  content: Ping\n"
            "- type: assistant\n"
            "  content: Pong\n",
            template_format="yaml",
        )

        messages = agent.get_messages()

        self.assertEqual(
            [m["role"] for m in messages], ["system", "user", "assistant"]
        )
        self.assertEqual(messages[2]["content"][0]["text"], "Pong")

    def test_json_template(self):
        agent = self._agent(
            '[{"type": "system", "content": "Be brief."}]',
            template_format="json",
        )

        messages = agent.get_messages()

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"][0]["text"], "Be brief.")

    def test_broken_yaml_is_reported(self):
        agent = self._agent(
            "- type: system\n  content: [unclosed\n", template_format="yaml"
        )

        with self.assertRaises(ValidationError):
            agent.get_messages()

    def test_broken_json_is_reported(self):
        agent = self._agent(
            '{"type": "system", "content": invalid}',
            template_format="json",
        )

        with self.assertRaises(ValidationError):
            agent.get_messages()

    # ------------------------------------------------------------------
    # Preview and thread wiring
    # ------------------------------------------------------------------

    def test_preview_shows_the_template_verbatim(self):
        agent = self._agent("You are a guide.")

        self.assertEqual(agent.system_prompt_preview, "You are a guide.")

    def test_preview_reports_an_error_instead_of_raising(self):
        agent = self._agent(
            "not json", template_format="json"
        )

        self.assertTrue(agent.system_prompt_preview.startswith("Error:"))

    def _thread_for(self, agent):
        """Build a thread, which needs a provider and a model of its own.

        The fake service comes from ``llm.tests.common``: ``llm.provider.service``
        is a static selection extended with ``selection_add``, so a provider
        cannot be created for a service no installed addon offers.
        """
        with selection_value(self.env["llm.provider"], "service", "agent_probe"):
            provider = self.env["llm.provider"].create(
                {"name": "probe provider", "service": "agent_probe"}
            )
        model = self.env["llm.model"].create(
            {
                "name": "probe-model",
                "provider_id": provider.id,
                "model_use": "chat",
            }
        )
        return self.env["llm.thread"].create(
            {
                "name": "probe thread",
                "provider_id": provider.id,
                "model_id": model.id,
                "agent_id": agent.id if agent else False,
            }
        )

    def test_thread_prepends_the_agent_template(self):
        agent = self._agent("You are a guide.")

        messages = self._thread_for(agent).get_prepend_messages()

        self.assertEqual(len(messages), 1)
        self.assertIn("You are a guide.", messages[0]["content"][0]["text"])

    def test_thread_without_agent_prepends_nothing(self):
        self.assertEqual(self._thread_for(None).get_prepend_messages(), [])

    # ------------------------------------------------------------------
    # The flattening itself
    # ------------------------------------------------------------------

    def test_prompt_models_are_gone(self):
        for model in (
            "llm.prompt",
            "llm.prompt.category",
            "llm.prompt.tag",
            "llm.prompt.test",
        ):
            self.assertNotIn(model, self.env)

    def test_thread_has_no_prompt_field(self):
        self.assertNotIn("prompt_id", self.env["llm.thread"]._fields)

    def test_agent_has_no_prompt_field(self):
        self.assertNotIn("prompt_id", self.env["llm.agent"]._fields)

    def test_agent_has_no_default_values_fields(self):
        """Jinja2 rendering and the default-values mechanism were removed:
        the template is used verbatim as the system prompt."""
        for field_name in ("default_values", "has_dynamic_defaults", "undefined_variables"):
            self.assertNotIn(field_name, self.env["llm.agent"]._fields)

    def test_template_is_required(self):
        with self.assertRaises(Exception):
            self.env["llm.agent"].create({"name": "no template"})

    def test_builtin_agents_carry_their_template(self):
        for xmlid in (
            "llm.llm_agent_creator",
            "llm.llm_agent_website_builder",
            "llm.llm_agent_odoo_operator",
        ):
            agent = self.env.ref(xmlid)
            self.assertTrue(
                (agent.template or "").strip(),
                f"{xmlid} lost its template in the flattening",
            )
            self.assertEqual(agent.template_format, "text")

    def test_builtin_templates_kept_their_content(self):
        """Guards the migration out of the deleted llm_prompt_data.xml."""
        creator = self.env.ref("llm.llm_agent_creator")

        self.assertIn("Agent Creator Agent", creator.template)
        self.assertIn("INSPECTION PHASE", creator.template)
