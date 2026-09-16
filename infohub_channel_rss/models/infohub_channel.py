import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.infohub.url_guard import UrlNotAllowed, assert_url_allowed

_logger = logging.getLogger(__name__)


class InfohubChannel(models.Model):
    _inherit = "infohub.channel"

    channel_type = fields.Selection(
        selection_add=[("rss", "RSS / Atom")],
        ondelete={"rss": "cascade"},
    )

    #: One channel polls exactly one feed — several feeds mean several channels,
    #: each with its own auto-fetch switch and its own item filter.
    rss_url = fields.Char(
        string="Feed URL",
        help="URL of the RSS or Atom feed to poll.",
    )

    @api.constrains("rss_url", "channel_type")
    def _check_rss_url(self):
        """Reject unsafe URLs on save, without performing DNS.

        This is the fast half of the SSRF check: scheme, hostname presence,
        literal IPs and known-local names. Resolution happens at request time
        (see the fetch component), because a save-time lookup would block the
        write on DNS and could not guarantee the address stays the same anyway.
        """
        for channel in self:
            if channel.channel_type != "rss" or not channel.rss_url:
                continue
            try:
                assert_url_allowed(channel.rss_url, resolve=False)
            except UrlNotAllowed as exc:
                raise ValidationError(str(exc)) from exc
