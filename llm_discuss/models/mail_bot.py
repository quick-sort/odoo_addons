from odoo import models


class MailBot(models.AbstractModel):
    _inherit = "mail.bot"

    def _apply_logic(self, channel, values, command=None):
        """Keep onboarding and commands, but yield completed chats to the LLM."""
        if (
            command is None
            and channel._llm_discuss_odoobot_takeover_agent(values)
        ):
            return None
        return super()._apply_logic(channel, values, command=command)
