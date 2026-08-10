# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import json
import unittest

from odoo.exceptions import ValidationError

from odoo.addons.knowledge_base.models.knowledge_extractor import (
    KnowledgeExtractor,
)

from .common import KnowledgeBaseCase


class TestSourceValidation(KnowledgeBaseCase):
    def test_file_source_requires_entry(self):
        kb = self._create_kb()
        with self.assertRaises(ValidationError):
            self.env["knowledge.source"].create(
                {"kb_id": kb.id, "source_type": "file"}
            )

    def test_url_source_requires_url(self):
        kb = self._create_kb()
        with self.assertRaises(ValidationError):
            self.env["knowledge.source"].create(
                {"kb_id": kb.id, "source_type": "url"}
            )

    def test_extract_without_sources_raises(self):
        kb = self._create_kb()
        with self.assertRaises(ValidationError):
            kb.action_extract_all()

    def test_content_path(self):
        kb = self._create_kb()
        source = self.env["knowledge.source"].create(
            {"kb_id": kb.id, "source_type": "url", "url": "https://example.com"}
        )
        source.flush_recordset()
        self.assertEqual(source.content_path, "%s/content.md" % source.id)


class TestExtractionFlow(KnowledgeBaseCase):
    def _stub_adapter(self, output, fmt="md", err=None):
        """Return a patch object replacing _get_adapter with a stub."""
        from unittest import mock

        class StubAdapter:
            _output_format = fmt

            def extract(self, source):
                if err:
                    raise err
                return output

        return mock.patch.object(
            KnowledgeExtractor,
            "_get_adapter",
            lambda self: StubAdapter(),
        )

    def test_extract_md(self):
        kb = self._create_kb()
        self._write_entry("readme.md", "# Hello\n\nSome content.")
        entry = self.env["one.storage.entry"].search(
            [("name", "=", "readme.md")], limit=1
        )
        self.env["knowledge.source"].create(
            {"kb_id": kb.id, "source_type": "file", "entry_id": entry.id}
        )
        with self._stub_adapter("# Hello from extractor"):
            kb._extract_all()
        source = kb.source_ids
        self.assertEqual(source.state, "extracted")
        self.assertEqual(kb.state, "extracted")
        self.assertEqual(
            self._read_backend(source.content_path),
            "# Hello from extractor",
        )

    def test_extract_json(self):
        kb = self._create_kb()
        self._write_entry("report.pdf", b"PDF bytes")
        entry = self.env["one.storage.entry"].search(
            [("name", "=", "report.pdf")], limit=1
        )
        self.env["knowledge.source"].create(
            {"kb_id": kb.id, "source_type": "file", "entry_id": entry.id}
        )
        structured = {"blocks": [{"type": "text", "content": "hi"}]}
        with self._stub_adapter(structured, fmt="json"):
            kb._extract_all()
        source = kb.source_ids
        self.assertEqual(source.output_format, "json")
        self.assertTrue(source.content_path.endswith("content.json"))
        self.assertEqual(
            json.loads(self._read_backend(source.content_path)), structured
        )

    def test_extract_error_marks_error_state(self):
        kb = self._create_kb()
        self._write_entry("broken.docx", b"broken")
        entry = self.env["one.storage.entry"].search(
            [("name", "=", "broken.docx")], limit=1
        )
        self.env["knowledge.source"].create(
            {"kb_id": kb.id, "source_type": "file", "entry_id": entry.id}
        )
        with self._stub_adapter(None, err=RuntimeError("boom")):
            kb._extract_all()
        self.assertEqual(kb.source_ids.state, "error")
        self.assertEqual(kb.state, "error")


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
