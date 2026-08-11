# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import unittest

from odoo.addons.knowledge_base.tests.common import KnowledgeBaseCase


@unittest.skipUnless(
    __import__("importlib").util.find_spec("markitdown"),
    "markitdown is not installed",
)
class TestMarkitdownReal(KnowledgeBaseCase):
    def test_extract_txt_file(self):
        kb = self._create_kb(extractor_id=self._create_extractor("markitdown").id)
        self._write_entry("notes.txt", "This is a plain text note.")
        entry = self.env["one.storage.entry"].search(
            [("name", "=", "notes.txt")], limit=1
        )
        self.env["knowledge.source"].create(
            {"kb_id": kb.id, "source_type": "file", "entry_id": entry.id}
        )
        kb._extract_all()
        source = kb.source_ids
        self.assertEqual(source.state, "extracted")
        self.assertIn("plain text note", self._read_backend(source.content_path))
