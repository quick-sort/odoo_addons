# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase

from .common import OneStorageCommon


class TestRootDefaultBackend(TransactionCase):
    """The global root is single and bound to the default storage backend."""

    def setUp(self):
        super().setUp()
        # Enforce the single-root invariant against any seeded root so the
        # assertions below are deterministic.
        self.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        self.env["ir.config_parameter"].sudo().set_param(
            "one_storage.default_backend_id", "0"
        )

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

    def test_get_or_create_default_is_idempotent(self):
        first = self.env["storage.backend"]._get_or_create_default()
        second = self.env["storage.backend"]._get_or_create_default()
        self.assertEqual(first, second)


class TestRootDefaultBackendWithAdapter(OneStorageCommon):
    """The default backend wires up to a real filesystem adapter."""

    def test_default_backend_is_filesystem(self):
        backend = self.env["storage.backend"]._get_or_create_default()
        self.assertEqual(backend.backend_type, "filesystem")
        with backend.open("ping.txt", "wb") as stream:
            stream.write(b"pong")
        with backend.open("ping.txt", "rb") as stream:
            self.assertEqual(stream.read(), b"pong")
        backend.delete("ping.txt")
