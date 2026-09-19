import json
import logging

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

TAGGER_CODE = "infohub_tagger"
TAGGING_BATCH_SIZE = 20
TAGGING_MAX_JOBS_PER_RUN = 10


class InfohubItem(models.Model):
    _inherit = "infohub.item"

    tag_ids = fields.Many2many(
        "infohub.tag",
        "infohub_item_tag_rel",
        "item_id",
        "tag_id",
        string="Tags",
    )
    tagging_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("queued", "Queued"),
            ("done", "Tagged"),
            ("skipped", "No Tags"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    tagging_error = fields.Text()

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    @api.model
    def _cron_enqueue_tagging(self):
        """Dispatch-only cron: claim pending items and enqueue batch jobs.

        Stays a no-op while the taxonomy is empty or the tagger agent is not
        configured. Items keep ``pending`` in that case, so configuring the
        taxonomy later back-fills the pool.
        """
        tags = self.env["infohub.tag"].search([])
        if not tags:
            return
        agent = self.env["llm.agent"].sudo().search([("code", "=", TAGGER_CODE)])
        if not (len(agent) == 1 and agent.active and agent.provider_id and agent.model_id):
            return

        items = self.search(
            [("tagging_state", "=", "pending")],
            order="id",
            limit=TAGGING_BATCH_SIZE * TAGGING_MAX_JOBS_PER_RUN,
        )
        for batch in range(0, len(items), TAGGING_BATCH_SIZE):
            chunk = items[batch : batch + TAGGING_BATCH_SIZE]
            chunk.write({"tagging_state": "queued"})
            chunk.with_delay(
                channel="root.infohub",
                description=_("InfoHub: tag %s item(s)") % len(chunk),
                identity_key=f"infohub-tagging-{chunk.ids[0]}",
            )._job_tag_items()

    # ------------------------------------------------------------------
    # Batch tagging job
    # ------------------------------------------------------------------

    def _job_tag_items(self):
        """Queue-job entry point: tag one claimed batch of items."""
        batch = self.exists().filtered(lambda i: i.tagging_state == "queued")
        if not batch:
            return

        tags = self.env["infohub.tag"].search([])
        agent = self.env["llm.agent"].sudo().search([("code", "=", TAGGER_CODE)])
        if not tags or not (len(agent) == 1 and agent.active):
            batch.write({"tagging_state": "pending"})
            return

        query = batch._build_tagging_query(tags)
        result = agent.invoke(query, new_cursor=False)
        if result.get("error"):
            batch.write({"tagging_state": "error", "tagging_error": result["error"]})
            return

        try:
            assigned = batch._parse_tagging_response(result.get("result") or "", tags)
        except ValueError as exc:
            batch.write({"tagging_state": "error", "tagging_error": str(exc)})
            return

        for item in batch:
            tag_ids = assigned.get(item.id, [])
            item.write(
                {
                    "tag_ids": [(6, 0, tag_ids)] if tag_ids else [(5, 0, 0)],
                    "tagging_state": "done" if tag_ids else "skipped",
                    "tagging_error": False,
                }
            )

    def _build_tagging_query(self, tags):
        """Build the user message: taxonomy plus item titles, nothing else.

        Bodies are deliberately left out — for classification the headline
        carries the signal and the payload stays a fraction of the size.
        """
        lines = ["Taxonomy:"]
        for tag in tags:
            use_when = tag.description or tag.name
            lines.append(f"- code: {tag.code} | name: {tag.name} | use when: {use_when}")
        lines.append("")
        lines.append("Items:")
        for item in self:
            lines.append(f"[id {item.id}] {item.title}")
        lines.append("")
        lines.append("Tag these items.")
        return "\n".join(lines)

    @api.model
    def _parse_tagging_response(self, raw, tags):
        """Extract ``{item_id: [tag_id]}`` from the model's answer.

        Raises ``ValueError`` when no JSON object can be recovered. Unknown
        tag codes and unknown item ids are dropped: the model can only ever
        select from the taxonomy it was given.
        """
        text = (raw or "").strip()
        if text.startswith("<"):
            text = html2plaintext(text)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(_("No JSON object found in the tagging answer."))
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(_("Invalid JSON in the tagging answer: %s") % exc) from exc

        entries = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ValueError(_("Tagging answer is not a list of results."))

        by_code = {tag.code.lower(): tag.id for tag in tags}
        assigned = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get("id")
            if not isinstance(item_id, int):
                continue
            codes = entry.get("tags") or []
            if not isinstance(codes, list):
                continue
            tag_ids = []
            for code in codes:
                tag_id = by_code.get(str(code).lower())
                if tag_id:
                    tag_ids.append(tag_id)
                else:
                    _logger.info("infohub tagging: dropping unknown tag code %r", code)
            assigned[item_id] = tag_ids
        return assigned

    def action_requeue_tagging(self):
        """Reset items to pending so the next cron pass tags them again."""
        self.write({"tagging_state": "pending", "tagging_error": False})
