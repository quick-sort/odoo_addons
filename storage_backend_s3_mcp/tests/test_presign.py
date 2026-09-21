from unittest import mock

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestS3McpPresign(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.backend.write({
            "backend_type": "amazon_s3",
            "aws_bucket": "test-bucket",
            "aws_access_key_id": "AKIA",
            "aws_secret_access_key": "secret",
        })

    def _mock_boto3_client(self, url="https://s3.example/presigned"):
        fake = mock.MagicMock()
        fake.generate_presigned_url.return_value = url
        patcher = mock.patch("boto3.client", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def _presign_args(self, fake):
        return fake.generate_presigned_url.call_args

    def test_component_extends_s3_adapter(self):
        adapter = self.backend._get_adapter()
        self.assertTrue(hasattr(adapter, "presign_upload"))
        self.assertTrue(hasattr(adapter, "presign_download"))
        self.assertEqual(adapter._usage, "amazon_s3")

    def test_presign_upload_calls_boto3(self):
        fake = self._mock_boto3_client()
        spec = self.backend.presign_upload("report.csv")
        args = self._presign_args(fake)
        self.assertEqual(args[0][0], "put_object")
        self.assertEqual(args[1]["Params"]["Bucket"], "test-bucket")
        self.assertEqual(args[1]["Params"]["Key"], "report.csv")
        self.assertEqual(spec["method"], "PUT")
        self.assertEqual(spec["url"], "https://s3.example/presigned")

    def test_presign_download_calls_boto3(self):
        fake = self._mock_boto3_client()
        spec = self.backend.presign_download("report.csv")
        args = self._presign_args(fake)
        self.assertEqual(args[0][0], "get_object")
        self.assertEqual(spec["method"], "GET")

    def test_presign_ttl_capped(self):
        fake = self._mock_boto3_client()
        self.backend.presign_upload("x.txt", expires_in=99999)
        self.assertEqual(self._presign_args(fake)[1]["ExpiresIn"], 3600)

    def test_gzip_key_mapping_passed_to_boto3(self):
        self.backend.gzip_extensions = "csv"
        fake = self._mock_boto3_client()
        self.backend.presign_upload("report.csv")
        self.assertEqual(self._presign_args(fake)[1]["Params"]["Key"], "report.csv.gz")

    def test_tool_returns_presigned_url_for_s3(self):
        self.backend.write({"mcp_write_enabled": True, "mcp_read_enabled": True})
        self._mock_boto3_client()
        with mock.patch.object(type(self.backend), "file_exists", return_value=False):
            up = self.env["storage.mcp.tool"].storage_get_upload_url(self.backend.name, "x.txt")
        self.assertEqual(up["upload"]["url"], "https://s3.example/presigned")
