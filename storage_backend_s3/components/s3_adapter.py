# Copyright 2017 Akretion (http://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# Copyright 2019 Camptocamp SA (http://www.camptocamp.com).
# @author Simone Orsi <simone.orsi@camptocamp.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging
import os
import tempfile
from contextlib import contextmanager

from odoo import exceptions

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

# Spooled temporary files hold up to this many bytes in memory before
# spilling to disk, bounding memory for large uploads.
_SPOOL_MAX_SIZE = 8 * 1024 * 1024

try:
    import boto3
    from botocore.exceptions import ClientError, EndpointConnectionError

except ImportError as err:  # pragma: no cover
    _logger.debug(err)


class S3StorageAdapter(Component):
    _name = "s3.adapter"
    _inherit = "base.storage.adapter"
    _usage = "amazon_s3"

    def _aws_bucket_params(self):
        params = {
            "aws_access_key_id": self.collection.aws_access_key_id,
            "aws_secret_access_key": self.collection.aws_secret_access_key,
        }
        if self.collection.aws_host:
            params["endpoint_url"] = self.collection.aws_host

        if self.collection.aws_region:
            if self.collection.aws_region != "other":
                params["region_name"] = self.collection.aws_region
            elif self.collection.aws_other_region:
                params["region_name"] = self.collection.aws_other_region
        return params

    def _get_bucket(self):
        params = self._aws_bucket_params()
        s3 = boto3.resource("s3", **params)
        bucket_name = self.collection.aws_bucket
        bucket = s3.Bucket(bucket_name)
        exists = True
        try:
            s3.meta.client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            # If a client error is thrown, then check that it was a 404 error.
            # If it was a 404 error, then the bucket does not exist.
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                exists = False
        except EndpointConnectionError as error:
            # log verbose error from s3, return short message for user
            _logger.exception("Error during connection on S3")
            raise exceptions.UserError(str(error)) from error
        region_name = params.get("region_name")
        if not exists:
            if not region_name:
                bucket = s3.create_bucket(Bucket=bucket_name)
            else:
                bucket = s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": region_name},
                )
        return bucket

    def _get_object(self, relative_path=None):
        bucket = self._get_bucket()
        path = None
        if relative_path:
            path = self._fullpath(relative_path)
        return bucket.Object(key=path)

    def validate_config(self):
        bucket_name = self.collection.aws_bucket
        if not bucket_name:
            raise exceptions.UserError(self.env._("No bucket configured"))
        params = self._aws_bucket_params()
        client = boto3.client("s3", **params)
        try:
            client.head_bucket(Bucket=bucket_name)
        except EndpointConnectionError as error:
            _logger.exception("Error during connection on S3")
            raise exceptions.UserError(str(error)) from error
        except ClientError as error:
            raise exceptions.UserError(str(error)) from error

    @contextmanager
    def open(self, relative_path, mode="rb", **kwargs):
        s3object = self._get_object(relative_path)
        if "r" in mode:
            body = s3object.get()["Body"]
            try:
                yield body
            finally:
                body.close()
        else:
            file_params = self._aws_upload_fileobj_params(**kwargs)
            with tempfile.SpooledTemporaryFile(
                max_size=_SPOOL_MAX_SIZE, mode="w+b"
            ) as spool:
                yield spool
                spool.seek(0)
                try:
                    s3object.upload_fileobj(spool, **file_params)
                except ClientError as error:
                    # log verbose error from s3, return short message for user
                    _logger.exception(
                        "Error during storage of the file %s", relative_path
                    )
                    raise exceptions.UserError(
                        self.env._("The file could not be stored: %s") % str(error)
                    ) from error

    def _aws_upload_fileobj_params(self, mimetype=None, **kw):
        extra_args = {}
        if mimetype:
            extra_args["ContentType"] = mimetype
        if self.collection.aws_cache_control:
            extra_args["CacheControl"] = self.collection.aws_cache_control
        if self.collection.aws_file_acl:
            extra_args["ACL"] = self.collection.aws_file_acl
        if extra_args:
            return {"ExtraArgs": extra_args}
        return {}

    def list(self, relative_path="", limit=None, detail=False):
        bucket = self._get_bucket()
        dir_path = self.collection.directory_path or ""
        prefix = "/".join(
            part for part in (dir_path.strip("/"), relative_path.strip("/")) if part
        )
        if prefix:
            prefix += "/"
        client = bucket.meta.client
        items = []
        kwargs = {
            "Bucket": bucket.name,
            "Prefix": prefix,
            "Delimiter": "/",
        }
        while True:
            response = client.list_objects_v2(**kwargs)
            for item in response.get("CommonPrefixes", ()):
                name = item["Prefix"][len(prefix):].rstrip("/")
                if name:
                    name += "/"
                else:
                    # A common prefix that resolves to nothing (e.g. the
                    # delimiter itself) is not a real entry; skip it.
                    continue
                items.append((name, 0) if detail else name)
            for item in response.get("Contents", ()):
                name = item["Key"][len(prefix):]
                if name:
                    items.append((name, item["Size"]) if detail else name)
            if limit and len(items) >= limit:
                items = items[:limit]
                break
            if not response.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = response.get("NextContinuationToken")
        return items

    def exists(self, relative_path):
        s3object = self._get_object(relative_path)
        try:
            s3object.load()
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise e

    def get_size(self, relative_path):
        s3object = self._get_object(relative_path)
        try:
            s3object.load()
            return s3object.content_length
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return 0
            raise e

    def delete(self, relative_path):
        s3object = self._get_object(relative_path)
        try:
            s3object.load()
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise e

        s3object.delete()
        return True
