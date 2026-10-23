import json
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.addons.component.core import WorkContext

_logger = logging.getLogger(__name__)

# A domain-looking token: ``nature.com``, ``www.nature.com``, ``a.b.co.uk``.
# Deliberately not a full URL/address parser — it is only used to reduce two
# free-form strings to what they can meaningfully share.
_DOMAIN_RE = re.compile(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}")


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
    fetch_interval_minutes = fields.Integer(
        string="Fetch Interval (Minutes)",
        default=15,
        help="Between-fetch gap. The dispatcher cron still runs every 15 min "
        "and only enqueues channels whose last_run_at is older than this.",
    )

    filter_domain = fields.Json(
        help="Optional Odoo-style domain evaluated against each raw item dict "
        "before it is stored. Only matching items are kept. "
        'Example: [["source", "ilike", "Reuters"]]',
    )

    item_ids = fields.One2many("infohub.item", "channel_id", string="Items")
    item_count = fields.Integer(compute="_compute_item_count")
    last_run_at = fields.Datetime(readonly=True)
    next_run_at = fields.Datetime(
        string="Next Fetch",
        compute="_compute_next_run_at",
        help="When this channel becomes due again. The dispatcher cron runs "
        "every 15 minutes and fetches it on the first tick after this time.",
    )
    error_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.depends("item_ids")
    def _compute_item_count(self):
        for channel in self:
            channel.item_count = len(channel.item_ids)

    @api.depends("enable_cron", "last_run_at", "fetch_interval_minutes")
    def _compute_next_run_at(self):
        for channel in self:
            # No schedule, or never run: the dispatcher fetches a never-run
            # channel on its next tick, so there is no meaningful timestamp
            # to show yet.
            if channel.enable_cron and channel.last_run_at:
                channel.next_run_at = channel.last_run_at + timedelta(
                    minutes=channel.fetch_interval_minutes
                )
            else:
                channel.next_run_at = False

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

    def url(self, raw_data):
        """A link to the original item, as carried in the raw item."""
        self.ensure_one()
        return self._component("infohub.content").url(raw_data)

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
            # A channel may hand back its payload either nested under
            # ``raw_data`` or spread across the entry dict itself (the RSS
            # parser does the latter). Normalise so the content component always
            # sees the channel's real payload shape.
            raw_data = entry.get("raw_data") or entry
            external_id = self._external_id(entry, raw_data)
            if not self._keep(entry):
                skipped += 1
                continue

            title = entry.get("title") or self.subject(raw_data)
            if not title:
                skipped += 1
                continue

            # The link lives in each channel's own payload shape, so it is read
            # through the content component rather than off the entry dict.
            url = entry.get("url") or self.url(raw_data) or ""

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
                    "url": url,
                    "content": entry.get("content") or self._content_html(raw_data),
                    "published_at": self._published_at(entry, raw_data),
                    "raw_data": raw_data,
                    "external_id": external_id,
                }
            )
            created += 1

        return created, skipped

    def _content_html(self, raw_data):
        """Render the item body as HTML via the channel's content component.

        ``infohub.item.content`` is an HTML field (sanitised on write), while
        ``build_content`` returns readable plain text — every channel's payload
        shape differs, and that method is where the knowledge of it lives. The
        text is escaped and paragraph breaks preserved so it renders as
        intended instead of collapsing to one line.
        """
        from odoo.tools import html_escape

        text = self.build_content(raw_data)
        if not text:
            return False
        paragraphs = [
            f"<p>{html_escape(block)}</p>"
            for block in text.split("\n\n")
            if block.strip()
        ]
        return "".join(paragraphs)

    @staticmethod
    def _external_id(entry, raw_data):
        """Stable per-channel identity, used for dedup.

        ``identifier`` outranks ``guid``/``link``: publishers that translate a
        release give every language its own URL but keep the release number, so
        the URL is not an identity. Atom's ``<id>`` stays first — it is already
        language-neutral. Repeated tags are collected as lists by the RSS
        parser; the first value is the identity, and a list must never be
        stringified into the key.
        """
        for key in ("id", "identifier", "guid", "external_id", "link", "url"):
            value = entry.get(key) or raw_data.get(key)
            if isinstance(value, (list, tuple)):
                value = next((item for item in value if item), "")
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

        Three steps, narrowest first: the source's ``url`` domain, then its
        ``name``, then the domains named in its ``description``. Matching is
        deliberately conservative — every step compares whole domains or whole
        names, never loose substrings — so a wrong source is never guessed.
        """
        self.ensure_one()
        Source = self.env["infohub.source"]
        # Every channel keeps the link inside its own payload — RSS under
        # ``link``, BioMedTracker under ``SOURCELINK`` — and only the MCP
        # channel also puts it on the entry dict itself. Reading ``entry["url"]``
        # alone therefore never matched for the other channels, so fall back to
        # the channel's own reader: the same one ``_ingest`` uses for the item's
        # ``url``.
        url = entry.get("url") or self.url(raw_data) or ""
        host = ""
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
        # Last resort: ``description``, documented on the model as the
        # free-form recognition clue — the publisher's domain, or the address
        # its newsletter is sent from. An inbound newsletter is the case that
        # needs it: it carries no item link, and ``source()`` returns the whole
        # ``Name <address@domain>`` sender, which never equals a source's
        # ``name``. Both sides are reduced to domains so that a clue of
        # ``fiercepharma.com`` matches ``news@fiercepharma.com`` without also
        # matching an unrelated ``notfiercepharma.com``.
        domains = self._domains_of(host) | self._domains_of(name)
        if domains:
            for source in Source.search([("description", "!=", False)]):
                clues = self._domains_of(source.description)
                if any(
                    domain == clue or domain.endswith("." + clue)
                    for domain in domains
                    for clue in clues
                ):
                    return source.id
        return False

    @staticmethod
    def _domains_of(value):
        """Every domain-looking token in ``value``, lower-cased.

        Applied to both sides of the ``description`` match: a clue may be a
        bare domain or a full address (``newsletters@nature.com``), and the item
        side may be a link host or a sender (``Fierce Pharma
        <news@fiercepharma.com>``). Reducing both leaves only what the two can
        meaningfully share, and values without a dot — feed titles, free-text
        notes — yield nothing, so they never match by accident.
        """
        return {match.rstrip(".") for match in _DOMAIN_RE.findall((value or "").lower())}

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
        now = fields.Datetime.now()
        channels = self.search([("active", "=", True), ("enable_cron", "=", True)])
        due = channels.filtered(
            lambda c: not c.last_run_at
            or c.last_run_at <= now - timedelta(minutes=c.fetch_interval_minutes)
        )
        for channel in due:
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
        """Fetch synchronously — for the manual button and for tests.

        Returns a notification action so a manual fetch says what happened
        instead of silently reloading; ``next`` refreshes the form so
        ``last_run_at`` / ``error_count`` reflect the run too.
        """
        fetched = created = skipped = 0
        for channel in self:
            try:
                # Not ``_``: that would shadow the translation function for
                # the whole method, and the notification below calls it.
                _payload, items = channel.fetch_news()
                channel_created, channel_skipped = channel._ingest(items)
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
                    channel_created,
                    channel_skipped,
                )
                fetched += len(items)
                created += channel_created
                skipped += channel_skipped
            except Exception as exc:  # noqa: BLE001 — surfaced to the user below
                channel._register_failure(exc)
                raise
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _(
                    "Fetched %(fetched)s item(s): %(created)s new, "
                    "%(skipped)s duplicate(s).",
                    fetched=fetched,
                    created=created,
                    skipped=skipped,
                ),
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _register_failure(self, exc):
        """Record a failed run so the counters survive a rollback.

        Writing in the caller's transaction would be pointless in production:
        a queue_job failure rolls that transaction back, taking the counter and
        the message with it, so ``error_count`` would stay at 0 forever and the
        auto-disable would never trip. Odoo's test ``assertRaises`` rolls back
        the same way, which is how this was caught.

        The write happens on a fresh cursor, which commits on clean exit and is
        closed either way. The row must already exist there; a channel created
        but not yet committed by the caller simply cannot be updated this way,
        and is skipped rather than raising.
        """
        self.ensure_one()
        values = {
            "last_run_at": fields.Datetime.now(),
            "error_count": self.error_count + 1,
            "last_error": str(exc),
        }
        channel_id = self.id
        try:
            with self.pool.cursor() as cr:
                channel = self.env["infohub.channel"].with_env(self.env(cr=cr)).browse(
                    channel_id
                )
                if channel.exists():
                    channel.write(values)
        except Exception:  # noqa: BLE001 — bookkeeping must never mask the cause
            _logger.exception(
                "infohub: could not record fetch failure for channel %s", channel_id
            )
        self.invalidate_recordset()
