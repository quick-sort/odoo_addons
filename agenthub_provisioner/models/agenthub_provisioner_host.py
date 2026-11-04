import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError

from ..contract import ProvisionerError

_logger = logging.getLogger(__name__)


class AgenthubProvisionerHost(models.Model):
    _name = "agenthub.provisioner.host"
    _description = "Agent Hub Provisioner Host"
    _inherit = ["collection.base"]
    _order = "name"

    name = fields.Char(required=True)
    driver_type = fields.Selection(
        selection=[],
        required=True,
        help="How containers are controlled. Each driver addon adds its own value.",
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("online", "Online"),
            ("offline", "Offline"),
            ("error", "Error"),
        ],
        default="unknown",
        readonly=True,
    )
    last_probe_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    default_image = fields.Char(
        default="ghcr.io/quick-sort/agent-box:latest",
        help="Image used when a deployment does not set its own.",
    )
    default_network = fields.Char(help="Docker network to attach containers to.")
    default_relay_url = fields.Char(help="Relay WebSocket URL used by deployments.")
    default_env = fields.Json(help="Environment variables shared by deployments.")

    deployment_ids = fields.One2many(
        "agenthub.agent.deployment",
        "host_id",
        string="Deployments",
    )

    _host_name_uniq = models.Constraint(
        "UNIQUE(name)",
        "Provisioner host names must be unique.",
    )

    def _check_provisioner_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(
                _("Only system administrators can manage provisioner hosts.")
            )

    def _driver(self):
        self.ensure_one()
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=self.driver_type)
        except (NoComponentError, RegistryNotReadyError) as exc:
            raise UserError(
                _(
                    "No provisioner driver is registered for type '%(type)s'. "
                    "Is the driver addon installed?",
                    type=self.driver_type or "",
                )
            ) from exc

    def action_probe(self):
        self.ensure_one()
        self._check_provisioner_access()
        ok = False
        detail = None
        try:
            probe = self._driver().probe(self)
            ok = probe.ok
            detail = probe.detail
        except ProvisionerError as exc:
            detail = exc.detail
        except Exception as exc:  # noqa: BLE001 - boundary, recorded for the admin
            _logger.exception("Provisioner host probe failed for %s", self.name)
            detail = str(exc)
        self.write(
            {
                "state": "online" if ok else "error",
                "last_probe_at": fields.Datetime.now(),
                "last_error": False if ok else (detail or "")[:2000],
            }
        )
        return True
