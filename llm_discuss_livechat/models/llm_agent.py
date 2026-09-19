from odoo import fields, models


class LlmAssistant(models.Model):
    _inherit = "llm.agent"

    livechat_channel_ids = fields.Many2many(
        "im_livechat.channel",
        "llm_agent_livechat_channel_rel",
        "agent_id",
        "livechat_channel_id",
        string="Live Chat Channels",
        help="Live Chat channels this agent is registered as an "
        "operator on. Requires a Bot User (see the Discuss tab).",
    )

    def write(self, vals):
        old_bot_users = {
            agent.id: agent.discuss_user_id
            for agent in self
        }
        res = super().write(vals)
        if "livechat_channel_ids" in vals or "discuss_user_id" in vals:
            self._sync_livechat_operator(old_bot_users=old_bot_users)
        return res

    def unlink(self):
        self._remove_livechat_operators(self.mapped("discuss_user_id"))
        return super().unlink()

    @property
    def _livechat_bot_user(self):
        self.ensure_one()
        return self.discuss_user_id

    def _remove_livechat_operators(self, bot_users):
        LivechatChannel = self.env["im_livechat.channel"].sudo()
        for bot_user in bot_users:
            channels = LivechatChannel.search([("user_ids", "in", bot_user.id)])
            channels.write({"user_ids": [fields.Command.unlink(bot_user.id)]})

    def _sync_livechat_operator(self, old_bot_users=None):
        """Synchronize selected channels and remove replaced bot users."""
        old_bot_users = old_bot_users or {}
        LivechatChannel = self.env["im_livechat.channel"].sudo()
        for agent in self:
            bot_user = agent.discuss_user_id
            old_bot = old_bot_users.get(agent.id)
            if old_bot and old_bot != bot_user:
                old_channels = LivechatChannel.search([("user_ids", "in", old_bot.id)])
                old_channels.write({"user_ids": [fields.Command.unlink(old_bot.id)]})

            if not bot_user:
                continue
            selected = agent.livechat_channel_ids
            currently_operator_on = LivechatChannel.search(
                [("user_ids", "in", bot_user.id)]
            )
            to_add = selected - currently_operator_on
            to_remove = currently_operator_on - selected
            if to_add:
                to_add.write({"user_ids": [fields.Command.link(bot_user.id)]})
            if to_remove:
                to_remove.write({"user_ids": [fields.Command.unlink(bot_user.id)]})

    def action_create_discuss_user(self):
        res = super().action_create_discuss_user()
        self._sync_livechat_operator()
        return res
