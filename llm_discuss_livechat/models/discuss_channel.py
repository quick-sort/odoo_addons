from odoo import models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _llm_discuss_user_can_use_agent(self, agent, user):
        """Require the agent to still be this Live Chat's operator."""
        self.ensure_one()
        if self.channel_type == "livechat":
            bot_partner = agent.discuss_user_id.partner_id
            return bool(
                bot_partner
                and self.livechat_operator_id == bot_partner
            )
        return super()._llm_discuss_user_can_use_agent(agent, user)

    def _llm_discuss_should_trigger(self, agent, message, msg_vals):
        """Trigger on visitor comments when this agent is the operator."""
        self.ensure_one()
        bot_partner = agent.discuss_user_id.partner_id
        if (
            bot_partner
            and self.channel_type == "livechat"
            and self.livechat_operator_id == bot_partner
            and message.author_id != bot_partner
            and msg_vals.get("message_type", "notification") == "comment"
        ):
            return True
        return super()._llm_discuss_should_trigger(agent, message, msg_vals)
