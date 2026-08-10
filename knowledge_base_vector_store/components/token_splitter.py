# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Token-based splitter: splits on whitespace and groups ``chunk_size``
whitespace tokens per chunk, with ``chunk_overlap`` tokens shared between
consecutive chunks.
"""

from odoo.addons.component.core import Component


class TokenSplitter(Component):
    _name = "token.splitter"
    _inherit = "knowledge.splitter.component"
    _usage = "token"

    def split(self, text):
        tokens = text.split()
        chunk_size = self.collection.chunk_size
        chunk_overlap = self.collection.chunk_overlap
        step = max(1, chunk_size - chunk_overlap)
        chunks = []
        for start in range(0, len(tokens), step):
            chunk = " ".join(tokens[start : start + chunk_size])
            if chunk:
                chunks.append(chunk)
            if start + chunk_size >= len(tokens):
                break
        return chunks or ([""] if text == "" else [text])
