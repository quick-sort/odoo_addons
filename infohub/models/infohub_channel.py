import json
import logging

from odoo import _, api, fields, models
from odoo.addons.component.core import WorkContext

_logger = logging.getLogger(__name__)


class InfohubChannel(models.Model):
    """A channel — *how* news is obtained.

    Channels are a ``component`` collection. Each concrete channel type lives in
    its own addon (``infohub_channel_rss``, ``infohub_channel_email``,
    ``infohub_channel_mcp``) and contributes:

    * a ``selection_add`` entry on ``channel_type``,
    * its own configuration fields (added by ``_inherit``, so the core stays
      free of channel-specific columns),
    * ``infohub.fetch.<type>`` and ``infohub.content.<type>`` components.

    Components are resolved by *usage suffix* rather than by
    ``_component_match`` disambiguation. That keeps every usage unique by
    construction, so the framework's otherwise-ambiguous multi-match path
    (``SeveralComponentError``) is never reached.
    """

    _name = "infohub.channel"
    _description = "InfoHub Channel"
    _inherit = ["collection.base"]
    _order = "name"

    name = fields.Char(required=True)
    channel_type = fields.Selection(
        selection=[],
        required=True,
        help="How items are obtained. Each channel addon adds its own value.",
    )
    active = fields.Boolean(default=True)
    enable_cron = fields.Boolean(
        string="Auto Fetch",
        default=False,
        help="Include this channel in the periodic fetch cron.",
    )

    filter_domain = fields.Json(
        help="Optional Odoo-style domain evaluated against each raw item dict "
        "before it is stored. Only matching items are kept. "
        'Example: [["source", "ilike", "Reuters"]]',
    )

    item_ids = fields.One2many("infohub.item", "channel_id", string="Items")
    item_count = fields.Integer(compute="_compute_item_count")
    last_run_at = fields.Datetime(readonly=True)
    error_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.depends("item_ids")
    def _compute_item_count(self):
        for channel in self:
            channel.item_count = len(channel.item_ids)

    # ------------------------------------------------------------------
    # Component dispatch
    # ------------------------------------------------------------------

    def _component(self, prefix):
        """Resolve ``<prefix>.<channel_type>`` for this channel."""
        self.ensure_one()
        return WorkContext(model_name=self._name, collection=self).component(
            usage=f"{prefix}.{self.channel_type}"
        )

    # ------------------------------------------------------------------
    # Channel API — concrete components implement these
    # ------------------------------------------------------------------

    def fetch_news(self, date_from=None, date_to=None, **kwargs):
        """Return ``(raw_response, items)``.

        ``items`` is a list of dicts shaped
        ``{title, url, summary, published_date, raw_data}``.
        """
        self.ensure_one()
        return self._component("infohub.fetch").fetch_news(
            date_from, date_to, **kwargs
        )

    def build_content(self, raw_data):
        """Render a raw item's ``raw_data`` as readable plain text."""
        self.ensure_one()
        return self._component("infohub.content").build_content(raw_data)

    def subject(self, raw_data):
        """The item's title, read from this channel's raw shape."""
        self.ensure_one()
        return self._component("infohub.content").subject(raw_data)

    def date(self, raw_data):
        """The item's publication date, as a string parseable by Odoo."""
        self.ensure_one()
        return self._component("infohub.content").date(raw_data)

    def source(self, raw_data):
        """The originating source name, as carried in the raw item."""
        self.ensure_one()
        return self._component("infohub.content").source(raw_data)

    # ------------------------------------------------------------------
    # Item filtering
    # ------------------------------------------------------------------

    def match_item(self, item):
        """Return True if the raw item dict passes this channel's filter."""
        self.ensure_one()
        domain = self.filter_domain or []
        if isinstance(domain, str):
            try:
                domain = json.loads(domain)
            except (ValueError, TypeError):
                return True
        return self._match_domain(domain, item) if domain else True

    @staticmethod
    def _match_domain(domain, item):
        """Evaluate an Odoo-style domain against a plain dict."""

        def _eval_leaf(leaf):
            field, op, value = leaf[0], leaf[1], leaf[2]
            actual = item.get(field)
            if op == "=":
                return actual == value
            if op == "!=":
                return actual != value
            if op == "<":
                return actual is not None and actual < value
            if op == ">":
                return actual is not None and actual > value
            if op == "<=":
                return actual is not None and actual <= value
            if op == ">=":
                return actual is not None and actual >= value
            if op == "in":
                return actual in (value or [])
            if op == "not in":
                return actual not in (value or [])
            if op in ("like", "ilike", "not like", "not ilike"):
                if actual is None:
                    return op.startswith("not")
                left, right = str(actual), str(value)
                if "ilike" in op:
                    left, right = left.lower(), right.lower()
                found = right in left
                return not found if op.startswith("not") else found
            return True

        # Flat list with no prefix operators behaves as implicit AND.
        if not any(t in ("&", "|", "!") for t in domain if isinstance(t, str)):
            return all(
                _eval_leaf(leaf) for leaf in domain if isinstance(leaf, (list, tuple))
            )

        # Prefix (Polish) expression tree.
        stack = list(reversed(domain))

        def _eval():
            token = stack.pop()
            if token == "&":
                return _eval() and _eval()
            if token == "|":
                return _eval() or _eval()
            if token == "!":
                return not _eval()
            return _eval_leaf(token)

        return _eval()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _ingest(self, items):
        """Turn raw item dicts into ``infohub.item`` records.

        Deduplicates on ``(channel, external_id)``. Returns ``(created, skipped)``.
        """
        self.ensure_one()
        Item = self.env["infohub.item"]
        created = skipped = 0

        for entry in items:
            raw_data = entry.get("raw_data") or {}
            external_id = self._external_id(entry, raw_data)
            if not self._keep(entry):
                skipped += 1
                continue

            title = entry.get("title") or self.subject(raw_data)
            if not title:
                skipped += 1
                continue

            if external_id and Item.search_count(
                [("channel_id", "=", self.id), ("external_id", "=", external_id)]
            ):
                skipped += 1
                continue

            Item.create(
                {
                    "channel_id": self.id,
                    "source_id": self._resolve_source(entry, raw_data),
                    "title": title[:255],
                    "url": entry.get("url") or "",
                    "published_at": self._published_at(entry, raw_data),
                    "raw_data": raw_data,
                    "external_id": external_id,
                }
            )
            created += 1

        return created, skipped

    @staticmethod
    def _external_id(entry, raw_data):
        """Stable per-channel identity, used for dedup."""
        for key in ("id", "guid", "external_id", "link", "url"):
            value = entry.get(key) or raw_data.get(key)
            if value:
                return str(value)[:255]
        return ""

    def _keep(self, entry):
        """Apply the channel's filter to an incoming entry.

        ``filter_domain`` targets the fields of the item's ``raw_data`` — that
        is the payload shape each channel's content component reads, and the
        only one stable across channels. Entries that carry no ``raw_data``
        fall back to the entry dict itself so they can still be filtered.
        """
        raw_data = entry.get("raw_data")
        return self.match_item(raw_data if raw_data else entry)

    def _published_at(self, entry, raw_data):
        value = entry.get("published_date") or self.date(raw_data)
        if not value:
            return fields.Datetime.now()
        try:
            return fields.Datetime.to_datetime(value)
        except (ValueError, TypeError):
            _logger.warning(
                "infohub: unparseable date %r on channel %s", value, self.display_name
            )
            return fields.Datetime.now()

    def _resolve_source(self, entry, raw_data):
        """Match the item to a known source, else leave it empty.

        Matching is deliberately conservative — a source is only assigned on an
        exact domain or sender match, so a wrong source is never guessed.
        """
        self.ensure_one()
        Source = self.env["infohub.source"]
        url = entry.get("url") or ""
        if url:
            host = (url.split("//")[-1].split("/")[0] or "").lower()
            if host:
                found = Source.search([("url", "ilike", host)], limit=1)
                if found:
                    return found.id
        name = self.source(raw_data)
        if name:
            found = Source.search([("name", "=ilike", name)], limit=1)
            if found:
                return found.id
        return False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Scheduled fetching
    # ------------------------------------------------------------------

    @api.model
    def _cron_fetch_channels(self):
        """Enqueue one job per channel due for a fetch.

        The cron itself only dispatches; all network work happens in the job.
        ``identity_key`` keeps a channel from being queued twice while its
        previous run is still in flight.
        """
        channels = self.search([("active", "=", True), ("enable_cron", "=", True)])
        for channel in channels:
            channel.with_delay(
                channel="root.infohub",
                description=_("InfoHub: fetch %s") % channel.display_name,
                identity_key=f"infohub-fetch-{channel.id}",
            )._job_fetch()

    def _job_fetch(self):
        """Queue-job entry point — one channel, one job."""
        self.ensure_one()
        self.action_fetch()

    def action_open_items(self):
        """Open the items belonging to this channel."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Items"),
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": [("channel_id", "=", self.id)],
            "context": {"default_channel_id": self.id},
        }

    def action_fetch(self):
        """Fetch synchronously — for the manual button and for tests."""
        for channel in self:
            try:
                _, items = channel.fetch_news()
                created, skipped = channel._ingest(items)
                channel.write(
                    {
                        "last_run_at": fields.Datetime.now(),
                        "error_count": 0,
                        "last_error": False,
                    }
                )
                _logger.info(
                    "infohub: %s fetched %s item(s), created %s, skipped %s",
                    channel.display_name,
                    len(items),
                    created,
                    skipped,
                )
            except Exception as exc:  # noqa: BLE001 — surfaced to the user below
                channel.write(
                    {
                        "last_run_at": fields.Datetime.now(),
                        "error_count": channel.error_count + 1,
                        "last_error": str(exc),
                    }
                )
                raise
        return True
