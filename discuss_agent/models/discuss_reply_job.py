import logging
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DiscussReplyJob(models.Model):
    """Pending reply for a Discuss message, decoupled from who consumes it.

    ``discuss.reply.job`` is the interface-level carrier of "one message is
    owed a reply by one agent". It captures the *persona* (``reply_partner_id``)
    and the *execution identity* (``source_user_id``) at enqueue time, so the
    two never have to be the same.

    The consumer is deliberately not implemented here:

    * a synchronous consumer (in-process LLM) claims the job and calls
      ``_complete`` with the generated reply;
    * an asynchronous consumer (external JSON-RPC agent such as agent-box)
      polls pending jobs, generates a reply out-of-band, then calls
      ``_complete`` back.

    Both share the same state machine and completion entry point.
    """

    _name = "discuss.reply.job"
    _description = "Discuss Reply Job"
    _order = "id"

    agent_id = fields.Many2one(
        "discuss.agent", required=True, ondelete="cascade", index=True
    )
    channel_id = fields.Many2one(
        "discuss.channel", required=True, ondelete="cascade", index=True
    )
    message_id = fields.Many2one(
        "mail.message", required=True, ondelete="cascade", index=True
    )
    reply_partner_id = fields.Many2one(
        "res.partner", ondelete="set null", index=True,
        help="Partner shown as the author of the reply bubble. Independent "
        "from the user whose permissions execute the agent.",
    )
    source_user_id = fields.Many2one(
        "res.users", ondelete="set null", index=True,
        help="User whose permissions are used for business records and tools.",
    )
    source_company_id = fields.Many2one(
        "res.company", ondelete="set null",
        help="Company active when the source message was posted.",
    )

    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    started_at = fields.Datetime(readonly=True)
    claim_token = fields.Char(readonly=True, copy=False, index=True)
    error_message = fields.Text(readonly=True)

    _unique_agent_message = models.Constraint(
        "UNIQUE(agent_id, message_id)",
        "A reply job is already registered for this message and agent.",
    )

    @api.model
    def _claim_pending(self, agent_types=None):
        """Atomically claim one pending job for immediate processing.

        ``agent_types`` restricts the claim to jobs whose ``discuss.agent`` has
        one of the given ``agent_type`` values, so each bridge worker only
        consumes its own kind (e.g. ``["llm"]`` for the in-process worker,
        ``["agentbox"]`` for an external JSON-RPC runtime).

        Uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers each grab a
        distinct job. The returned recordset is invalidated so the SQL-side
        state changes are visible without re-reading.
        """
        token = uuid.uuid4().hex
        params = [token]
        agent_filter = ""
        if agent_types:
            agent_filter = (
                "AND candidate.agent_id IN "
                "(SELECT id FROM discuss_agent WHERE agent_type IN %s)"
            )
            params.append(tuple(agent_types))
        query = f"""
            UPDATE {self._table} AS job
               SET state = 'processing',
                   started_at = NOW(),
                   claim_token = %s,
                   attempt_count = job.attempt_count + 1,
                   write_date = NOW()
             WHERE job.id = (
                SELECT candidate.id
                  FROM {self._table} AS candidate
                 WHERE candidate.state = 'pending'
                 {agent_filter}
                 ORDER BY candidate.id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
             )
         RETURNING job.id
        """
        self.env.cr.execute(query, params)
        row = self.env.cr.fetchone()
        job = self.browse(row[0]) if row else self.browse()
        job.invalidate_recordset(
            ["state", "started_at", "claim_token", "attempt_count", "write_date"]
        )
        return job

    def _execution_user_and_company(self):
        """Resolve the execution identity captured at enqueue time, fail closed."""
        self.ensure_one()
        source_user = self.source_user_id
        if not (
            source_user
            and source_user.active
            and source_user.has_group("base.group_user")
        ):
            raise UserError(
                _("The original execution user is no longer available.")
            )
        company = self.source_company_id or source_user.company_id
        if company not in source_user.company_ids:
            raise UserError(
                _("The execution company is not available to the user.")
            )
        return source_user, company

    def _post_reply(self, body):
        """Publish the reply authored by the persona (narrow sudo, posting only)."""
        self.ensure_one()
        if not (self.reply_partner_id and self.channel_id.exists()):
            return
        self.channel_id.sudo().message_post(
            author_id=self.reply_partner_id.id,
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

    def _complete(self, result):
        """Finalize a job with the generated reply and publish it.

        ``result`` is the dict returned by ``discuss.agent._discuss_execute``:
        ``{"result_html"/"result"}``. Returns ``False`` when the reply is empty.
        """
        self.ensure_one()
        body = (result or {}).get("result_html") or (result or {}).get("result")
        if not body:
            return False
        self._post_reply(body)
        self.write(
            {
                "state": "done",
                "started_at": False,
                "claim_token": False,
                "error_message": False,
            }
        )
        return True

    def _complete_error(self, error):
        """Finalize a job as failed."""
        self.ensure_one()
        self.write(
            {
                "state": "error",
                "started_at": False,
                "claim_token": False,
                "error_message": str(error)[:4000],
            }
        )
