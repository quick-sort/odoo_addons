# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from unittest import mock

from odoo.addons.component.exception import NoComponentError

from .common import OneStorageCommon


class TestAdapterLookup(OneStorageCommon):
    """The storage backend (delegated to storage_backend) provides the
    unified add/get/list/delete interface used by entries."""

    def test_unified_open_delete(self):
        with self.backend.open("a/b.txt", "wb") as stream:
            stream.write(b"hello")
        with self.backend.open("a/b.txt", "rb") as stream:
            self.assertEqual(stream.read(), b"hello")
        names = self.backend.list_files("a")
        self.assertIn("b.txt", names)
        self.backend.delete("a/b.txt")
        self.assertEqual(self.backend.list_files("a"), [])

    def test_get_size(self):
        with self.backend.open("img.png", "wb") as stream:
            stream.write(b"payload")
        self.assertEqual(self.backend.get_size("img.png"), len(b"payload"))

    def test_validate_config_ok(self):
        self.backend._get_adapter().validate_config()

    def test_unknown_backend_type_raises(self):
        unknown = self.env["storage.backend"].create(
            {"name": "ghost", "backend_type": "filesystem"}
        )
        # ``backend_type`` is a server-env computed field, so it cannot be set
        # to an unregistered usage through the field (the selection rejects it
        # and there is no column to update). Patch it directly to simulate a
        # backend whose adapter component is no longer registered.
        with mock.patch.object(type(unknown), "backend_type", "does_not_exist"):
            with self.assertRaises(NoComponentError):
                unknown._get_adapter()


class TestBindMount(OneStorageCommon):
    """A directory whose ``binding_id`` points at a backend mirror root is a
    bind mount: operating on it operates on the mirror tree, and one backend
    can be bound at several paths."""

    def _make_second_backend_root(self):
        second = self.env["storage.backend"].create(
            {
                "name": "Second FS",
                "backend_type": "filesystem",
                "directory_path": "second_fs_%s" % self.tmp_name,
            }
        )
        # The backend owns its mirror root via entry_id.
        mirror_root = self.env["one.storage.entry"].create(
            {
                "name": "second_root",
                "entry_type": "directory",
                "parent_id": self.root_folder.id,
            }
        )
        second.entry_id = mirror_root
        return second, mirror_root

    def test_resolve_backend_finds_mirror_root(self):
        backend, mirror = self.root_folder._resolve_backend()
        self.assertEqual(backend, self.backend)
        self.assertEqual(mirror, self.root_folder)
        self.assertEqual(self.root_folder._backend_relpath(), "")

    def test_file_relpath_built_from_parent_chain(self):
        self._write_on_disk("note.txt", b"data")
        entry = self.env["one.storage.entry"].create(
            {"name": "note.txt", "entry_type": "file", "parent_id": self.root_folder.id}
        )
        resolved = self.root_folder.resolve_path(["note.txt"])
        self.assertEqual(resolved, entry)
        self.assertEqual(entry._backend_relpath(), "note.txt")

    def test_bind_shows_mirror_children(self):
        second, mirror_root = self._make_second_backend_root()
        base_dir = second._get_adapter()._basedir()
        import os

        sub = os.path.join(base_dir, "second_fs_%s" % self.tmp_name)
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "shared.txt"), "wb") as fh:
            fh.write(b"hi")

        # Bind the mirror root to another directory under root.
        bind = self.env["one.storage.entry"].create(
            {"name": "bind", "entry_type": "directory", "parent_id": self.root_folder.id}
        )
        bind.binding_id = mirror_root

        # Listing the bind lazily mirrors the backend under the *target*.
        names = bind.list_children().mapped("name")
        self.assertIn("shared.txt", names)
        # And listing the mirror root shows the same child.
        self.assertIn("shared.txt", mirror_root.list_children().mapped("name"))

    def test_one_backend_bindable_to_multiple_paths(self):
        second, mirror_root = self._make_second_backend_root()
        bind_a = self.env["one.storage.entry"].create(
            {"name": "bind_a", "entry_type": "directory", "parent_id": self.root_folder.id}
        )
        bind_b = self.env["one.storage.entry"].create(
            {"name": "bind_b", "entry_type": "directory", "parent_id": self.root_folder.id}
        )
        bind_a.binding_id = mirror_root
        bind_b.binding_id = mirror_root
        self.assertEqual(bind_a._follow(), mirror_root)
        self.assertEqual(bind_b._follow(), mirror_root)

    def test_read_only_mirror_blocks_writes(self):
        second, mirror_root = self._make_second_backend_root()
        mirror_root.read_only = True
        with self.assertRaises(Exception):
            mirror_root.create_file("x.txt", b"x")
