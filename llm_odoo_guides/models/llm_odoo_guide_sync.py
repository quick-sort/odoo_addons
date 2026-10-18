"""Runtime update of the Odoo user-documentation guides.

Fetches the latest ``odoo/documentation`` tarball from GitHub, renders its
``content/applications`` RST through :mod:`odoo.addons.llm_odoo_guides.rst_renderer`,
then upserts the resulting ``llm.tool.guide`` records by ``code``.
"""

import os
import re
import shutil
import tarfile
import tempfile

import requests

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.llm_odoo_guides import rst_renderer

GITHUB_TARBALL = "https://github.com/odoo/documentation/archive/refs/heads/{branch}.tar.gz"
MAX_TARBALL_BYTES = 1_500_000_000  # 1.5 GB hard cap


class OdooGuideSync(models.Model):
    _name = "llm.odoo.guide.sync"
    _description = "Odoo User Guide Sync"

    branch = fields.Char(default="19.0", required=True)
    last_sync_state = fields.Selection(
        [("draft", "Never run"), ("running", "Running"), ("done", "Done"), ("failed", "Failed")],
        default="draft",
        readonly=True,
    )
    last_sync_date = fields.Datetime(readonly=True)
    last_sync_guide_count = fields.Integer(readonly=True)
    last_sync_error = fields.Text(readonly=True)

    def action_sync(self):
        self.ensure_one()
        self.last_sync_state = "running"
        self.last_sync_error = False
        self.with_delay(channel="root.llm_odoo_guides")._sync_from_web()

    def _sync_from_web(self):
        """Download, render and upsert the guides (run inside a queue job)."""
        self.ensure_one()
        applications_dir = None
        try:
            applications_dir = self._download_applications(self.branch)
            guides = rst_renderer.build_all_guides(applications_dir)
            with self.env.cr.savepoint():
                created, updated = self._upsert_guides(guides)
        except Exception as exc:
            # Record the failure without re-raising: raising would roll back the
            # failure bookkeeping with the transaction (see the rollback note in
            # project memory). The savepoint above already discarded any partial
            # upserts.
            self.write({"last_sync_state": "failed", "last_sync_error": str(exc)})
            return
        finally:
            if applications_dir:
                tmp_root = os.path.dirname(os.path.dirname(applications_dir))
                shutil.rmtree(tmp_root, ignore_errors=True)
        self.write({
            "last_sync_state": "done",
            "last_sync_date": fields.Datetime.now(),
            "last_sync_guide_count": created + updated,
            "last_sync_error": False,
        })

    def _download_applications(self, branch):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", branch):
            raise UserError("Invalid branch: %r" % branch)
        url = GITHUB_TARBALL.format(branch=branch)
        fd, tar_path = tempfile.mkstemp(suffix=".tar.gz")
        os.close(fd)
        tmp_dir = tempfile.mkdtemp(prefix="odoo-docs-")
        try:
            self._download(url, tar_path)
            with tarfile.open(tar_path, "r:gz") as tf:
                for member in tf:
                    if not (member.isfile()
                            and member.name.startswith("content/applications/")
                            and member.name.endswith(".rst")):
                        continue
                    dest = os.path.join(tmp_dir, member.name)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as fh:
                        fh.write(tf.extractfile(member).read())
            return os.path.join(tmp_dir, "content", "applications")
        finally:
            try:
                os.unlink(tar_path)
            except OSError:
                pass

    def _download(self, url, dest_path):
        with requests.get(url, stream=True, timeout=(30, 600), allow_redirects=True) as resp:
            resp.raise_for_status()
            final = resp.url or url
            if not final.startswith(("https://github.com/", "https://codeload.github.com/")):
                raise UserError("Refusing to follow a redirect to an unexpected host")
            total = 0
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    total += len(chunk)
                    if total > MAX_TARBALL_BYTES:
                        raise UserError("Tarball exceeds the size cap")

    def _upsert_guides(self, guides):
        Guide = self.env["llm.tool.guide"]
        existing = {g.code: g for g in Guide.search([])}
        created = updated = 0
        for item in guides:
            vals = {k: item[k] for k in ("title", "summary", "keyword", "body")}
            rec = existing.get(item["code"])
            if rec:
                rec.write(vals)
                updated += 1
            else:
                Guide.create(dict(vals, code=item["code"]))
                created += 1
        return created, updated
