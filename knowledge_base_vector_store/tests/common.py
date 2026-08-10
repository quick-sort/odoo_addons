# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import os
import shutil

from odoo.addons.component.tests.common import TransactionComponentCase


class KnowledgeVectorCase(TransactionComponentCase):
    """Shared setup for chunking/vectorization tests.

    Builds a storage backend + one_storage tree, an extractor (markitdown),
    and a KB with one extracted source, so chunking tests can start from a
    ready ``content.md``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp_name = "kvs_test_%s" % os.getpid()
        cls.md_backend = cls.env["storage.backend"].create(
            {
                "name": "Test MD Backend",
                "backend_type": "filesystem",
                "directory_path": cls.tmp_name,
            }
        )
        base_dir = cls.md_backend._get_adapter()._basedir()
        cls.tmpdir = os.path.join(base_dir, cls.tmp_name)
        cls.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        cls.root_folder = cls.env["one.storage.entry"].create(
            {
                "name": "root",
                "entry_type": "directory",
                "backend_id": cls.md_backend.id,
            }
        )
        cls.extractor = cls.env["knowledge.extractor"].create(
            {"name": "Test Extractor", "extractor_type": "markitdown"}
        )
        cls.kb = cls.env["knowledge.base"].create(
            {
                "name": "Test KB",
                "md_backend_id": cls.md_backend.id,
                "extractor_id": cls.extractor.id,
            }
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def _write_entry(self, name, content, directory=None):
        parent = directory or self.root_folder
        entry = self.env["one.storage.entry"].create(
            {"name": name, "entry_type": "file", "parent_id": parent.id}
        )
        entry.set_content(content, binary=False if isinstance(content, str) else True)
        return entry

    def _add_file_source(self, name, content):
        entry = self._write_entry(name, content)
        return self.env["knowledge.source"].create(
            {"kb_id": self.kb.id, "source_type": "file", "entry_id": entry.id}
        )

    def _seed_extracted(self, content):
        """Add a source and write its content.md directly to the backend."""
        source = self._add_file_source("doc.md", content)
        source.write({"state": "extracted"})
        self.md_backend.add(
            "%s/content.md" % source.id,
            content.encode("utf-8"),
        )
        return source

    def _create_splitter(self, splitter_type="recursive", chunk_size=500, overlap=50):
        return self.env["knowledge.splitter"].create(
            {
                "name": "Test Splitter",
                "splitter_type": splitter_type,
                "chunk_size": chunk_size,
                "chunk_overlap": overlap,
            }
        )

    def _create_chunkset(self, splitter=None, kb=None):
        return self.env["knowledge.chunkset"].create(
            {
                "kb_id": (kb or self.kb).id,
                "name": "Test Chunkset",
                "splitter_id": (splitter or self._create_splitter()).id,
            }
        )
