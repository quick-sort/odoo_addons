# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from .common import OneStorageCommon


class TestRecursiveSync(OneStorageCommon):
    """_sync_from_backend mirrors the whole backend subtree into entries."""

    def test_materializes_nested_dirs_and_files(self):
        self._write_on_disk("a/d.txt", b"ddd")
        self._write_on_disk("a/b/c.txt", b"ccc")
        self.root_folder._sync_from_backend()
        a = self.root_folder.child_ids.filtered(lambda c: c.name == "a")
        self.assertTrue(a and a.is_dir)
        d = a.child_ids.filtered(lambda c: c.name == "d.txt")
        self.assertTrue(d and not d.is_dir)
        self.assertEqual(d.file_size, len(b"ddd"))
        self.assertEqual(d.mimetype, "text/plain")
        b = a.child_ids.filtered(lambda c: c.name == "b")
        self.assertTrue(b and b.is_dir)
        c = b.child_ids.filtered(lambda ch: ch.name == "c.txt")
        self.assertTrue(c and not c.is_dir)
        self.assertEqual(c.file_size, len(b"ccc"))

    def test_sync_is_idempotent(self):
        self._write_on_disk("note.txt", b"x")
        self.root_folder._sync_from_backend()
        self.root_folder._sync_from_backend()
        notes = self.root_folder.child_ids.filtered(lambda c: c.name == "note.txt")
        self.assertEqual(len(notes), 1)

    def test_list_children_lazily_mirrors(self):
        """Listing a backend mirror dir pulls missing backend children."""
        self._write_on_disk("lazy.txt", b"x")
        children = self.root_folder.list_children()
        names = children.mapped("name")
        self.assertIn("lazy.txt", names)
