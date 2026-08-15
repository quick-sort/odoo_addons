# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import errno
import os

from odoo.exceptions import ValidationError

from .common import OneStorageCommon


class TestNameValidation(OneStorageCommon):
    def test_rejects_bad_names(self):
        for bad in ("", "  ", "a/b", "a\\b", "..", ".", " x", "x "):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.root_folder.create_file(bad)

    def test_rejects_bad_name_on_write(self):
        entry = self.root_folder.create_file("ok.txt", b"x")
        with self.assertRaises(ValidationError):
            entry.name = "bad/name"

    def test_rename_rejects_bad_name(self):
        entry = self.root_folder.create_file("ok.txt", b"x")
        with self.assertRaises(OSError) as ctx:
            entry.rename("bad/name")
        self.assertEqual(ctx.exception.errno, errno.EINVAL)


class TestRenameAndMove(OneStorageCommon):
    def test_rename_file_moves_backend_bytes(self):
        entry = self.root_folder.create_file("old.txt", b"data")
        entry.rename("new.txt")
        self.assertEqual(entry.name, "new.txt")
        self.assertFalse(self.backend.file_exists("old.txt"))
        self.assertTrue(self.backend.file_exists("new.txt"))
        self.assertEqual(entry.read_bytes(), b"data")

    def test_rename_noop_keeps_bytes(self):
        entry = self.root_folder.create_file("same.txt", b"data")
        entry.rename("same.txt")
        self.assertTrue(self.backend.file_exists("same.txt"))

    def test_rename_clash_raises(self):
        self.root_folder.create_file("a.txt", b"1")
        b = self.root_folder.create_file("b.txt", b"2")
        with self.assertRaises(FileExistsError):
            b.rename("a.txt")

    def test_rename_directory_moves_subtree_bytes(self):
        folder = self.root_folder.mkdir("docs")
        folder.create_file("inner.txt", b"inner")
        folder.rename("manuals")
        self.assertEqual(folder._backend_relpath(), "manuals")
        self.assertTrue(self.backend.file_exists("manuals/inner.txt"))
        self.assertFalse(self.backend.file_exists("docs/inner.txt"))
        self.assertEqual(
            folder.resolve_path(["inner.txt"]).read_bytes(), b"inner"
        )

    def test_write_name_triggers_backend_rename(self):
        entry = self.root_folder.create_file("old.txt", b"data")
        entry.name = "new.txt"
        self.assertFalse(self.backend.file_exists("old.txt"))
        self.assertTrue(self.backend.file_exists("new.txt"))

    def test_move_same_backend_renames(self):
        sub = self.root_folder.mkdir("sub")
        entry = self.root_folder.create_file("file.txt", b"data")
        entry.move(sub)
        self.assertEqual(entry.parent_id, sub)
        self.assertFalse(self.backend.file_exists("file.txt"))
        self.assertTrue(self.backend.file_exists("sub/file.txt"))
        self.assertEqual(entry.read_bytes(), b"data")

    def test_move_directory_same_backend(self):
        src = self.root_folder.mkdir("src")
        dest = self.root_folder.mkdir("dest")
        src.create_file("inner.txt", b"inner")
        src.move(dest)
        self.assertEqual(src.parent_id, dest)
        self.assertTrue(self.backend.file_exists("dest/src/inner.txt"))
        self.assertFalse(self.backend.file_exists("src/inner.txt"))

    def test_move_into_own_subtree_raises(self):
        parent = self.root_folder.mkdir("parent")
        child = parent.mkdir("child")
        with self.assertRaises(OSError) as ctx:
            parent.move(child)
        self.assertEqual(ctx.exception.errno, errno.EINVAL)

    def test_move_clash_raises(self):
        dest = self.root_folder.mkdir("dest")
        dest.create_file("file.txt", b"clash")
        entry = self.root_folder.create_file("file.txt", b"data")
        with self.assertRaises(FileExistsError):
            entry.move(dest)

    def test_move_onto_file_raises(self):
        target = self.root_folder.create_file("target.txt", b"x")
        entry = self.root_folder.create_file("file.txt", b"data")
        with self.assertRaises(NotADirectoryError):
            entry.move(target)

    def test_cross_backend_move_streams_bytes(self):
        second = self.env["storage.backend"].create(
            {
                "name": "Second FS",
                "backend_type": "filesystem",
                "directory_path": "second_fs_%s" % self.tmp_name,
            }
        )
        dest = self.env["one.storage.entry"].create(
            {"name": "dest", "entry_type": "directory",
             "parent_id": self.root_folder.id}
        )
        second.entry_id = dest
        src = self.root_folder.create_file("moved.bin", b"move me")
        src.move(dest)
        with second.open("moved.bin", "rb") as stream:
            self.assertEqual(stream.read(), b"move me")
        self.assertFalse(self.backend.file_exists("moved.bin"))
        self.assertEqual(src.parent_id, dest)

    def test_cross_backend_move_directory(self):
        second = self.env["storage.backend"].create(
            {
                "name": "Second FS",
                "backend_type": "filesystem",
                "directory_path": "second_fs_dir_%s" % self.tmp_name,
            }
        )
        dest = self.env["one.storage.entry"].create(
            {"name": "dest", "entry_type": "directory",
             "parent_id": self.root_folder.id}
        )
        second.entry_id = dest
        src = self.root_folder.mkdir("tree")
        src.mkdir("inner").create_file("leaf.txt", b"leaf")
        src.create_file("top.txt", b"top")
        src.move(dest)
        self.assertEqual(src.parent_id, dest)
        with second.open("tree/inner/leaf.txt", "rb") as stream:
            self.assertEqual(stream.read(), b"leaf")
        with second.open("tree/top.txt", "rb") as stream:
            self.assertEqual(stream.read(), b"top")
        self.assertFalse(os.path.exists(
            os.path.join(self.tmpdir, "tree")
        ))


