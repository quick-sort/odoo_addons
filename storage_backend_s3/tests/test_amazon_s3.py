# Copyright 2017 Akretion (http://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

# pylint: disable=missing-manifest-dependency
# disable warning on 'vcr' missing in manifest: this is only a dependency for
# dev/tests

import logging
import os
from unittest import mock

from vcr_unittest import VCRMixin

from odoo.addons.storage_backend.tests.common import BackendStorageTestMixin, CommonCase

_logger = logging.getLogger(__name__)


class AmazonS3Case(VCRMixin, CommonCase, BackendStorageTestMixin):
    def _get_vcr_kwargs(self, **kwargs):
        return {
            "record_mode": "once",
            "match_on": ["method", "path", "query"],
            "filter_headers": ["Authorization"],
            "decode_compressed_response": True,
        }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend.write(
            {
                "backend_type": "amazon_s3",
                "aws_bucket": os.environ.get("AWS_BUCKET", "test-storage-backend"),
                "aws_access_key_id": os.environ.get(
                    "AWS_ACCESS_KEY_ID", "FAKE_ACCESS_KEY_ID"
                ),
                "aws_secret_access_key": os.environ.get(
                    "AWS_SECRET_ACCESS_KEY", "FAKE_SECRET_ACCESS_KEY"
                ),
            }
        )

    def test_setting_and_getting_data_from_root(self):
        self._test_setting_and_getting_data_from_root()

    def test_setting_and_getting_data_from_dir(self):
        self._test_setting_and_getting_data_from_dir()

    def test_list_detail_shape(self):
        items = self.backend.list_files(detail=True)
        # Common prefixes become directory entries with a trailing "/"
        # stripped name and is_dir=True; objects carry size and is_dir=False.
        for item in items:
            self.assertIsInstance(item, dict)
            self.assertIn("name", item)
            self.assertIn("size", item)
            self.assertIn("is_dir", item)
        for item in items:
            if item["is_dir"]:
                self.assertFalse(item["name"].endswith("/"))
                self.assertEqual(item["size"], 0)

    def test_recursive_prefix_is_rooted_once(self):
        self.backend.directory_path = "datasets"
        adapter = self.backend._get_adapter()
        bucket = mock.MagicMock()
        bucket.name = "test-storage-backend"
        bucket.meta.client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "datasets/datasets2/", "Size": 0},
                {"Key": "datasets/datasets2/file.csv", "Size": 12},
            ],
            "IsTruncated": False,
        }
        with mock.patch.object(type(adapter), "_get_bucket", return_value=bucket):
            items = self.backend.list_files_recursive("datasets2", detail=True)
            rooted_items = self.backend.list_files_recursive(
                "datasets/datasets2", detail=True
            )
        self.assertEqual(items, rooted_items)
        self.assertEqual(
            items,
            [{"name": "datasets2/file.csv", "size": 12, "is_dir": False}],
        )
        prefixes = [
            call.kwargs["Prefix"]
            for call in bucket.meta.client.list_objects_v2.call_args_list
        ]
        self.assertEqual(prefixes, ["datasets/datasets2/"] * 2)

    def test_recursive_exact_root_segment_is_explicitly_logical(self):
        self.backend.directory_path = "datasets"
        logical_backend = self.backend.with_context(
            storage_backend_force_relative_path=True
        )
        adapter = logical_backend._get_adapter()
        bucket = mock.MagicMock()
        bucket.name = "test-storage-backend"
        bucket.meta.client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "datasets/datasets/prices/file.csv",
                    "Size": 12,
                }
            ],
            "IsTruncated": False,
        }
        with mock.patch.object(type(adapter), "_get_bucket", return_value=bucket):
            items = logical_backend.list_files_recursive(
                "datasets/prices", detail=True
            )
        self.assertEqual(
            items,
            [
                {
                    "name": "datasets/prices/file.csv",
                    "size": 12,
                    "is_dir": False,
                }
            ],
        )
        self.assertEqual(
            bucket.meta.client.list_objects_v2.call_args.kwargs["Prefix"],
            "datasets/datasets/prices/",
        )

    def test_params(self):
        adapter = self.backend._get_adapter()
        self.backend.aws_host = ""
        params = adapter._aws_bucket_params()
        self.assertNotIn("endpoint_url", params)
        self.backend.aws_host = "another.s3.endpoint.com"
        params = adapter._aws_bucket_params()
        self.assertEqual(params["endpoint_url"], "another.s3.endpoint.com")

    def test_aws_other_region_filled(self):
        adapter = self.backend._get_adapter()
        self.assertFalse(self.backend.aws_region)
        self.backend.aws_other_region = "fr-par"
        params = adapter._aws_bucket_params()
        # no region as "aws_region" is empty
        self.assertNotIn("region_name", params)
        self.backend.aws_region = "other"
        params = adapter._aws_bucket_params()
        self.assertEqual(params["region_name"], "fr-par")

    def test_aws_other_region_empty(self):
        self.backend.aws_other_region = ""
        adapter = self.backend._get_adapter()
        params = adapter._aws_bucket_params()
        self.assertNotIn("region_name", params)
