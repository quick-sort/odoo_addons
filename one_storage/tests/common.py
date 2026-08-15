# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import os
import shutil

from odoo.addons.component.tests.common import TransactionComponentCase

_tmp_counter = 0


class OneStorageCommon(TransactionComponentCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        global _tmp_counter
        _tmp_counter += 1
        cls.tmp_name = "one_storage_test_%s_%s" % (os.getpid(), _tmp_counter)
        cls.backend = cls.env["storage.backend"].create(
            {
                "name": "Test FS",
                "backend_type": "filesystem",
                "directory_path": cls.tmp_name,
            }
        )
        base_dir = cls.backend._get_adapter()._basedir()
        cls.tmpdir = os.path.join(base_dir, cls.tmp_name)
        # A single global root is enforced; clear any seeded root so the test
        # owns the tree and binds it to the dedicated test backend.
        cls.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        cls.root_folder = cls.env["one.storage.entry"].create(
            {"name": "root", "entry_type": "directory"}
        )
        cls.backend.entry_id = cls.root_folder

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        # Filesystem writes are not transactional, so earlier tests' files
        # leak into this test's backend directory. Clear it so lazy mirroring
        # (list_children/_sync_children) only ever sees this test's files.
        if os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir)
        os.makedirs(self.tmpdir, exist_ok=True)

    def _write_on_disk(self, relpath, content):
        full = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(content)
        return full
