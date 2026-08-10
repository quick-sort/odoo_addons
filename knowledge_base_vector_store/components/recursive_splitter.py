# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Recursive character splitter (LangChain-style).

Splits on progressively finer separators (blank lines, newlines, spaces,
chars) so semantic units stay intact as long as they fit within
``chunk_size``. Consecutive chunks share ``chunk_overlap`` characters.
"""

from odoo.addons.component.core import Component

_SEPARATORS = ["\n\n", "\n", " ", ""]


class RecursiveSplitter(Component):
    _name = "recursive.splitter"
    _inherit = "knowledge.splitter.component"
    _usage = "recursive"

    def split(self, text):
        return self._split(text, list(_SEPARATORS))

    @staticmethod
    def _first_separator(text, separators):
        for sep in separators:
            if sep in text:
                return sep
        return ""

    def _split(self, text, separators):
        chunk_size = self.collection.chunk_size
        chunk_overlap = self.collection.chunk_overlap
        sep = self._first_separator(text, separators)
        new_separators = separators[separators.index(sep) + 1 :]
        pieces = text.split(sep) if sep else list(text)
        chunks = []
        current = ""
        for piece in pieces:
            if len(piece) > chunk_size and new_separators:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split(piece, new_separators))
                continue
            separator = sep if current else ""
            if len(current) + len(separator) + len(piece) <= chunk_size:
                current = current + separator + piece
            else:
                if current:
                    chunks.append(current)
                tail = current[-chunk_overlap:].lstrip() if chunk_overlap else ""
                if tail:
                    candidate = tail + sep + piece
                    if len(candidate) <= chunk_size:
                        current = candidate
                    else:
                        chunks.append(tail)
                        current = piece
                else:
                    current = piece
        if current:
            chunks.append(current)
        return [chunk for chunk in chunks if chunk]
