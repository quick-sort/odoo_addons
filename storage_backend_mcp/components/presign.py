from odoo.addons.component.core import AbstractComponent


class StorageAdapterPresign(AbstractComponent):
    """Default presign capability: no native signing, so return ``None``.

    The tool layer treats ``None`` as "no native capability, fall back to the
    relay controller with a one-shot capability token". Backends with native
    signing (S3, …) get a bridge addon that overrides these on their adapter.
    """

    _inherit = "base.storage.adapter"

    def presign_upload(self, relative_path, expires_in=600):
        return None

    def presign_download(self, relative_path, expires_in=600):
        return None
