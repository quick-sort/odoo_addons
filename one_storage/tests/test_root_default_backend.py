# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.exceptions import ValidationError

from .common import OneStorageCommon


class TestRootDefaultBackend(OneStorageCommon):
    """The global root is single and bound to the default storage backend."""

    def setUp(self):
        super().setUp()
        # _get_or_create_root reuses the common class's bound root; detach
        # it so idempotency and constraint checks start from a clean slate.
        self.env["storage.backend"].search(
            [("entry_id", "=", self.root_folder.id)]
        ).entry_id = False
        self.root_folder.unlink()

    def test_get_or_create_root_is_idempotent(self):
        first = self.env["one.storage.entry"]._get_or_create_root()
        second = self.env["one.storage.entry"]._get_or_create_root()
        self.assertEqual(first, second)
        self.assertFalse(first.parent_id)

    def test_root_uses_default_backend(self):
        root = self.env["one.storage.entry"]._get_or_create_root()
        default = self.env["storage.backend"]._get_or_create_default()
        self.assertEqual(root.backend_id, default)
        param = self.env["ir.config_parameter"].sudo().get_param(
            "one_storage.default_backend_id"
        )
        self.assertEqual(int(param), default.id)

    def test_single_root_constraint(self):
        self.env["one.storage.entry"]._get_or_create_root()
        with self.assertRaises(ValidationError):
            self.env["one.storage.entry"].create(
                {"name": "second root", "entry_type": "directory"}
            )

    def test_default_backend_roundtrips_through_adapter(self):
        backend = self.env["storage.backend"]._get_or_create_default()
        self.assertEqual(backend.backend_type, "filesystem")
        with backend.open("ping.txt", "wb") as stream:
            stream.write(b"pong")
        with backend.open("ping.txt", "rb") as stream:
            self.assertEqual(stream.read(), b"pong")
        backend.delete("ping.txt")
