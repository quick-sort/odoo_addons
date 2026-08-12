# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import errno

from .common import OneStorageCommon


class TestFileApi(OneStorageCommon):
    def test_write_then_read_roundtrip(self):
        entry = self.root_folder.create_file("a.txt", b"hello")
        self.assertEqual(entry.read_bytes(), b"hello")
        self.assertEqual(entry.file_size, 5)
        self.assertEqual(entry.state, "synced")

    def test_write_bytes_overwrites(self):
        entry = self.root_folder.create_file("a.txt", b"old")
        entry.write_bytes(b"new content")
        self.assertEqual(entry.read_bytes(), b"new content")
        self.assertEqual(self.backend.get("a.txt"), b"new content")
        self.assertEqual(entry.state, "synced")

    def test_create_file_without_data_starts_draft(self):
        entry = self.root_folder.create_file("empty.bin")
        self.assertEqual(entry.state, "draft")
        self.assertFalse(entry.file_exists())
        self.assertFalse(self.backend.file_exists("empty.bin"))

    def test_create_file_existing_raises(self):
        self.root_folder.create_file("a.txt", b"x")
        with self.assertRaises(FileExistsError):
            self.root_folder.create_file("a.txt")

    def test_create_file_on_file_raises(self):
        entry = self.root_folder.create_file("a.txt", b"x")
        with self.assertRaises(NotADirectoryError):
            entry.create_file("b.txt")

    def test_mkdir_plain_and_parents(self):
        docs = self.root_folder.mkdir("docs")
        self.assertTrue(docs.is_dir)
        nested = self.root_folder.mkdir("a/b/c", parents=True)
        self.assertEqual(nested.complete_name, "/root/a/b/c")
        # Re-running with parents=True reuses existing levels.
        again = self.root_folder.mkdir("a/b/c", parents=True)
        self.assertEqual(again.id, nested.id)

    def test_mkdir_existing_raises(self):
        self.root_folder.mkdir("docs")
        with self.assertRaises(FileExistsError):
            self.root_folder.mkdir("docs")

    def test_mkdir_on_file_raises(self):
        entry = self.root_folder.create_file("a.txt", b"x")
        with self.assertRaises(NotADirectoryError):
            entry.mkdir("sub")
        with self.assertRaises(NotADirectoryError):
            self.root_folder.mkdir("a.txt/b", parents=True)

    def test_remove_deletes_file_and_backend_bytes(self):
        entry = self.root_folder.create_file("a.txt", b"data")
        entry.remove()
        self.assertFalse(entry.exists())
        self.assertFalse(self.backend.file_exists("a.txt"))

    def test_remove_on_dir_raises(self):
        docs = self.root_folder.mkdir("docs")
        with self.assertRaises(IsADirectoryError):
            docs.remove()

    def test_rmdir_empty(self):
        docs = self.root_folder.mkdir("docs")
        docs.rmdir()
        self.assertFalse(docs.exists())

    def test_rmdir_non_empty_raises(self):
        docs = self.root_folder.mkdir("docs")
        docs.create_file("a.txt", b"x")
        with self.assertRaises(OSError) as ctx:
            docs.rmdir()
        self.assertEqual(ctx.exception.errno, errno.ENOTEMPTY)
        self.assertTrue(docs.exists())

    def test_rmdir_on_file_raises(self):
        entry = self.root_folder.create_file("a.txt", b"x")
        with self.assertRaises(NotADirectoryError):
            entry.rmdir()

    def test_read_bytes_on_dir_raises(self):
        docs = self.root_folder.mkdir("docs")
        with self.assertRaises(IsADirectoryError):
            docs.read_bytes()

    def test_stat_file(self):
        entry = self.root_folder.create_file("a.txt", b"hello")
        st = entry.stat()
        self.assertFalse(st["is_dir"])
        self.assertEqual(st["size"], 5)

    def test_stat_missing_file_raises(self):
        entry = self.root_folder.create_file("ghost.bin")
        with self.assertRaises(FileNotFoundError):
            entry.stat()

    def test_stat_dir_is_logical(self):
        docs = self.root_folder.mkdir("docs")
        st = docs.stat()
        self.assertTrue(st["is_dir"])
        self.assertIsNone(st["size"])

    def test_file_exists(self):
        entry = self.root_folder.create_file("a.txt", b"x")
        self.assertTrue(entry.file_exists())
        self.assertTrue(self.root_folder.file_exists())

    def test_navigate_and_crud(self):
        docs = self.root_folder.mkdir("docs")
        docs.create_file("report.txt", b"42")
        entry = self.root_folder.resolve_path(["docs", "report.txt"])
        self.assertEqual(entry.read_bytes(), b"42")
        self.assertEqual(list(self.root_folder.list_children()), [docs])
        entry.remove()
        self.assertFalse(entry.exists())
