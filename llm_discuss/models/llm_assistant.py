import logging

from psycopg2 import IntegrityError

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ODOOBOT_UNIQUE_KEY = "odoobot"


class LlmAssistant(models.Model):
    _inherit = "llm.assistant"

    discuss_user_id = fields.Many2one(
        "res.users",
        string="Discuss Bot User",
        readonly=True,
        copy=False,
        help="Internal technical user representing this assistant inside "
        "Discuss / Live Chat. Created via the 'Create Bot User' button. "
        "Add this user to a chat/channel to let the assistant participate "
        "in it.",
    )
    discuss_enabled = fields.Boolean(
        string="Enable in Discuss",
        help="When enabled, this assistant automatically replies to "
        "messages in Discuss according to the Reply Trigger below. "
        "Requires a Bot User.",
    )
    discuss_trigger_mode = fields.Selection(
        [
            ("both", "Direct chat or @mention"),
            ("direct_chat", "Only in direct 1:1 chat"),
            ("mention", "Only when @mentioned"),
        ],
        string="Reply Trigger",
        default="both",
        required=True,
        help="Direct chat: the assistant replies to every message in its "
        "1:1 conversation with a user. @mention: the assistant only "
        "replies when explicitly mentioned in a (multi-user) channel.",
    )
    odoobot_enabled = fields.Boolean(
        string="Use for OdooBot Private Chat",
        copy=False,
        help="After each user's native OdooBot onboarding is complete, use this "
        "assistant for that same OdooBot private chat. Replies still appear as "
        "OdooBot, while hidden threads and tools run with the sender's permissions.",
    )
    odoobot_unique_key = fields.Char(
        readonly=True,
        copy=False,
    )

    _unique_odoobot_assistant = models.Constraint(
        "UNIQUE(odoobot_unique_key)",
        "Only one assistant can be configured for OdooBot private chat.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            vals["odoobot_unique_key"] = (
                ODOOBOT_UNIQUE_KEY if vals.get("odoobot_enabled") else False
            )
            normalized_vals_list.append(vals)
        return super().create(normalized_vals_list)

    def write(self, vals):
        vals = dict(vals)
        if "odoobot_enabled" in vals:
            vals["odoobot_unique_key"] = (
                ODOOBOT_UNIQUE_KEY if vals["odoobot_enabled"] else False
            )
        else:
            # The key is an internal database-enforced implementation detail.
            vals.pop("odoobot_unique_key", None)
        return super().write(vals)

    def action_create_discuss_user(self):
        """Create the least-privileged internal user representing the bot."""
        for assistant in self:
            if assistant.discuss_user_id:
                continue
            login = f"llm-bot-{assistant.code or assistant.id}@bot.internal"
            user = (
                self.env["res.users"]
                .sudo()
                .with_context(no_reset_password=True)
                .create(
                    {
                        "name": assistant.name,
                        "login": login,
                        "share": False,
                        "active": True,
                        "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
                    }
                )
            )
            assistant.discuss_user_id = user.id
            _logger.info(
                "llm_discuss: created bot user %s (login=%s) for assistant %s",
                user.id,
                login,
                assistant.id,
            )
        return True

    def _discuss_bot_partner(self):
        self.ensure_one()
        return self.discuss_user_id.partner_id

    @api.model
    def _get_odoobot_assistant(self):
        """Return the single active assistant configured for OdooBot chat."""
        return self.sudo().search(
            [
                ("active", "=", True),
                ("odoobot_enabled", "=", True),
            ],
            limit=1,
        )

    @api.model
    def get_available_discuss_assistants(self):
        """Return safe launcher metadata for assistants available to the user."""
        user = self.env.user
        if not user.has_group("base.group_user"):
            return []
        assistants = self.sudo()._get_allowed_assistants_for_user(user).filtered(
            lambda assistant: (
                assistant.active
                and assistant.discuss_enabled
                and assistant.discuss_user_id
                and assistant.discuss_user_id.active
            )
        )
        assistants = assistants.sorted(
            key=lambda assistant: (not assistant.is_default, assistant.name or "")
        )
        return [
            {
                "id": assistant.id,
                "name": assistant.name,
                "bot_user_id": assistant.discuss_user_id.id,
                "bot_partner_id": assistant.discuss_user_id.partner_id.id,
                "is_default": assistant.is_default,
            }
            for assistant in assistants
        ]

    @api.model
    def get_odoobot_discuss_config(self):
        """Return only the OdooBot persona metadata safe for the current user."""
        user = self.env.user
        assistant = self._get_odoobot_assistant()
        if not (
            user.has_group("base.group_user")
            and assistant
            and assistant in assistant._get_allowed_assistants_for_user(user)
        ):
            return {}
        return {"bot_partner_id": self.env.ref("base.partner_root").id}

    @api.model
    def _llm_discuss_normalize_page_context(self, page_context, user):
        """Validate client page metadata using ``user`` record access.

        Invalid or inaccessible context is ignored rather than rejecting the
        already-authorized Discuss message. Business data is fetched again by
        the worker, so this method stores only a validated reference snapshot.
        """
        if not isinstance(page_context, dict):
            return {}

        normalized = {"version": 1}
        view_type = page_context.get("view_type")
        if view_type in {"form", "list", "kanban", "calendar", "graph", "pivot", "activity"}:
            normalized["view_type"] = view_type

        action_id = page_context.get("action_id")
        if isinstance(action_id, int) and action_id > 0:
            normalized["action_id"] = action_id
        elif isinstance(action_id, str) and 0 < len(action_id) <= 128:
            normalized["action_id"] = action_id

        model_name = page_context.get("res_model")
        if not isinstance(model_name, str) or model_name not in self.env:
            return normalized if len(normalized) > 1 else {}
        normalized["res_model"] = model_name

        res_id = page_context.get("res_id")
        if not res_id:
            return normalized
        try:
            res_id = int(res_id)
        except (TypeError, ValueError):
            return normalized
        if res_id <= 0:
            return normalized

        try:
            record = self.env[model_name].sudo(False).with_user(user).browse(res_id).exists()
            if not record:
                return normalized
            record.check_access("read")
        except Exception:  # noqa: BLE001 - inaccessible context is intentionally discarded
            _logger.info(
                "llm_discuss: user %s cannot use page context %s,%s",
                user.id,
                model_name,
                res_id,
            )
            return normalized

        normalized["res_id"] = res_id
        return normalized

    def _llm_discuss_enqueue_reply(
        self,
        channel,
        message,
        source_user,
        reply_partner,
        page_context,
    ):
        """Idempotently persist one reply while keeping persona and ACL separate."""
        self.ensure_one()
        if not reply_partner:
            return False

        Queue = self.env["llm.discuss.reply.queue"].sudo()
        job = Queue.search(
            [
                ("assistant_id", "=", self.id),
                ("message_id", "=", message.id),
            ],
            limit=1,
        )
        if not job:
            try:
                # The savepoint keeps a concurrent unique-constraint conflict
                # from aborting the user's message transaction.
                with self.env.cr.savepoint():
                    job = Queue.create(
                        {
                            "assistant_id": self.id,
                            "channel_id": channel.id,
                            "message_id": message.id,
                            "reply_partner_id": reply_partner.id,
                            "source_user_id": source_user.id,
                            "source_company_id": self.env.company.id,
                            "execution_mode": (
                                "source_user"
                                if source_user.has_group("base.group_user")
                                else "assistant_user"
                            ),
                            "page_context": page_context,
                        }
                    )
            except IntegrityError:
                job = Queue.search(
                    [
                        ("assistant_id", "=", self.id),
                        ("message_id", "=", message.id),
                    ],
                    limit=1,
                )
        if not job or job.state not in {"pending", "processing"}:
            return False
        job._set_bot_typing(True)
        return True

    @api.model
    def _llm_discuss_trigger_queue_cron(self):
        cron = self.env.ref(
            "llm_discuss.ir_cron_process_reply_queue",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _llm_discuss_dispatch(self, channel, message, msg_vals):
        """Evaluate ordinary bot triggers and enqueue without blocking the post."""
        source_user = self.env.user
        raw_page_context = self.env.context.get("llm_discuss_page_context")
        page_context = self._llm_discuss_normalize_page_context(
            raw_page_context,
            source_user,
        )
        assistants = self.sudo().search(
            [
                ("active", "=", True),
                ("discuss_enabled", "=", True),
                ("discuss_user_id", "!=", False),
            ]
        )
        if not assistants:
            return

        triggered = False
        for assistant in assistants:
            try:
                if not channel._llm_discuss_user_can_use_assistant(
                    assistant,
                    source_user,
                ):
                    continue
                if not channel._llm_discuss_should_trigger(assistant, message, msg_vals):
                    continue
                triggered |= assistant._llm_discuss_enqueue_reply(
                    channel,
                    message,
                    source_user,
                    assistant.discuss_user_id.partner_id,
                    page_context,
                )
            except Exception:  # noqa: BLE001 - assistant failure must not abort message posting
                _logger.exception(
                    "llm_discuss: error dispatching assistant %s on channel %s",
                    assistant.id,
                    channel.id,
                )

        if triggered:
            self._llm_discuss_trigger_queue_cron()

    def _llm_discuss_dispatch_odoobot(self, channel, message):
        """Queue this assistant behind the native OdooBot private-chat persona."""
        self.ensure_one()
        source_user = self.env.user
        if not (
            self.active
            and self.odoobot_enabled
            and source_user.has_group("base.group_user")
            and channel._llm_discuss_user_can_use_assistant(self, source_user)
        ):
            return

        page_context = self._llm_discuss_normalize_page_context(
            self.env.context.get("llm_discuss_page_context"),
            source_user,
        )
        odoobot_partner = self.env.ref("base.partner_root")
        if self._llm_discuss_enqueue_reply(
            channel,
            message,
            source_user,
            odoobot_partner,
            page_context,
        ):
            self._llm_discuss_trigger_queue_cron()
