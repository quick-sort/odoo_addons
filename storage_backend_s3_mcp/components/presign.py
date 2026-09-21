import boto3

from odoo.addons.component.core import Component

TTL_MAX = 3600  # one hour, matching the core relay's token cap


class S3AdapterPresign(Component):
    """Fulfil the core's presign extension point for S3 backends.

    Extends the vendored ``s3.adapter`` in place (same ``_usage``), reusing its
    boto3 client factory and credentials. Bytes go straight to S3 via a
    presigned URL instead of through the Odoo relay.
    """

    _inherit = "s3.adapter"

    def presign_upload(self, relative_path, expires_in=600):
        return self._presign("put_object", relative_path, expires_in)

    def presign_download(self, relative_path, expires_in=600):
        return self._presign("get_object", relative_path, expires_in)

    def _presign(self, operation, relative_path, expires_in):
        key = self._fullpath(relative_path)
        client = boto3.client("s3", **self._aws_bucket_params())
        url = client.generate_presigned_url(
            operation,
            Params={"Bucket": self.collection.aws_bucket, "Key": key},
            ExpiresIn=min(expires_in or 600, TTL_MAX),
        )
        method = "PUT" if operation == "put_object" else "GET"
        return {"url": url, "method": method, "headers": {}}
