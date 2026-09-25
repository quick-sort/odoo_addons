from unittest import mock

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSharepointBackend(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://odoo.example.com"
        )
        # server.env.mixin fields (graph_*, backend_type, sharepoint_* config)
        # only persist through write() — values passed to create() are cached
        # but never reach the sparse storage, so recomputes after cache
        # invalidation (or from a sudo env) would fall back to the field
        # defaults. Create bare, then write. Backend: the demo record, like
        # storage_backend_s3_mcp does.
        cls.application = cls.env["microsoft.graph.application"].create(
            {"name": "Contoso Graph App"}
        )
        cls.application.write(
            {
                "graph_tenant_id": "tenant-guid",
                "graph_client_id": "client-guid",
                "graph_client_secret": "sekret",
            }
        )
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.backend.write(
            {
                "backend_type": "sharepoint",
                "sharepoint_application_id": cls.application.id,
                "sharepoint_drive_id": "drive-1",
                "sharepoint_read_only": True,
            }
        )

    def _service_class(self):
        return type(self.env["microsoft.graph.service"])

    # AC-1

    def test_validate_configuration_ok(self):
        self.backend._sharepoint_validate_configuration()

    def test_validate_configuration_missing_application(self):
        self.backend.sharepoint_application_id = False
        with self.assertRaises(UserError):
            self.backend._sharepoint_validate_configuration()

    def test_validate_configuration_missing_drive(self):
        self.backend.sharepoint_drive_id = False
        with self.assertRaises(UserError):
            self.backend._sharepoint_validate_configuration()

    def test_validate_configuration_rejects_other_type(self):
        other = self.env["storage.backend"].create({"name": "Local FS"})
        with self.assertRaises(UserError):
            other._sharepoint_validate_configuration()

    # AC-2

    def test_authorize_delegates_to_graph_service(self):
        with mock.patch.object(
            self._service_class(), "_authorization_action"
        ) as authorize:
            self.backend.action_sharepoint_authorize()
        args, kwargs = authorize.call_args
        self.assertEqual(args[0], self.application)
        self.assertEqual(
            kwargs["redirect_to"],
            f"/web#id={self.backend.id}&model=storage.backend&view_type=form",
        )

    # AC-3

    def test_current_user_authorized_compute(self):
        # The compute has no @api.depends (it counts another model's rows),
        # so the env caches its value per record: within one request the
        # value is only as fresh as the first read. Production sees a new
        # env per request; here we invalidate to observe recomputes.
        def refresh():
            self.backend.invalidate_recordset(
                ["sharepoint_current_user_authorized"]
            )

        self.assertFalse(self.backend.sharepoint_current_user_authorized)
        self.env["microsoft.graph.credential"].sudo().create(
            {
                "application_id": self.application.id,
                "user_id": self.env.user.id,
                "refresh_token": "rt",
            }
        )
        refresh()
        self.assertTrue(self.backend.sharepoint_current_user_authorized)
        # a credential bound to another user does not authorize the current one
        other = self.env["res.users"].create(
            {
                "name": "Bob",
                "login": "bob@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.env["microsoft.graph.credential"].sudo().search(
            [
                ("application_id", "=", self.application.id),
                ("user_id", "=", self.env.user.id),
            ]
        ).unlink()
        self.env["microsoft.graph.credential"].sudo().create(
            {
                "application_id": self.application.id,
                "user_id": other.id,
                "refresh_token": "rt-other",
            }
        )
        refresh()
        self.assertFalse(self.backend.sharepoint_current_user_authorized)

    # AC-4

    def test_adapter_requests_use_backend_application(self):
        adapter = self.backend._get_adapter()
        with mock.patch.object(
            self._service_class(), "_request", return_value={"id": "item-1"}
        ) as request:
            adapter._metadata("docs/a.txt")
        args = request.call_args[0]
        self.assertEqual(args[0], self.application)
        self.assertEqual(args[1], "GET")
        self.assertEqual(args[2], "/v1.0/drives/drive-1/root:/docs/a.txt:")

    def test_adapter_requires_application(self):
        orphan = self.env["storage.backend"].create({"name": "No App"})
        orphan.write(
            {"backend_type": "sharepoint", "sharepoint_drive_id": "drive-1"}
        )
        adapter = orphan._get_adapter()
        with self.assertRaises(AccessError):
            adapter._metadata("a.txt")

    # AC-5

    def test_path_endpoint_construction(self):
        adapter = self.backend._get_adapter()
        self.assertEqual(adapter._path_endpoint(""), "/v1.0/drives/drive-1/root")
        self.assertEqual(
            adapter._path_endpoint("a/b.txt"),
            "/v1.0/drives/drive-1/root:/a/b.txt:",
        )
        self.backend.sharepoint_root_item_id = "root-item"
        self.assertEqual(
            adapter._path_endpoint(""),
            "/v1.0/drives/drive-1/items/root-item",
        )
        self.backend.sharepoint_root_item_id = False
        self.backend.directory_path = "sub/dir"
        self.assertEqual(
            adapter._path_endpoint("a.txt"),
            "/v1.0/drives/drive-1/root:/sub/dir/a.txt:",
        )

    # AC-6

    def test_read_only_blocks_write(self):
        adapter = self.backend._get_adapter()
        with self.assertRaises(AccessError):
            with adapter.open("a.txt", "wb"):
                pass
        with self.assertRaises(AccessError):
            adapter.delete("a.txt")
        with self.assertRaises(AccessError):
            adapter.rename("a.txt", "b.txt")
        with self.assertRaises(AccessError):
            adapter.rmdir("a")

    def test_read_only_allows_read(self):
        adapter = self.backend._get_adapter()
        with mock.patch.object(
            self._service_class(), "_request", side_effect=FileNotFoundError("x")
        ):
            self.assertFalse(adapter.exists("a.txt"))
