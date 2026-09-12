from odoo import models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _llm_discuss_user_can_use_assistant(self, assistant, user):
        """Require the assistant to still be this Live Chat's operator."""
        self.ensure_one()
        if self.channel_type == "livechat":
            bot_partner = assistant.discuss_user_id.partner_id
            return bool(
                bot_partner
                and self.livechat_operator_id == bot_partner
            )
        return super()._llm_discuss_user_can_use_assistant(assistant, user)

    def _llm_discuss_should_trigger(self, assistant, message, msg_vals):
        """Trigger on visitor comments when this assistant is the operator."""
        self.ensure_one()
        bot_partner = assistant.discuss_user_id.partner_id
        if (
            bot_partner
            and self.channel_type == "livechat"
            and self.livechat_operator_id == bot_partner
            and message.author_id != bot_partner
            and msg_vals.get("message_type", "notification") == "comment"
        ):
            return True
        return super()._llm_discuss_should_trigger(assistant, message, msg_vals)
