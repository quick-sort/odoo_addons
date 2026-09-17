from odoo import _, fields, models
from odoo.exceptions import UserError


class InfohubChannel(models.Model):
    _inherit = "infohub.channel"

    channel_type = fields.Selection(
        selection_add=[("biomedtracker", "BioMedTracker (Citeline)")],
        ondelete={"biomedtracker": "cascade"},
    )

    biomedtracker_username = fields.Char(
        string="Username",
        help="BioMedTracker account used by the automated login.",
    )
    biomedtracker_password = fields.Char(
        string="Password",
        help="BioMedTracker account password. Store a password only when the "
        "instance is not using a secret store; prefer ``manual_cookie`` on "
        "shared installations.",
    )
    biomedtracker_manual_cookie = fields.Text(
        string="Manual Cookie",
        help="Session cookie pasted from a browser session, for accounts the "
        "automated login cannot handle. Takes precedence when the stored "
        "session cookie is empty.",
    )
    biomedtracker_session_cookie = fields.Text(
        string="Session Cookie",
        readonly=True,
        copy=False,
        help="Cookie stored after a successful automated login; reused until "
        "the server rejects it.",
    )

    def action_biomedtracker_login(self):
        """Run the login handshake from the channel form."""
        for channel in self:
            try:
                channel._component("infohub.login").login()
            except Exception as exc:  # noqa: BLE001 — surfaced to the user
                raise UserError(_("BioMedTracker login failed: %s") % exc) from exc
        return True

    def _biomedtracker_cookie(self):
        """The cookie to send, preferring the freshest stored session."""
        self.ensure_one()
        return (
            self.biomedtracker_session_cookie
            or self.biomedtracker_manual_cookie
            or ""
        )
