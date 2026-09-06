# Copyright 2017 Akretion (http://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
import base64
import gzip
import os

from odoo.exceptions import AccessError

from .common import BackendStorageTestMixin, CommonCase

ADAPTER_PATH = (
    "odoo.addons.storage_backend.components.filesystem_adapter.FileSystemStorageBackend"
)


class FileSystemCase(CommonCase, BackendStorageTestMixin):
    def test_setting_and_getting_data_from_root(self):
        self._test_setting_and_getting_data_from_root()

    def test_setting_and_getting_data_from_dir(self):
        self._test_setting_and_getting_data_from_dir()

    def test_find_files(self):
        good_filepaths = ["somepath/file%d.good" % x for x in range(1, 10)]
        bad_filepaths = ["somepath/file%d.bad" % x for x in range(1, 10)]
        mocked_filepaths = bad_filepaths + good_filepaths
        backend = self.backend.sudo()
        base_dir = backend._get_adapter()._basedir()
        expected = [base_dir + "/" + path for path in good_filepaths]
        self._test_find_files(
            backend, ADAPTER_PATH, mocked_filepaths, r".*\.good$", expected
        )

    def test_move_files(self):
        backend = self.backend.sudo()
        base_dir = backend._get_adapter()._basedir()
        expected = [base_dir + "/" + self.filename]
        destination_path = os.path.join(base_dir, "destination")
        self._test_move_files(
            backend, ADAPTER_PATH, self.filename, destination_path, expected
        )


class FileSystemCapabilitiesCase(CommonCase):
    def _write(self, backend, name, data=None):
        with backend.open(name, "wb") as stream:
            stream.write(data if data is not None else base64.b64decode(self.filedata))

    def test_exists_and_get_size(self):
        backend = self.backend
        filename = "caps_test.bin"
        self.assertFalse(backend.file_exists(filename))
        self._write(backend, filename)
        self.assertTrue(backend.file_exists(filename))
        self.assertEqual(
            backend.get_size(filename),
            len(base64.b64decode(self.filedata)),
        )
        backend.delete(filename)
        self.assertFalse(backend.file_exists(filename))

    def test_list_detail(self):
        backend = self.backend
        names = ["d1.txt", "d2.txt"]
        for name in names:
            self._write(backend, name)
        try:
            os.makedirs(
                os.path.join(backend._get_adapter()._basedir(), "sub"),
                exist_ok=True,
            )
            items = backend.list_files(detail=True)
            by_name = {item["name"]: item for item in items}
            for name in names:
                self.assertEqual(
                    by_name[name]["size"],
                    len(base64.b64decode(self.filedata)),
                )
            subdir = by_name["sub"]
            self.assertIs(subdir["is_dir"], True)
            self.assertIn("mtime", subdir)
        finally:
            for name in names:
                backend.delete(name)

    def test_list_limit(self):
        backend = self.backend
        names = ["l1.txt", "l2.txt", "l3.txt"]
        for name in names:
            self._write(backend, name)
        try:
            self.assertEqual(len(backend.list_files(limit=2)), 2)
        finally:
            for name in names:
                backend.delete(name)

    def test_list_files_recursive_detail_pattern_and_limit(self):
        backend = self.backend
        backend.gzip_extensions = "json"
        names = ["recursive/a.json", "recursive/nested/b.json", "recursive/c.txt"]
        for name in names:
            self._write(backend, name, name.encode())
        try:
            items = backend.list_files_recursive(
                "recursive", pattern="*.json", limit=1, detail=True
            )
            self.assertEqual(len(items), 1)
            self.assertTrue(items[0]["name"].endswith(".json"))
            self.assertFalse(items[0]["is_dir"])
            self.assertGreater(items[0]["size"], 0)
            all_names = backend.list_files_recursive("recursive")
            self.assertIn("recursive/nested/b.json", all_names)
            self.assertNotIn("recursive/nested/b.json.gz", all_names)
        finally:
            for name in names:
                backend.delete(name)
            backend.rmdir("recursive/nested")
            backend.rmdir("recursive")

    def test_stat_file_and_dir(self):
        backend = self.backend
        filename = "stat_test.bin"
        self._write(backend, filename)
        try:
            info = backend.stat(filename)
            self.assertFalse(info["is_dir"])
            self.assertEqual(
                info["size"], len(base64.b64decode(self.filedata))
            )
            self.assertIn("mtime", info)
            self.assertIn("mode", info)
            # the basedir is itself a directory
            dir_info = backend.stat("")
            self.assertTrue(dir_info["is_dir"])
        finally:
            backend.delete(filename)

    def test_gzip_roundtrip(self):
        backend = self.backend
        backend.gzip_extensions = "txt"
        filename = "gzip_test.txt"
        raw = base64.b64decode(self.filedata)
        try:
            self._write(backend, filename, raw)
            # logical path round-trips through open()
            with backend.open(filename, "rb") as stream:
                self.assertEqual(stream.read(), raw)
            # physical path carries a .gz suffix holding compressed bytes
            self.assertTrue(backend.file_exists(filename + ".gz"))
            physical_raw = gzip.decompress(
                open(
                    os.path.join(
                        backend._get_adapter()._basedir(),
                        backend._gzip_physical(filename)[0],
                    ),
                    "rb",
                ).read()
            )
            self.assertEqual(physical_raw, raw)
            # get_size reports the stored (compressed) size, not the logical one
            self.assertNotEqual(backend.get_size(filename), len(raw))
            self.assertGreater(backend.get_size(filename), 0)
            # logical listing strips the .gz suffix back off
            items = backend.list_files()
            self.assertIn(filename, items)
            self.assertNotIn(filename + ".gz", items)
        finally:
            backend.delete(filename)


