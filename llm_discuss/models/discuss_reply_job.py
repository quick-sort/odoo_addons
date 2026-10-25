from odoo import api, models


class DiscussReplyJob(models.Model):
    """Consumer of discuss.reply.job for the in-process LLM responder."""

    _inherit = "discuss.reply.job"

    @api.model
    def _discuss_cron_process_pending(self):
        """Process pending llm-agent reply jobs (run by ir.cron).

        The full processing loop lives in discuss_agent's ``_process_pending``;
        this only pins the responder kind so the worker never claims another
        bridge's jobs.
        """
        self._process_pending(agent_types=["llm"])
