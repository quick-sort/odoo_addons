from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError


class AgenthubChannel(models.Model):
    """A transport — *how* messages travel in and out of Odoo.

    Channels are a ``component`` collection. Each concrete channel type lives in
    its own addon (``agenthub_wecom``, ...) and contributes a ``selection_add``
    entry on ``channel_type`` plus an ``agenthub.channel.adapter`` component
    resolved by usage.

    The core keeps no channel-specific columns; a channel addon adds its own
    config fields (``bot_id``/``secret`` for WeCom, ...) with ``_inherit``.
    """

    _name = "agenthub.channel"
    _description = "Agent Hub Channel"
    _inherit = ["collection.base"]
    _order = "name"

    name = fields.Char(required=True)
    channel_type = fields.Selection(
        selection=[],
        required=True,
        help="How messages travel. Each channel addon adds its own value.",
    )
    active = fields.Boolean(default=True)
    last_run_at = fields.Datetime(readonly=True)
    error_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)

    def _adapter(self):
        """Resolve the transport adapter for this channel's type, or ``None``."""
        self.ensure_one()
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=self.channel_type)
        except (NoComponentError, RegistryNotReadyError):
            return None

    def send(self, message):
        """Deliver an outbound ``mail.message`` to the channel's peer."""
        self.ensure_one()
        adapter = self._adapter()
        if adapter is None:
            raise UserError(
                _(
                    "No channel adapter is registered for type '%(type)s'. "
                    "Is the addon providing it installed?",
                    type=self.channel_type,
                )
            )
        return adapter.send(self, message)
