import os
import shutil

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.component.tests.common import TransactionComponentCase


@tagged("post_install", "-at_install")
class TestCollectionStorageScan(TransactionComponentCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp_name = "llm_kb_scan_test_%s" % os.getpid()
        cls.backend = cls.env["storage.backend"].create(
            {
                "name": "Scan Test",
                "backend_type": "filesystem",
                "directory_path": cls.tmp_name,
            }
        )
        cls.tmpdir = os.path.join(
            cls.backend._get_adapter()._basedir(), cls.tmp_name
        )
        cls.collection = cls.env["llm.knowledge.collection"].create(
            {
                "name": "Scan KB",
                "source_backend_id": cls.backend.id,
            }
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        # Filesystem writes are not transactional: start each test with a
        # clean backend directory.
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        os.makedirs(self.tmpdir)

    def _write(self, relpath, data=b"hello"):
        full = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        return full

    def _file_resources(self):
        # Scoped to this class's backend so demo data never interferes.
        return self.env["llm.resource"].search(
            [
                ("source_type", "=", "file"),
                ("source_backend_id", "=", self.backend.id),
            ]
        )

    def test_scan_creates_draft_resources(self):
        self._write("doc.md", b"# Title")
        self._write("notes/deep.txt", b"nested")
        self.collection.scan_storage()

        resources = self._file_resources()
        self.assertEqual(len(resources), 2)
        by_path = {r.source_path: r for r in resources}
        self.assertIn("doc.md", by_path)
        self.assertIn("notes/deep.txt", by_path)
        # No extractor installed: extraction posts an error message and the
        # resource stays draft.
        self.assertEqual(by_path["doc.md"].state, "draft")
        self.assertIn(self.collection, by_path["doc.md"].collection_ids)

    def test_rescan_links_existing_without_duplicates(self):
        self._write("doc.md")
        self.collection.scan_storage()
        resource = self._file_resources()

        other = self.env["llm.knowledge.collection"].create(
            {
                "name": "Other KB",
                "source_backend_id": self.backend.id,
            }
        )
        other.scan_storage()
        self.collection.scan_storage()

        self.assertEqual(len(self._file_resources()), 1)
        self.assertEqual(len(resource.collection_ids), 2)

    def test_gone_file_flagged_and_reappearance_clears_flag(self):
        path = self._write("doc.md")
        self.collection.scan_storage()
        resource = self._file_resources()
        self.assertFalse(resource.to_delete)

        os.remove(path)
        self.collection.scan_storage()
        self.assertTrue(resource.to_delete)

        self._write("doc.md", b"back again")
        self.collection.scan_storage()
        self.assertFalse(resource.to_delete)

    def test_source_path_limits_scan_and_gone_detection(self):
        self.collection.source_path = "docs"
        self._write("docs/inside.md")
        self._write("outside.md")
        self.collection.scan_storage()

        resources = self._file_resources()
        self.assertEqual(resources.mapped("source_path"), ["docs/inside.md"])

        # Removing the whole scanned subtree flags only resources under the
        # source path; the sibling stays untouched (and unscanned).
        shutil.rmtree(os.path.join(self.tmpdir, "docs"))
        self.collection.scan_storage()
        self.assertTrue(resources.to_delete)

    def test_upload_wizard_requires_source_backend(self):
        wizard = self.env["llm.upload.resource.wizard"].create(
            {
                "collection_id": self.collection.id,
                "external_urls": "https://example.com/article",
            }
        )
        wizard.action_upload_resources()
        url_resource = self.env["llm.resource"].search(
            [
                ("source_type", "=", "url"),
                ("create_uid", "!=", False),
                ("id", "not in", self.env.ref(
                    "llm_knowledge.llm_resource_url_demo",
                    raise_if_not_found=False,
                ).ids),
            ]
        )
        self.assertEqual(
            len(url_resource), 1,
            "expected exactly the wizard's URL resource",
        )

        backendless = self.env["llm.knowledge.collection"].create(
            {"name": "No Backend KB"}
        )
        attachment = self.env["ir.attachment"].create(
            {"name": "file.txt", "datas": b"aGVsbG8="}
        )
        wizard = self.env["llm.upload.resource.wizard"].create(
            {
                "collection_id": backendless.id,
                "file_ids": [(4, attachment.id)],
            }
        )
        with self.assertRaises(UserError):
            wizard._process_file_uploads(backendless)

    def test_upload_wizard_writes_to_source_backend(self):
        attachment = self.env["ir.attachment"].create(
            {"name": "notes.txt", "datas": b"aGVsbG8="}
        )
        wizard = self.env["llm.upload.resource.wizard"].create(
            {
                "collection_id": self.collection.id,
                "file_ids": [(4, attachment.id)],
            }
        )
        wizard.action_upload_resources()

        resources = self._file_resources()
        self.assertEqual(len(resources), 1)
        resource = resources[0]
        self.assertTrue(resource.source_backend_id.file_exists(resource.source_path))
        self.assertEqual(resource._read_source_bytes(), b"hello")
