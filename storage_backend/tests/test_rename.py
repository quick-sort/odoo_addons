# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import os
import shutil

from .common import CommonCase


class FileSystemRenameCase(CommonCase):
    def setUp(self):
        super().setUp()
        self.backend = self.backend.sudo()
        # The default backend's filestore is shared and not rolled back
        # between runs; a unique token per run keeps this class's paths from
        # ever colliding with leftovers of a previous run.
        self.token = "rename_%d_%s" % (os.getpid(), self.env.cr.dbname)
        self._created = []

    def tearDown(self):
        base = self.backend._get_adapter()._basedir()
        for name in self._created:
            shutil.rmtree(os.path.join(base, name), ignore_errors=True)
        super().tearDown()

    def _path(self, name):
        return "%s_%s" % (self.token, name)

    def _write(self, name, data):
        with self.backend.open(name, "wb") as stream:
            stream.write(data)
        self._created.append(self.backend._gzip_physical(name)[0])

    def test_rename_file(self):
        src, dst = self._path("old.txt"), self._path("new.txt")
        self._write(src, b"data")
        self.backend.rename(src, dst)
        self.assertFalse(self.backend.file_exists(src))
        self.assertTrue(self.backend.file_exists(dst))
        with self.backend.open(dst, "rb") as stream:
            self.assertEqual(stream.read(), b"data")

    def test_rename_into_subdirectory(self):
        name = self._path("file.txt")
        self._write(name, b"data")
        sub = self._path("sub/dir/file.txt")
        self.backend.rename(name, sub)
        self.assertTrue(self.backend.file_exists(sub))
        self.assertIn("file.txt", self.backend.list_files(self._path("sub/dir")))

    def test_rename_directory(self):
        dir_name, new_dir = self._path("dir"), self._path("renamed")
        self._write("%s/a.txt" % dir_name, b"a")
        self.backend.rename(dir_name, new_dir)
        self.assertTrue(self.backend.file_exists("%s/a.txt" % new_dir))
        self.assertFalse(self.backend.file_exists("%s/a.txt" % dir_name))

    def test_rename_missing_source_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.backend.rename(self._path("ghost.txt"), self._path("other.txt"))

    def test_rename_gzip_path_maps_physical(self):
        self.backend.gzip_extensions = "csv,txt"
        try:
            name = self._path("data.csv")
            self._write(name, b"a,b")
            self.backend.rename(name, self._path("other.csv"))
            self.assertFalse(self.backend.file_exists(name))
            with self.backend.open(self._path("other.csv"), "rb") as stream:
                self.assertEqual(stream.read(), b"a,b")
        finally:
            self.backend.gzip_extensions = False
