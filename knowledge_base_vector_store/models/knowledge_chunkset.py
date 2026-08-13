# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""One chunking configuration of a knowledge base.

A KB may have several chunksets (different splitters/sizes); each chunkset
may in turn feed several vector stores (different embedding models), so one
KB can be compared across configurations.
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class KnowledgeChunkset(models.Model):
    _name = "knowledge.chunkset"
    _description = "Knowledge Chunking Configuration"
    _inherit = ["mail.thread"]

    kb_id = fields.Many2one(
        comodel_name="knowledge.base",
        string="Knowledge Base",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char(required=True)
    splitter_id = fields.Many2one(
        comodel_name="knowledge.splitter",
        string="Splitter",
        required=True,
        ondelete="restrict",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("chunking", "Chunking"),
            ("chunked", "Chunked"),
            ("error", "Error"),
        ],
        default="draft",
        tracking=True,
    )
    chunk_ids = fields.One2many(
        comodel_name="knowledge.chunk",
        inverse_name="chunkset_id",
        string="Chunks",
    )
    chunk_count = fields.Integer(compute="_compute_chunk_count")
    vector_ids = fields.One2many(
        comodel_name="knowledge.vector",
        inverse_name="chunkset_id",
        string="Vector Stores",
    )

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for chunkset in self:
            chunkset.chunk_count = len(chunkset.chunk_ids)

    @api.constrains("kb_id", "splitter_id")
    def _check_kb_scope(self):
        for chunkset in self:
            if not chunkset.kb_id.source_ids:
                raise ValidationError(
                    _(
                        "Knowledge base '%s' has no sources yet. "
                        "Define its scope before chunking.",
                        chunkset.kb_id.name,
                    )
                )

    # ------------------------------------------------------------------
    # Chunking workflow
    # ------------------------------------------------------------------
    def action_chunk(self):
        """Enqueue one chunking job per source of the KB (async)."""
        for chunkset in self:
            if chunkset.state == "chunking":
                continue
            chunkset.write({"state": "chunking"})
            for source in chunkset.kb_id.source_ids:
                source.with_delay(
                    channel="root.knowledge",
                    description=_("Chunk %s") % source.display_name,
                )._chunk(chunkset.id)
        return True

    def _chunk_all(self):
        """Synchronous chunking, used by tests and scripts."""
        for chunkset in self:
            chunkset.write({"state": "chunking"})
            for source in chunkset.kb_id.source_ids:
                chunkset._chunk_source(source)
            chunkset._refresh_state()

    def _chunk_source(self, source):
        """Chunk one source into this chunkset. Queue job body."""
        self.ensure_one()
        adapter = self.splitter_id._get_adapter()
        if adapter is None:
            self.write({"state": "error"})
            return
        backend = self.kb_id.md_backend_id
        content_path = "%s/content.%s" % (
            source.id,
            source.output_format or "md",
        )
        try:
            with backend.open(content_path, "rb") as stream:
                raw = stream.read()
        except Exception:  # noqa: BLE001
            _logger.warning("No extracted content at %s, skipping", content_path)
            return
        text = self._source_to_text(raw, source.output_format or "md")
        parts = adapter.split(text)
        self._clear_source_chunks(source)
        for index, part in enumerate(parts, start=1):
            path = "%s/chunks/%s/%s.md" % (source.id, self.id, index)
            data = part.encode("utf-8")
            with backend.open(path, "wb") as stream:
                stream.write(data)
            self.env["knowledge.chunk"].create(
                {
                    "chunkset_id": self.id,
                    "source_id": source.id,
                    "sequence": index,
                    "file_size": len(data),
                }
            )
        self._refresh_state()

    @staticmethod
    def _source_to_text(raw, fmt):
        if fmt == "json":
            try:
                return json.dumps(
                    json.loads(raw.decode("utf-8")),
                    ensure_ascii=False,
                    default=str,
                )
            except (ValueError, UnicodeDecodeError):
                return raw.decode("utf-8", errors="replace")
        return raw.decode("utf-8", errors="replace")

    def _clear_source_chunks(self, source):
        """Remove old chunk metadata and stale files for this source."""
        dir_path = "%s/chunks/%s" % (source.id, self.id)
        stale = self.env["knowledge.chunk"].search(
            [("chunkset_id", "=", self.id), ("source_id", "=", source.id)]
        )
        stale.unlink()
        try:
            backend = self.kb_id.md_backend_id
            for name in backend.list_files(dir_path):
                backend.delete("%s/%s" % (dir_path, name))
        except Exception:  # noqa: BLE001
            _logger.warning("Could not clear chunk dir %s", dir_path)

    def _refresh_state(self):
        for chunkset in self:
            if chunkset.kb_id.source_ids and not chunkset.chunk_ids:
                chunkset.state = "error"
            else:
                chunkset.state = "chunked"
        self.kb_id._refresh_state()

    def action_rechunk(self):
        """Restart chunking (clears existing chunks first)."""
        return self.action_chunk()
