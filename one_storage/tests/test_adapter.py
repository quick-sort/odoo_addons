# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.addons.component.exception import NoComponentError

from .common import OneStorageCommon


class TestAdapterLookup(OneStorageCommon):
    """The storage backend (delegated to storage_backend) provides the
    unified add/get/list/delete interface used by entries."""

    def test_unified_add_get_delete(self):
        self.backend.add("a/b.txt", b"hello")
        self.assertEqual(self.backend.get("a/b.txt"), b"hello")
        names = self.backend.list_files("a")
        self.assertIn("b.txt", names)
        self.backend.delete("a/b.txt")
        self.assertEqual(self.backend.list_files("a"), [])

    def test_get_size(self):
        self.backend.add("img.png", b"payload")
        self.assertEqual(self.backend.get_size("img.png"), len(b"payload"))

    def test_validate_config_ok(self):
        self.backend._get_adapter().validate_config()

    def test_unknown_backend_type_raises(self):
        unknown = self.env["storage.backend"].create(
            {"name": "ghost", "backend_type": "filesystem"}
        )
        # monkeypatch to force an unregistered usage
        unknown.backend_type = "does_not_exist"
        with self.assertRaises((NoComponentError, KeyError, ValueError)):
            unknown._get_adapter()


class TestMountRouting(OneStorageCommon):
    """Mount points rebind a folder subtree to another backend."""

    def test_mount_takes_precedence_over_folder_backend(self):
        # second backend + a mount under root
        second = self.env["storage.backend"].create(
            {"name": "Second FS", "backend_type": "filesystem",
             "directory_path": "second_fs"}
        )
        self.env["one.storage.mount"].create(
            {
                "name": "mounted",
                "entry_id": self.root_folder.id,
                "backend_id": second.id,
                "backend_path": "share",
            }
        )
        backend, rel = self.root_folder._resolve_backend()
        self.assertEqual(backend, second)
        self.assertEqual(rel, "share")

    def test_folder_backend_used_when_no_mount(self):
        backend, rel = self.root_folder._resolve_backend()
        self.assertEqual(backend, self.backend)
        self.assertEqual(rel, "")

    def test_resolve_path_to_file(self):
        self._write_on_disk("note.txt", b"data")
        entry = self.env["one.storage.entry"].create(
            {"name": "note.txt", "entry_type": "file", "parent_id": self.root_folder.id}
        )
        resolved = self.root_folder.resolve_path(["note.txt"])
        self.assertEqual(resolved, entry)
        self.assertEqual(entry.backend_path, "note.txt")