class TestCopy(OneStorageCommon):
    def test_copy_file(self):
        entry = self.root_folder.create_file("orig.txt", b"data")
        dest = self.root_folder.mkdir("dest")
        copy = entry.copy_to(dest)
        self.assertNotEqual(copy.id, entry.id)
        self.assertEqual(copy.parent_id, dest)
        self.assertEqual(copy.read_bytes(), b"data")
        # Source untouched.
        self.assertTrue(self.backend.file_exists("orig.txt"))
        self.assertTrue(self.backend.file_exists("dest/orig.txt"))

    def test_copy_file_with_new_name(self):
        entry = self.root_folder.create_file("orig.txt", b"data")
        copy = entry.copy_to(self.root_folder, new_name="renamed.txt")
        self.assertEqual(copy.name, "renamed.txt")
        self.assertTrue(self.backend.file_exists("renamed.txt"))

    def test_copy_directory_recursive(self):
        folder = self.root_folder.mkdir("folder")
        folder.mkdir("sub").create_file("leaf.txt", b"leaf")
        folder.create_file("top.txt", b"top")
        dest = self.root_folder.mkdir("dest")
        copy = folder.copy_to(dest)
        self.assertEqual(copy.parent_id, dest)
        self.assertEqual(
            copy.resolve_path(["sub", "leaf.txt"]).read_bytes(), b"leaf"
        )
        self.assertTrue(self.backend.file_exists("dest/folder/sub/leaf.txt"))
        self.assertTrue(self.backend.file_exists("dest/folder/top.txt"))
        # Source untouched.
        self.assertTrue(self.backend.file_exists("folder/sub/leaf.txt"))

    def test_copy_clash_raises(self):
        entry = self.root_folder.create_file("orig.txt", b"data")
        with self.assertRaises(FileExistsError):
            entry.copy_to(self.root_folder)


class TestRmtree(OneStorageCommon):
    def test_rmtree_deletes_tree(self):
        folder = self.root_folder.mkdir("tree")
        folder.mkdir("sub").create_file("leaf.txt", b"leaf")
        folder.create_file("top.txt", b"top")
        folder.rmtree()
        self.assertFalse(folder.exists())
        self.assertFalse(self.backend.file_exists("tree/sub/leaf.txt"))
        self.assertFalse(self.backend.file_exists("tree/top.txt"))

    def test_rmtree_on_file_raises(self):
        entry = self.root_folder.create_file("a.txt", b"x")
        with self.assertRaises(NotADirectoryError):
            entry.rmtree()

    def test_rmdir_non_empty_still_raises(self):
        folder = self.root_folder.mkdir("tree")
        folder.create_file("a.txt", b"x")
        with self.assertRaises(OSError) as ctx:
            folder.rmdir()
        self.assertEqual(ctx.exception.errno, errno.ENOTEMPTY)


class TestVfsHelpers(OneStorageCommon):
    def test_resolve_path_missing_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            self.root_folder.resolve_path(["ghost.txt"])

    def test_resolve_path_through_file_raises_notadir(self):
        self.root_folder.create_file("a.txt", b"x")
        with self.assertRaises(NotADirectoryError):
            self.root_folder.resolve_path(["a.txt", "b.txt"])

    def test_read_write_text(self):
        entry = self.root_folder.create_file("note.md")
        entry.write_text("héllo")
        self.assertEqual(entry.read_text(), "héllo")

    def test_glob_filters_children(self):
        self.root_folder.create_file("a.txt", b"1")
        self.root_folder.create_file("b.log", b"2")
        self.root_folder.mkdir("c.txt.d")
        matched = self.root_folder.glob("*.txt")
        self.assertEqual(matched.mapped("name"), ["a.txt"])

    def test_open_write_mode_respects_read_only(self):
        entry = self.root_folder.create_file("ro.txt", b"x")
        self.root_folder.read_only = True
        try:
            with self.assertRaises(ValidationError):
                entry.open("wb")
        finally:
            self.root_folder.read_only = False
