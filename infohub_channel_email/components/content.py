from odoo.addons.component.core import Component
from odoo.tools import html2plaintext


class InfohubFetchEmail(Component):
    """Email is pushed to us, not polled.

    Inbound mail arrives through ``mail.alias`` and is turned into an item by
    ``infohub.email.message.message_new``. There is nothing to fetch, so this
    exists only so the channel resolves like any other.
    """

    _name = "infohub.fetch.email"
    _inherit = "infohub.fetch"
    _usage = "infohub.fetch.email"

    def fetch_news(self, date_from=None, date_to=None, **kwargs):
        return {}, []


class InfohubContentEmail(Component):
    _name = "infohub.content.email"
    _inherit = "infohub.content"
    _usage = "infohub.content.email"

    def build_content(self, raw_data):
        data = raw_data or {}
        parts = []
        header = self._labelled(
            data,
            [
                ("Subject", "subject"),
                ("From", "email_from"),
                ("Date", "date"),
            ],
        )
        if header:
            parts.append("\n".join(header))

        body = self._first(data, ("body", "content", "summary"))
        if body:
            parts.append(html2plaintext(body))
        return "\n\n".join(parts)

    def subject(self, raw_data):
        return self._first(raw_data or {}, ("subject",))

    def source(self, raw_data):
        """The sender, which for a newsletter is the publication.

        Returned as the bare address; matching against ``infohub.source``
        happens by name or domain, and a mismatch simply leaves the item
        unattributed rather than guessing.
        """
        return self._first(raw_data or {}, ("email_from",))

    def date(self, raw_data):
        return self._first(raw_data or {}, ("date",))

    def url(self, raw_data):
        """Newsletters carry links in the body, not a canonical item URL."""
        return self._first(raw_data or {}, ("url", "link"))
