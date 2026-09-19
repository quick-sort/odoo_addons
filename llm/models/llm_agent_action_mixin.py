import logging

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMAssistantActionMixin(models.AbstractModel):
    """
    Mixin to add AI agent action functionality to any model.
    Provides generic methods to open LLM chat with specific agents.

    Usage:
        class MyModel(models.Model):
            _inherit = ['my.model', 'llm.agent.action.mixin']

            def action_my_ai_button(self):
                return self.action_open_llm_agent('my_agent_code')
    """

    _name = "llm.agent.action.mixin"
    _description = "LLM Assistant Action Mixin"

    def action_open_llm_agent(
        self, agent_code=None, force_new_thread=False, **kwargs
    ):
        """
        Generic method to open AI agent for current record.
        Creates/finds thread, sets agent, and prepares for frontend to open AI chat.

        Args:
            agent_code: Code of the agent to use (e.g., 'invoice_analyzer').
                           If not provided, tries to get from context.
            force_new_thread: If True, always create new thread (ignore existing).
            **kwargs: Reserved for future extensibility.

        Returns:
            dict: Client action to open AI chat in chatter

        Raises:
            UserError: If no provider/model found
        """
        self.ensure_one()

        # Get agent code from parameter or context
        if not agent_code:
            agent_code = self.env.context.get("agent_code")

        if not agent_code:
            raise UserError(
                "No agent code provided. Please specify agent_code parameter or context."
            )

        _logger.info(
            "=== Opening AI agent '%s' for %s ID: %s (force_new=%s) ===",
            agent_code,
            self._name,
            self.id,
            force_new_thread,
        )

        # Find existing thread or create new one
        thread = self._find_or_create_llm_thread(force_new=force_new_thread)

        # Find and set agent
        self._set_agent_on_thread(thread, agent_code)

        _logger.info(
            "=== AI agent ready. Thread ID: %s, Agent: %s ===",
            thread.id,
            thread.agent_id.name if thread.agent_id else "None",
        )

        # Return client action to open AI chat in chatter
        # This is more reliable than bus notifications which can fail on cloud
        # deployments with WebSocket issues
        return {
            "type": "ir.actions.client",
            "tag": "llm_open_chatter",
            "params": {
                "thread_id": thread.id,
                "model": self._name,
                "res_id": self.id,
            },
        }

    def _find_or_create_llm_thread(self, force_new=False):
        """
        Find existing thread for this record or create a new one.

        Args:
            force_new: If True, always create new thread (ignore existing)

        Returns:
            llm.thread: The thread record
        """
        if not force_new:
            _logger.info("Step 1: Looking for existing thread...")
            thread = self.env["llm.thread"].search(
                [("model", "=", self._name), ("res_id", "=", self.id)], limit=1
            )

            if thread:
                _logger.info("Found existing thread ID: %s", thread.id)
                return thread

        _logger.info("Creating new thread...")

        # Find default chat model or fallback to first available
        _logger.info("Looking for default chat model...")
        default_model = self.env["llm.model"].search(
            [
                ("model_use", "in", ["chat", "multimodal"]),
                ("is_default", "=", True),
                ("active", "=", True),
            ],
            limit=1,
        )

        if default_model:
            _logger.info(
                "Found default model: %s (Provider: %s)",
                default_model.name,
                default_model.provider_id.name,
            )
        else:
            _logger.info("No default model found, looking for first available...")

            # Fallback: Get first provider and its first chat model
            _logger.info("Looking for first available provider...")
            provider = self.env["llm.provider"].search([("active", "=", True)], limit=1)
            if not provider:
                _logger.error("No active LLM provider found!")
                raise UserError(
                    "No active LLM provider found. Please configure a provider first."
                )

            _logger.info("Found provider: %s", provider.name)
            _logger.info("Looking for first chat model for this provider...")
            default_model = self.env["llm.model"].search(
                [
                    ("provider_id", "=", provider.id),
                    ("model_use", "in", ["chat", "multimodal"]),
                    ("active", "=", True),
                ],
                limit=1,
            )

        if not default_model:
            _logger.error("No active chat model found!")
            raise UserError(
                "No active chat model found. Please configure a model first."
            )

        _logger.info(
            "Creating new thread with Provider: %s, Model: %s",
            default_model.provider_id.name,
            default_model.name,
        )

        # Create new thread - name will be auto-generated by backend
        thread = self.env["llm.thread"].create(
            {
                "model": self._name,
                "res_id": self.id,
                "provider_id": default_model.provider_id.id,
                "model_id": default_model.id,
            }
        )
        _logger.info("Thread created successfully with ID: %s", thread.id)

        return thread

    def _set_agent_on_thread(self, thread, agent_code):
        """
        Find agent by code and set it on the thread.

        Args:
            thread: llm.thread record
            agent_code: Code of the agent to find
        """
        _logger.info("Step 2: Looking for agent with code '%s'...", agent_code)
        agent = self.env["llm.agent"].search(
            [("code", "=", agent_code)], limit=1
        )

        if agent:
            _logger.info("Found agent: %s (ID: %s)", agent.name, agent.id)
            if not thread.agent_id:
                _logger.info(
                    "Setting agent on thread (with tools, provider, model)..."
                )
                thread.set_agent(agent.id)
                _logger.info(
                    "Agent set successfully. Tools: %s",
                    thread.tool_ids.mapped("name"),
                )
            else:
                _logger.info(
                    "Thread already has agent: %s", thread.agent_id.name
                )
        else:
            _logger.warning("Agent with code '%s' not found!", agent_code)
