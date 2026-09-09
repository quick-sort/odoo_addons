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
                "cache_backend_id": cls.backend.id,
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

    def _file_documents(self):
        # Scoped to this class's backend so demo data never interferes.
        return self.env["llm.document"].search(
            [
                ("source_type", "=", "file"),
                ("source_backend_id", "=", self.backend.id),
            ]
        )

    def test_scan_creates_draft_documents(self):
        self._write("doc.md", b"# Title")
        self._write("notes/deep.txt", b"nested")
        self.collection.scan_storage()

        documents = self._file_documents()
        self.assertEqual(len(documents), 2)
        by_path = {r.source_path: r for r in documents}
        self.assertIn("doc.md", by_path)
        self.assertIn("notes/deep.txt", by_path)
        # Retrieval succeeds, then missing extractor mapping keeps the document retryable.
        self.assertEqual(by_path["doc.md"].state, "retrieved")
        self.assertEqual(by_path["doc.md"].collection_id, self.collection)

    def test_same_source_in_different_collections_creates_owned_documents(self):
        self._write("doc.md")
        self.collection.scan_storage()

        other = self.env["llm.knowledge.collection"].create(
            {
                "name": "Other KB",
                "source_backend_id": self.backend.id,
                "cache_backend_id": self.backend.id,
            }
        )
        other.scan_storage()
        self.collection.scan_storage()

        documents = self._file_documents()
        self.assertEqual(len(documents), 2)
        self.assertEqual(set(documents.mapped("collection_id")), {self.collection, other})

    def test_gone_file_flagged_and_reappearance_clears_flag(self):
        path = self._write("doc.md")
        self.collection.scan_storage()
        document = self._file_documents()
        self.assertFalse(document.to_delete)

        os.remove(path)
        self.collection.scan_storage()
        self.assertTrue(document.to_delete)

        self._write("doc.md", b"back again")
        self.collection.scan_storage()
        self.assertFalse(document.to_delete)

    def test_source_path_limits_scan_and_gone_detection(self):
        self.collection.source_path = "docs"
        self._write("docs/inside.md")
        self._write("outside.md")
        self.collection.scan_storage()

        documents = self._file_documents()
        self.assertEqual(documents.mapped("source_path"), ["docs/inside.md"])

        # Removing the whole scanned subtree flags only documents under the
        # source path; the sibling stays untouched (and unscanned).
        shutil.rmtree(os.path.join(self.tmpdir, "docs"))
        self.collection.scan_storage()
        self.assertTrue(documents.to_delete)

    def test_upload_wizard_requires_source_backend(self):
        wizard = self.env["llm.upload.document.wizard"].create(
            {
                "collection_id": self.collection.id,
                "external_urls": "https://example.com/article",
            }
        )
        wizard.action_upload_documents()
        demo_document = self.env.ref(
            "llm_knowledge.llm_document_url_demo",
            raise_if_not_found=False,
        )
        url_document = self.env["llm.document"].search(
            [
                ("source_type", "=", "url"),
                ("create_uid", "!=", False),
                ("id", "not in", demo_document.ids if demo_document else []),
            ]
        )
        self.assertEqual(
            len(url_document), 1,
            "expected exactly the wizard's URL document",
        )

        backendless = self.env["llm.knowledge.collection"].create(
            {"name": "No Backend KB"}
        )
        attachment = self.env["ir.attachment"].create(
            {"name": "file.txt", "datas": b"aGVsbG8="}
        )
        wizard = self.env["llm.upload.document.wizard"].create(
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
        wizard = self.env["llm.upload.document.wizard"].create(
            {
                "collection_id": self.collection.id,
                "file_ids": [(4, attachment.id)],
            }
        )
        wizard.action_upload_documents()

        documents = self._file_documents()
        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertTrue(document.source_backend_id.file_exists(document.source_path))
        self.assertEqual(document._retrieve_file_binary()["content"], b"hello")