class FileSystemTraversalCase(CommonCase):
    """Logical paths must never escape the backend root."""

    def _write(self, name):
        with self.backend.open(name, "wb") as stream:
            stream.write(b"x")

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(AccessError):
            self._write("/etc/passwd")

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(AccessError):
            self._write("../escape.txt")

    def test_sibling_prefix_escape_is_rejected(self):
        # A sibling of the basedir that shares its name prefix (``storage``
        # vs ``storageevil``) must not be reachable via ``..``.
        base = self.backend._get_adapter()._basedir()
        sibling = os.path.dirname(base) + "evil"
        rel = os.path.relpath(sibling, base)
        self.assertTrue(rel.startswith(".."))
        with self.assertRaises(AccessError):
            self._write(rel + "/x.txt")

    def test_backslash_is_rejected(self):
        with self.assertRaises(AccessError):
            self._write("a\\b.txt")

    def test_root_prefix_is_component_aware(self):
        self.backend.directory_path = "datasets"
        adapter = self.backend._get_adapter()
        base_dir = adapter._basedir()
        self.assertEqual(
            adapter._fullpath("datasets2/file.txt"),
            os.path.join(base_dir, "datasets", "datasets2", "file.txt"),
        )
        self.assertEqual(
            adapter._fullpath("datasets/file.txt"),
            os.path.join(base_dir, "datasets", "file.txt"),
        )
        logical_adapter = self.backend.with_context(
            storage_backend_force_relative_path=True
        )._get_adapter()
        self.assertEqual(
            logical_adapter._fullpath("datasets/file.txt"),
            os.path.join(base_dir, "datasets", "datasets", "file.txt"),
        )

    def test_clean_relative_path_still_works(self):
        self._write("ok.txt")
        try:
            self.assertTrue(self.backend.file_exists("ok.txt"))
        finally:
            self.backend.delete("ok.txt")


class FileSystemDemoUserAccessCase(CommonCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.backend.with_user(cls.demo_user)

    def test_cannot_add_file(self):
        with self.assertRaises(AccessError):
            with self.backend.open(self.filename, "wb") as stream:
                stream.write(base64.b64decode(self.filedata))

    def test_cannot_list_file(self):
        with self.assertRaises(AccessError):
            self.backend.list_files()

    def test_cannot_read_file(self):
        with self.assertRaises(AccessError):
            with self.backend.open(self.filename, "rb") as stream:
                stream.read()

    def test_cannot_delete_file(self):
        with self.assertRaises(AccessError):
            self.backend.delete(self.filename)
