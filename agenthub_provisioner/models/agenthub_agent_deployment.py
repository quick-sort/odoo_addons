import fnmatch
import hashlib
import json
import logging
import os

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..contract import ContainerSpec, ProvisionerError
from ..utils import (
    CONTAINER_NAME_RE,
    SECRET_KEY_RE,
    mask_env,
    mask_text,
    validate_env,
    validate_volumes,
)

_logger = logging.getLogger(__name__)

RESERVED_ENV = {"RELAY_AGENT_ID", "RELAY_AGENT_TOKEN"}

CONTAINER_STATE_MAP = {
    "running": "running",
    "restarting": "running",
    "created": "stopped",
    "exited": "stopped",
    "paused": "stopped",
    "dead": "error",
    "removing": "stopping",
}


class AgenthubAgentDeployment(models.Model):
    _name = "agenthub.agent.deployment"
    _description = "Agent Hub Agent Deployment"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True)
    agent_id = fields.Many2one(
        "agenthub.agent",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    host_id = fields.Many2one(
        "agenthub.provisioner.host",
        required=True,
        ondelete="restrict",
        index=True,
    )

    mode = fields.Selection(
        [("relay", "Relay"), ("odoo_discuss", "Odoo Discuss")],
        default="relay",
        required=True,
    )
    image = fields.Char(required=True)
    pull_policy = fields.Selection(
        [("missing", "If Missing"), ("always", "Always"), ("never", "Never")],
        default="missing",
        required=True,
    )
    command = fields.Json(help="Container command as a JSON array of strings.")
    container_name = fields.Char(required=True, copy=False)
    runtime_id = fields.Char(readonly=True, copy=False)

    desired_state = fields.Selection(
        [("running", "Running"), ("stopped", "Stopped"), ("absent", "Absent")],
        default="stopped",
        required=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("provisioning", "Provisioning"),
            ("running", "Running"),
            ("stopping", "Stopping"),
            ("stopped", "Stopped"),
            ("error", "Error"),
            ("removed", "Removed"),
        ],
        default="draft",
        readonly=True,
        tracking=True,
    )
    config_hash = fields.Char(readonly=True, copy=False)
    config_drift = fields.Boolean(readonly=True, copy=False)
    last_action_at = fields.Datetime(readonly=True)
    last_status_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    relay_url = fields.Char(help="Overrides the host default and agenthub.relay_url.")
    relay_heartbeat_seconds = fields.Integer(default=20, required=True)
    llm_profile_id = fields.Many2one(
        "agenthub.provisioner.llm",
        ondelete="set null",
    )

    odoo_url = fields.Char(help="Defaults to web.base.url.")
    odoo_db = fields.Char(help="Defaults to the current database.")
    odoo_login = fields.Char(help="Defaults to the agent's service user login.")
    odoo_api_key = fields.Char(groups="base.group_system")
    odoo_channel_id = fields.Integer()

    extra_env = fields.Json()
    volumes = fields.Json(help="{name: {bind, mode}}; defaults to a home volume.")
    network = fields.Char(help="Overrides the host default network.")
    restart_policy = fields.Selection(
        [
            ("no", "No"),
            ("always", "Always"),
            ("unless-stopped", "Unless Stopped"),
            ("on-failure", "On Failure"),
        ],
        default="unless-stopped",
        required=True,
    )
    auto_heal = fields.Boolean(
        help="Re-apply when the container disappears. Off by default.",
    )
    logs_tail = fields.Integer(default=200)

    _deployment_agent_uniq = models.Constraint(
        "UNIQUE(agent_id)",
        "An agent can have only one deployment.",
    )
    _deployment_container_uniq = models.Constraint(
        "UNIQUE(container_name)",
        "Container names must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        default_image = self.env["ir.config_parameter"].sudo().get_param(
            "agenthub.provisioner.image",
            "ghcr.io/quick-sort/agent-box:latest",
        )
        for vals in vals_list:
            agent = (
                self.env["agenthub.agent"].browse(vals["agent_id"])
                if vals.get("agent_id")
                else None
            )
            if not vals.get("image"):
                image = False
                if vals.get("host_id"):
                    image = self.env["agenthub.provisioner.host"].browse(
                        vals["host_id"]
                    ).default_image
                vals["image"] = image or default_image
            if not vals.get("container_name") and agent:
                vals["container_name"] = "agenthub-agent-%s" % agent.id
            if not vals.get("name") and agent:
                vals["name"] = "%s deployment" % agent.name
        return super().create(vals_list)

    @api.constrains("container_name")
    def _check_container_name(self):
        for deployment in self:
            if deployment.container_name and not CONTAINER_NAME_RE.match(
                deployment.container_name
            ):
                raise ValidationError(
                    _(
                        "Invalid container name '%s'. Use letters, digits, '_', "
                        "'-' and '.', starting with an alphanumeric character."
                    )
                    % deployment.container_name
                )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _check_provisioner_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(
                _("Only system administrators can manage agent deployments.")
            )

    def _relay_url_value(self):
        self.ensure_one()
        return (
            self.relay_url
            or self.host_id.default_relay_url
            or self.env["ir.config_parameter"].sudo().get_param("agenthub.relay_url")
        )

    def _odoo_url_value(self):
        self.ensure_one()
        return self.odoo_url or self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url"
        )

    def _odoo_db_value(self):
        self.ensure_one()
        return self.odoo_db or self.env.cr.dbname

    def _odoo_login_value(self):
        self.ensure_one()
        return self.odoo_login or (self.agent_id.user_id.login or "")

    def _command_tuple(self):
        self.ensure_one()
        command = self.command
        if command:
            if not isinstance(command, (list, tuple)) or not all(
                isinstance(part, str) and part for part in command
            ):
                raise UserError(
                    _("Command must be a JSON array of non-empty strings.")
                )
            return tuple(command)
        if self.mode == "relay":
            return ("uv", "run", "agent-box", "--relay")
        return ("uv", "run", "agent-box", "--odoo")

    def _render_volumes(self):
        self.ensure_one()
        if self.volumes:
            return validate_volumes(self.volumes)
        return {
            "%s-home" % self.container_name: {"bind": "/home/agent", "mode": "rw"}
        }

    @api.model
    def _token_secret(self):
        secret = os.environ.get("AGENTHUB_PROVISIONER_TOKEN_SECRET")
        if not secret:
            secret = self.env["ir.config_parameter"].sudo().get_param(
                "agenthub.provisioner.token_secret"
            )
        if not secret:
            raise UserError(
                _(
                    "No provisioner token secret is configured. Set "
                    "AGENTHUB_PROVISIONER_TOKEN_SECRET or the "
                    "agenthub.provisioner.token_secret system parameter."
                )
            )
        return secret

    def _render_env(self):
        self.ensure_one()
        env = validate_env(self.host_id.default_env or {})

        if self.mode == "relay":
            relay_url = self._relay_url_value()
            if not relay_url:
                raise UserError(
                    _(
                        "Deployment '%s' uses relay mode but no relay URL is "
                        "configured."
                    )
                    % self.name
                )
            env.update(
                {
                    "RELAY_URL": relay_url,
                    "RELAY_AGENT_ID": str(self.agent_id.id),
                    "RELAY_AGENT_TOKEN": self.agent_id._provisioner_token(),
                    "RELAY_HEARTBEAT_SECONDS": str(
                        max(1, int(self.relay_heartbeat_seconds or 20))
                    ),
                }
            )
        else:
            missing = []
            if not self._odoo_url_value():
                missing.append("odoo_url")
            if not self._odoo_db_value():
                missing.append("odoo_db")
            if not self._odoo_login_value():
                missing.append("odoo_login")
            if not self.odoo_api_key:
                missing.append("odoo_api_key")
            if missing:
                raise UserError(
                    _(
                        "Deployment '%(name)s' uses Odoo Discuss mode and is "
                        "missing: %(fields)s.",
                        name=self.name,
                        fields=", ".join(missing),
                    )
                )
            env.update(
                {
                    "ODOO_URL": self._odoo_url_value(),
                    "ODOO_DB": self._odoo_db_value(),
                    "ODOO_LOGIN": self._odoo_login_value(),
                    "ODOO_API_KEY": self.odoo_api_key,
                }
            )
            if self.odoo_channel_id:
                env["ODOO_CHANNEL_ID"] = str(self.odoo_channel_id)

        if self.llm_profile_id:
            env.update(self.llm_profile_id._render_env())

        env.update(validate_env(self.extra_env or {}, reserved=RESERVED_ENV))
        return env

    def _render_env_preview(self):
        self.ensure_one()
        return mask_env(self._render_env())

    def _allowed_images(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "agenthub.provisioner.allowed_images",
            "ghcr.io/quick-sort/agent-box:*",
        )
        return [item.strip() for item in (raw or "").split(",") if item.strip()]

    def _validate_image(self):
        self.ensure_one()
        patterns = self._allowed_images()
        if patterns and not any(
            fnmatch.fnmatchcase(self.image or "", pattern) for pattern in patterns
        ):
            raise UserError(
                _("Image '%(image)s' is not allowed by agenthub.provisioner.allowed_images.",
                  image=self.image or "")
            )

    def _validate_config(self):
        self.ensure_one()
        if not self.container_name or not CONTAINER_NAME_RE.match(
            self.container_name
        ):
            raise UserError(_("Deployment has an invalid container name."))
        if not self.image:
            raise UserError(_("Deployment has no image."))
        self._validate_image()
        self._command_tuple()
        self._render_volumes()
        self._render_env()

    def _spec_hash(self, env=None, command=None, volumes=None):
        self.ensure_one()
        payload = {
            "image": self.image,
            "command": list(command if command is not None else self._command_tuple()),
            "env": dict(env if env is not None else self._render_env()),
            "volumes": dict(
                volumes if volumes is not None else self._render_volumes()
            ),
            "network": self.network or self.host_id.default_network or "",
            "restart_policy": self.restart_policy,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _safe_spec_hash(self):
        try:
            return self._spec_hash()
        except Exception:  # noqa: BLE001 - drift detection must not raise
            return None

    def _render_spec(self):
        self.ensure_one()
        self._validate_config()
        env = self._render_env()
        command = self._command_tuple()
        volumes = self._render_volumes()
        config_hash = self._spec_hash(env=env, command=command, volumes=volumes)
        network = self.network or self.host_id.default_network or None
        return ContainerSpec(
            name=self.container_name,
            image=self.image,
            command=command,
            env=env,
            volumes=volumes,
            labels={
                "agenthub.managed": "true",
                "agenthub.agent_id": str(self.agent_id.id),
                "agenthub.deployment_id": str(self.id),
                "agenthub.config_hash": config_hash,
            },
            config_hash=config_hash,
            network=network,
            restart_policy=self.restart_policy,
            pull_policy=self.pull_policy,
        )

    # ------------------------------------------------------------------
    # Secrets / errors
    # ------------------------------------------------------------------

    def _sync_agent_token(self):
        self.ensure_one()
        if self.mode != "relay":
            return
        token = self.agent_id._provisioner_token()
        self.agent_id.sudo().write(
            {"token_hash": self.agent_id._hash_token(token)}
        )

    def _known_secrets(self):
        self.ensure_one()
        secrets = []
        if self.llm_profile_id.secret:
            secrets.append(self.llm_profile_id.secret)
        if self.odoo_api_key:
            secrets.append(self.odoo_api_key)
        for key, value in (self.extra_env or {}).items():
            if SECRET_KEY_RE.search(str(key)) and value:
                secrets.append(str(value))
        try:
            secrets.append(self.agent_id._provisioner_token())
        except Exception:  # noqa: BLE001 - masking is best effort
            _logger.debug(
                "Could not derive the agent token while masking", exc_info=True
            )
        return [secret for secret in secrets if secret]

    def _sanitize_error(self, exc):
        detail = exc.detail if isinstance(exc, ProvisionerError) else str(exc)
        if isinstance(exc, ProvisionerError):
            detail = f"{exc.code}: {detail}"
        return mask_text(detail, self._known_secrets())[:2000]

    # ------------------------------------------------------------------
    # Queue jobs / actions
    # ------------------------------------------------------------------

    def _enqueue(self, method_name):
        self.ensure_one()
        delayable = self.with_delay(
            channel="root.agenthub",
            identity_key="agenthub_provisioner.deployment.%s" % self.id,
            description="Agent Hub provisioner: %s %s"
            % (method_name, self.container_name),
        )
        getattr(delayable, method_name)()

    def action_apply(self):
        self.ensure_one()
        self._check_provisioner_access()
        if self.state in ("provisioning", "stopping"):
            raise UserError(_("An operation is already in progress."))
        self._validate_config()
        self.write(
            {
                "desired_state": "running",
                "state": "provisioning",
                "last_error": False,
            }
        )
        self._enqueue("_job_apply")
        return True

    def action_stop(self):
        self.ensure_one()
        self._check_provisioner_access()
        if self.state in ("provisioning", "stopping"):
            raise UserError(_("An operation is already in progress."))
        self.write(
            {
                "desired_state": "stopped",
                "state": "stopping",
                "last_error": False,
            }
        )
        self._enqueue("_job_stop")
        return True

    def action_remove(self):
        self.ensure_one()
        self._check_provisioner_access()
        if self.state in ("provisioning", "stopping"):
            raise UserError(_("An operation is already in progress."))
        self.write(
            {
                "desired_state": "absent",
                "state": "stopping",
                "last_error": False,
            }
        )
        self._enqueue("_job_remove")
        return True

    def action_rotate_token(self):
        self.ensure_one()
        self._check_provisioner_access()
        if self.state in ("provisioning", "stopping"):
            raise UserError(_("An operation is already in progress."))
        self.agent_id.sudo().write(
            {
                "provisioner_token_version": (
                    self.agent_id.provisioner_token_version or 1
                )
                + 1
            }
        )
        return self.action_apply()

    def action_sync(self):
        self.ensure_one()
        self._check_provisioner_access()
        return self._sync_status()

    def action_logs(self):
        self.ensure_one()
        self._check_provisioner_access()
        text = self._fetch_logs()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Logs: %s") % self.container_name,
                "message": text[:2000] or _("No logs."),
                "sticky": False,
            },
        }

    def _job_apply(self):
        self.ensure_one()
        try:
            self._sync_agent_token()
            spec = self._render_spec()
            state = self.host_id._driver().apply(self.host_id, spec)
            now = fields.Datetime.now()
            self.write(
                {
                    "state": CONTAINER_STATE_MAP.get(state.status, "running"),
                    "runtime_id": state.id or self.runtime_id,
                    "config_hash": spec.config_hash,
                    "config_drift": False,
                    "last_action_at": now,
                    "last_status_at": now,
                    "last_error": False,
                }
            )
        except Exception as exc:  # noqa: BLE001 - recorded, no queue retry loop
            _logger.exception("Provisioner apply failed for %s", self.container_name)
            self.write(
                {
                    "state": "error",
                    "last_action_at": fields.Datetime.now(),
                    "last_error": self._sanitize_error(exc),
                }
            )

    def _job_stop(self):
        self.ensure_one()
        try:
            self.host_id._driver().stop(
                self.host_id, self.runtime_id or self.container_name
            )
            self.write(
                {
                    "state": "stopped",
                    "last_action_at": fields.Datetime.now(),
                    "last_error": False,
                }
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Provisioner stop failed for %s", self.container_name)
            self.write(
                {
                    "state": "error",
                    "last_action_at": fields.Datetime.now(),
                    "last_error": self._sanitize_error(exc),
                }
            )

    def _job_remove(self):
        self.ensure_one()
        try:
            self.host_id._driver().remove(
                self.host_id, self.runtime_id or self.container_name
            )
            self.write(
                {
                    "state": "removed",
                    "runtime_id": False,
                    "config_hash": False,
                    "config_drift": False,
                    "last_action_at": fields.Datetime.now(),
                    "last_error": False,
                }
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Provisioner remove failed for %s", self.container_name)
            self.write(
                {
                    "state": "error",
                    "last_action_at": fields.Datetime.now(),
                    "last_error": self._sanitize_error(exc),
                }
            )

    def _sync_status(self):
        self.ensure_one()
        try:
            state = self.host_id._driver().status(
                self.host_id, self.runtime_id or self.container_name
            )
        except Exception as exc:  # noqa: BLE001
            self.write(
                {
                    "last_status_at": fields.Datetime.now(),
                    "last_error": self._sanitize_error(exc),
                }
            )
            return False

        now = fields.Datetime.now()
        vals = {"last_status_at": now, "runtime_id": state.id or self.runtime_id}
        if state.status == "missing":
            vals["config_drift"] = False
            if self.desired_state == "running":
                vals["state"] = "error"
                vals["last_error"] = _("Container is missing.")
            elif self.desired_state == "absent":
                vals["state"] = "removed"
                vals["runtime_id"] = False
                vals["last_error"] = False
            else:
                vals["state"] = "stopped"
                vals["last_error"] = False
        else:
            vals["state"] = CONTAINER_STATE_MAP.get(state.status, "running")
            labels = state.labels or {}
            current_hash = self._safe_spec_hash()
            vals["config_drift"] = bool(
                current_hash
                and labels.get("agenthub.config_hash") != current_hash
            )
            vals["last_error"] = False
        self.write(vals)
        return True

    def _fetch_logs(self):
        self.ensure_one()
        text = self.host_id._driver().logs(
            self.host_id,
            self.runtime_id or self.container_name,
            tail=max(1, int(self.logs_tail or 200)),
        )
        return mask_text(text, self._known_secrets())

    @api.model
    def _cron_reconcile(self):
        hosts = self.env["agenthub.provisioner.host"].sudo().search(
            [("active", "=", True)]
        )
        for host in hosts:
            host.action_probe()
        deployments = self.sudo().search(
            [("state", "not in", ("draft", "removed", "provisioning", "stopping"))]
        )
        for deployment in deployments:
            host = deployment.host_id
            if not host.active or host.state != "online":
                continue
            deployment._sync_status()
            if (
                deployment.auto_heal
                and deployment.desired_state == "running"
                and deployment.state in ("error", "stopped")
            ):
                try:
                    deployment.action_apply()
                except Exception:  # noqa: BLE001 - one bad deployment must not stop cron
                    _logger.exception(
                        "Provisioner auto-heal failed for %s",
                        deployment.container_name,
                    )
        return True
