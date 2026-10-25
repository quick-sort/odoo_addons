from odoo import fields, models


class DiscussAgent(models.Model):
    """Register the in-process LLM responder on the discuss_agent interface."""

    _inherit = "discuss.agent"

    agent_type = fields.Selection(
        selection_add=[("llm", "LLM Agent")],
        ondelete={"llm": "cascade"},
    )

    def _discuss_after_enqueue(self):
        """Wake the in-process worker cron immediately after a job is queued."""
        cron = self.env.ref(
            "llm_discuss.ir_cron_process_discuss_reply_job",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
