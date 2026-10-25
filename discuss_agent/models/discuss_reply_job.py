import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

BATCH_SIZE = 50
GC_RETENTION_DAYS = 7
PROCESSING_TIMEOUT_MINUTES = 120


class LostQueueClaimError(Exception):
    """Raised when another worker has fenced an expired queue claim."""


class DiscussReplyJob(models.Model):
    """Pending reply for a Discuss message, decoupled from who consumes it.

    ``discuss.reply.job`` is the interface-level carrier of "one message is
    owed a reply by one agent". It captures the *persona* (``reply_partner_id``)
    and the *execution identity* (``source_user_id``) at enqueue time, so the
    two never have to be the same.

    It carries the full lifecycle needed by either consumer shape:

    * a synchronous consumer (in-process LLM) calls ``_process_pending`` →
      ``_process_one``, which generates the reply and completes the job;
    * an asynchronous consumer (external JSON-RPC agent such as agent-box)
      polls pending jobs via ``_claim_pending``, generates a reply out-of-band,
      then calls ``_complete`` back.

    Both share the same fencing / timeout / GC state machine.
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
    page_context = fields.Json(
        default=dict,
        help="Validated page metadata captured when the source message was sent.",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Attachments",
        help="Inbound attachments snapshot captured at enqueue time.",
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

    # -- persona & authorization -------------------------------------------

    def _reply_partner(self):
        self.ensure_one()
        return self.reply_partner_id

    def _reply_is_authorized(self):
        """Revalidate sender and current channel assignment before any bot post."""
        self.ensure_one()
        source_user = self.source_user_id
        if not source_user or not source_user.active:
            return False
        if not source_user.has_group("base.group_user"):
            return False
        return self.channel_id._discuss_user_can_use_agent(
            self.agent_id,
            source_user,
        )

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

    # -- fencing / lifecycle ----------------------------------------------

    @api.model
    def _expire_stale_jobs(self):
        """Fence timed-out workers without automatically replaying their tools."""
        cutoff = fields.Datetime.now() - timedelta(minutes=PROCESSING_TIMEOUT_MINUTES)
        query = f"""
            UPDATE {self._table}
               SET state = 'error',
                   started_at = NULL,
                   claim_token = NULL,
                   error_message = %s,
                   write_date = NOW()
             WHERE state = 'processing'
               AND started_at < %s
         RETURNING id
        """
        self.env.cr.execute(
            query,
            (
                "Agent processing timed out; automatic replay was disabled "
                "to avoid repeating tool side effects.",
                cutoff,
            ),
        )
        stale = self.browse([row[0] for row in self.env.cr.fetchall()])
        stale.invalidate_recordset(
            ["state", "started_at", "claim_token", "error_message", "write_date"]
        )
        return stale

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

    def _lock_owned_claim(self, claim_token):
        """Lock this row and verify the caller still owns its fencing token."""
        self.ensure_one()
        query = f"""
            SELECT state, claim_token
              FROM {self._table}
             WHERE id = %s
             FOR UPDATE
        """
        self.env.cr.execute(query, (self.id,))
        row = self.env.cr.fetchone()
        return bool(
            row
            and row[0] == "processing"
            and row[1]
            and row[1] == claim_token
        )

    @api.model
    def _gc_processed_jobs(self):
        cutoff = fields.Datetime.now() - timedelta(days=GC_RETENTION_DAYS)
        stale = self.search(
            [
                ("state", "in", ["done", "error"]),
                ("create_date", "<", cutoff),
            ]
        )
        if stale:
            stale.unlink()

    # -- background context ------------------------------------------------

    def _build_background(self, execution_user, company):
        """Re-check the page reference and return a minimal ACL-safe snapshot."""
        self.ensure_one()
        page = dict(self.page_context or {})
        background = {"page": page} if page else {}
        model_name = page.get("res_model")
        res_id = page.get("res_id")
        if not (model_name and res_id and model_name in self.env):
            return background, {}

        try:
            record = (
                self.env[model_name]
                .sudo(False)
                .with_user(execution_user)
                .with_company(company)
                .browse(int(res_id))
                .exists()
            )
            if not record:
                return background, {}
            record.check_access("read")
            background["record"] = {
                "model": model_name,
                "id": record.id,
                "display_name": record.display_name,
            }
            return background, {"model": model_name, "res_id": record.id}
        except Exception:  # noqa: BLE001 - stale/inaccessible context must not elevate
            _logger.info(
                "discuss_agent: execution user %s cannot read context %s,%s",
                execution_user.id,
                model_name,
                res_id,
            )
            page.pop("res_id", None)
            return background, {}

    # -- typing ------------------------------------------------------------

    def _set_bot_typing(self, is_typing):
        """Drive Odoo's native typing member state for the reply persona."""
        for job in self:
            reply_partner = job._reply_partner()
            if not reply_partner or not job.channel_id:
                continue
            member = job.channel_id.channel_member_ids.filtered(
                lambda channel_member: channel_member.partner_id == reply_partner
            )[:1]
            if member:
                member._notify_typing(is_typing)

    def _clear_bot_typing_if_idle(self):
        """Clear this persona only when it has no other active channel job."""
        self.ensure_one()
        reply_partner = self._reply_partner()
        active_jobs = self.search(
            [
                ("agent_id", "=", self.agent_id.id),
                ("channel_id", "=", self.channel_id.id),
                ("state", "in", ["pending", "processing"]),
            ]
        )
        other_active = any(
            job._reply_partner() == reply_partner for job in active_jobs
        )
        if not other_active:
            self._set_bot_typing(False)

    # -- posting / completion ----------------------------------------------

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

    def _post_final_failure(self):
        self.ensure_one()
        reply_partner = self._reply_partner()
        if not reply_partner or not self.channel_id or not self._reply_is_authorized():
            return
        timed_out = "processing timed out" in (self.error_message or "").lower()
        body = (
            _(
                "Processing timed out and its final result is unknown. "
                "Please verify any requested action before trying again."
            )
            if timed_out
            else _("Sorry, I could not complete that request. Please try again.")
        )
        try:
            with self.env.cr.savepoint():
                self.channel_id.sudo().message_post(
                    author_id=reply_partner.id,
                    body=body,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
        except Exception:  # noqa: BLE001 - queue finalization must still commit
            _logger.exception(
                "discuss_agent: could not post failure notice for job %s",
                self.id,
            )

    def _mark_failure(self, error, claim_token):
        """Finalize as error only if this worker still owns the claim.

        Failed runs are intentionally not replayed automatically: a tool may
        have produced an external side effect that the database cannot roll
        back or identify as idempotent.
        """
        self.ensure_one()
        if not self._lock_owned_claim(claim_token):
            raise LostQueueClaimError()
        self.write(
            {
                "state": "error",
                "started_at": False,
                "claim_token": False,
                "error_message": str(error)[:4000],
            }
        )
        self._post_final_failure()

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

    # -- processing loop ---------------------------------------------------

    def _process_one(self):
        """Generate one complete non-streaming answer under the source identity.

        Synchronous consumer path only. Runs the responder through
        ``discuss.agent._discuss_execute`` under the captured execution user,
        then posts the reply and marks the job done under the fencing lock.
        """
        self.ensure_one()
        claim_token = self.claim_token
        if self.state != "processing" or not claim_token:
            return
        lost_claim = False
        self._set_bot_typing(True)
        self.env.cr.commit()
        try:
            with self.env.cr.savepoint():
                agent = self.agent_id
                message = self.message_id
                channel = self.channel_id
                reply_partner = self._reply_partner()
                if not (reply_partner and message.exists() and channel.exists()):
                    raise UserError(
                        _(
                            "The agent, reply persona, message, or channel is "
                            "no longer available."
                        )
                    )

                if not self._reply_is_authorized():
                    raise UserError(
                        _("You are no longer allowed to use this agent.")
                    )

                execution_user, company = self._execution_user_and_company()
                background, thread_vals = self._build_background(
                    execution_user,
                    company,
                )
                query = html2plaintext(message.body) if message.body else ""

                result = agent._discuss_execute(
                    execution_user=execution_user,
                    company=company,
                    query=query,
                    background=background,
                    thread_vals=thread_vals,
                    attachment_ids=self.attachment_ids.ids,
                    stream=False,
                )
                if result.get("error"):
                    raise UserError(result["error"])

                body = result.get("result_html") or result.get("result") or ""
                if not body:
                    raise UserError(_("The agent returned an empty response."))

                if not self._lock_owned_claim(claim_token):
                    raise LostQueueClaimError()
                if not self._reply_is_authorized():
                    raise UserError(
                        _("The agent is no longer assigned to this conversation.")
                    )

                channel.sudo().message_post(
                    author_id=reply_partner.id,
                    body=body,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
                self.write(
                    {
                        "state": "done",
                        "started_at": False,
                        "claim_token": False,
                        "error_message": False,
                    }
                )
        except LostQueueClaimError:
            lost_claim = True
            _logger.warning(
                "discuss_agent: discarded result for job %s after losing claim",
                self.id,
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures per job
            _logger.exception(
                "discuss_agent: failed to process reply job %s",
                self.id,
            )
            try:
                self._mark_failure(exc, claim_token)
            except LostQueueClaimError:
                lost_claim = True
        finally:
            if lost_claim:
                self.env.cr.rollback()
            else:
                self.env.cr.commit()
                self.invalidate_recordset()
                self._clear_bot_typing_if_idle()
                self.env.cr.commit()

    @api.model
    def _process_pending(self, agent_types=None, batch_size=BATCH_SIZE):
        """Process a batch of pending jobs of the given responder kinds."""
        stale = self._expire_stale_jobs()
        self.env.cr.commit()
        for job in stale:
            job._post_final_failure()
            job._clear_bot_typing_if_idle()
            self.env.cr.commit()

        for _index in range(batch_size):
            job = self._claim_pending(agent_types=agent_types)
            self.env.cr.commit()
            if not job:
                break
            job._process_one()
        self._gc_processed_jobs()
