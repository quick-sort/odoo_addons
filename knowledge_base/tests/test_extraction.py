# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import json
from unittest import mock

from odoo.exceptions import ValidationError

from odoo.addons.knowledge_base.models.knowledge_source import KnowledgeSource

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
    def _stub_extractor(self, output, fmt="md", err=None):
        """Patch ``_get_extractor`` to return an in-memory stub extractor.

        No concrete extractor addon is installed in this test DB, so we replace
        the extractor lookup rather than create a ``knowledge.extractor`` record
        (whose ``extractor_type`` selection is empty without one). The stub
        returns an adapter that produces ``output`` (or raises ``err``).
        """

        class StubAdapter:
            _output_format = fmt

            def extract(self, source):
                if err:
                    raise err
                return output

        class StubExtractor:
            def _get_adapter(self):
                return StubAdapter()

            def _get_output_format(self):
                return StubAdapter()._output_format

        patcher = mock.patch.object(
            KnowledgeSource, "_get_extractor", lambda self: StubExtractor()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create_extracted_kb(self, filename, content, output, fmt="md", err=None):
        """KB with one file source and a stubbed extractor, ready to extract."""
        kb = self._create_kb()
        self._write_entry(filename, content)
        entry = self.env["one.storage.entry"].search(
            [("name", "=", filename)], limit=1
        )
        self.env["knowledge.source"].create(
            {"kb_id": kb.id, "source_type": "file", "entry_id": entry.id}
        )
        self._stub_extractor(output, fmt=fmt, err=err)
        return kb

    def test_extract_md(self):
        kb = self._create_extracted_kb(
            "readme.md", "# Hello\n\nSome content.", "# Hello from extractor"
        )
        kb._extract_all()
        source = kb.source_ids
        self.assertEqual(source.state, "extracted")
        self.assertEqual(kb.state, "extracted")
        self.assertEqual(
            self._read_backend(source.content_path),
            "# Hello from extractor",
        )

    def test_extract_json(self):
        structured = {"blocks": [{"type": "text", "content": "hi"}]}
        kb = self._create_extracted_kb(
            "report.pdf", b"PDF bytes", structured, fmt="json"
        )
        kb._extract_all()
        source = kb.source_ids
        self.assertEqual(source.output_format, "json")
        self.assertTrue(source.content_path.endswith("content.json"))
        self.assertEqual(
            json.loads(self._read_backend(source.content_path)), structured
        )

    def test_extract_error_marks_error_state(self):
        kb = self._create_extracted_kb(
            "broken.docx", b"broken", None, err=RuntimeError("boom")
        )
        kb._extract_all()
        self.assertEqual(kb.source_ids.state, "error")
        self.assertEqual(kb.state, "error")
