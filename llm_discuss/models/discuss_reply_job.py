import logging

from odoo import api, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

BATCH_SIZE = 20


class DiscussReplyJob(models.Model):
    """Consumer of discuss.reply.job for the in-process LLM responder."""

    _inherit = "discuss.reply.job"

    @api.model
    def _discuss_cron_process_pending(self):
        """Process pending llm-agent reply jobs (run by ir.cron).

        Claims jobs one at a time, committing the claim before generating so a
        concurrent worker never claims the same job.
        """
        for _index in range(BATCH_SIZE):
            job = self._claim_pending(agent_types=["llm"])
            self.env.cr.commit()
            if not job:
                break
            try:
                job._discuss_process_one()
            except Exception:  # noqa: BLE001 - isolate failures per job
                _logger.exception(
                    "llm_discuss: failed to process reply job %s", job.id
                )
                job._complete_error("Processing failed; see server log.")
            self.env.cr.commit()

    def _discuss_process_one(self):
        """Generate one reply under the source identity and finalize the job."""
        self.ensure_one()
        execution_user, company = self._execution_user_and_company()
        query = (
            html2plaintext(self.message_id.body or "")
            if self.message_id.body
            else ""
        )
        result = self.agent_id._discuss_execute(
            execution_user=execution_user,
            company=company,
            query=query,
        )
        if result.get("error"):
            self._complete_error(result["error"])
        elif not self._complete(result):
            self._complete_error("The agent returned an empty response.")
