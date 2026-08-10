# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import os
import shutil

from odoo.addons.component.tests.common import TransactionComponentCase


class KnowledgeBaseCase(TransactionComponentCase):
    """Shared setup: a filesystem storage backend + a one_storage tree.

    Extraction writes to the same backend the test owns, so assertions read
    files directly from the filestore on disk.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp_name = "knowledge_base_test_%s" % os.getpid()
        cls.md_backend = cls.env["storage.backend"].create(
            {
                "name": "Test MD Backend",
                "backend_type": "filesystem",
                "directory_path": cls.tmp_name,
            }
        )
        base_dir = cls.md_backend._get_adapter()._basedir()
        cls.tmpdir = os.path.join(base_dir, cls.tmp_name)
        # A single global root is enforced; clear any seeded root so the test
        # owns the tree and binds it to the test backend.
        cls.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        cls.root_folder = cls.env["one.storage.entry"].create(
            {"name": "root", "entry_type": "directory", "backend_id": cls.md_backend.id}
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def _write_entry(self, name, content, directory=None):
        """Create a file entry with real bytes on the test backend."""
        parent = directory or self.root_folder
        entry = self.env["one.storage.entry"].create(
            {
                "name": name,
                "entry_type": "file",
                "parent_id": parent.id,
            }
        )
        entry.set_content(content, binary=False if isinstance(content, str) else True)
        return entry

    def _create_extractor(self, extractor_type="markitdown", **kw):
        return self.env["knowledge.extractor"].create(
            {"name": "Test Extractor", "extractor_type": extractor_type, **kw}
        )

    def _create_kb(self, **kw):
        vals = {
            "name": "Test KB",
            "md_backend_id": self.md_backend.id,
        }
        vals.update(kw)
        return self.env["knowledge.base"].create(vals)

    def _read_backend(self, path):
        return self.md_backend.get(path).decode("utf-8")
