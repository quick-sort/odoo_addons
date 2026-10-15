import hashlib
import logging
from typing import Any, Optional

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.llm.decorators import llm_tool

from .skill import CODE_SLUG_RE

_logger = logging.getLogger(__name__)


class SkillHubTool(models.AbstractModel):
    _name = "skillhub.tool"
    _description = "SkillHub tools"

    def _skill_path(self, code):
        return f"skillhub/{code}.zip"

    def _staging_path(self, code):
        """Where an incoming package waits until its record has been written.

        Kept on the same backend, and under the skillhub prefix, so promoting
        it to ``_skill_path(code)`` is a rename rather than a cross-backend
        copy.
        """
        return f"skillhub/.staging/{code}.zip"

    def _get_skill_or_raise(self, skill_id):
        skill = self.env["skillhub.skill"].search([("id", "=", skill_id)], limit=1)
        if not skill:
            raise UserError(
                f"Skill {skill_id} not found or you don't have access to it."
            )
        return skill

    def _require_owner(self, skill):
        if skill.create_uid.id != self.env.uid:
            raise UserError("Only the owner can modify this skill.")

    @llm_tool(destructive_hint=False)
    def skill_publish(
        self,
        file_id: int,
        code: str,
        title: str,
        description: str = "",
        version: str = "",
        category_id: int = 0,
        depends_on_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """Publish a skill package from a staged upload (the ``file_id`` returned
        by ``storage_stage_upload`` after ``storage_commit_upload``).

        Streams the zip to a staging path, records its ``size`` and ``sha256``
        and upserts ``skillhub.skill`` by code, and only then moves the package
        to its stable path. Publishing an existing code therefore replaces that
        skill's blob and metadata, while a publish that fails before the record
        is written leaves the previously published package untouched. Only the
        owner of an existing code may overwrite it.

        ``category_id`` optionally assigns a ``skillhub.category``; when omitted
        an existing skill keeps its current category.

        ``depends_on_ids`` optionally sets the skills this one depends on; when
        omitted an existing skill keeps its current dependencies, while an
        explicit list (including empty) replaces them.
        """
        if not CODE_SLUG_RE.fullmatch(code or ""):
            raise UserError(
                "Skill code must be a slug: letters, digits, '.', '_' or '-', "
                "starting with a letter or digit."
            )
        upload = self.env["storage.upload"].browse(file_id)
        if not upload.exists():
            raise UserError(f"Upload {file_id} not found.")
        existing = self.env["skillhub.skill"].search([("code", "=", code)], limit=1)
        if not existing:
            taken = self.env["skillhub.skill"].sudo().search(
                [("code", "=", code)], limit=1
            )
            if taken:
                raise UserError(f"Skill code '{code}' is already taken.")
        storage_path = self._skill_path(code)
        staged_path = self._staging_path(code)
        digest = hashlib.sha256()
        size = 0
        try:
            with upload.consume(
                res_model="skillhub.skill",
                res_id=existing.id if existing else 0,
            ) as stream:
                with upload.backend_id.open(staged_path, "wb") as out:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                        out.write(chunk)
            values = {
                "title": title,
                "description": description,
                "version": version,
                "backend_id": upload.backend_id.id,
                "storage_path": storage_path,
                "size": size,
                "sha256": digest.hexdigest(),
            }
            if category_id:
                values["category_id"] = category_id
            if depends_on_ids is not None:
                values["depends_on_ids"] = [(6, 0, depends_on_ids)]
            if existing:
                existing.write({**values, "state": "active"})
                skill = existing
            else:
                skill = self.env["skillhub.skill"].create({"code": code, **values})
            # The record is written, so the package may take its final place.
            # Promoting it only now is what stops a publish that dies half way
            # from replacing the package the record still points at.
            upload.backend_id.rename(staged_path, storage_path)
        except Exception:
            # Nothing was recorded, so the streamed bytes must not outlive the
            # call. Best effort: a stray staged file beats masking the error
            # that got us here.
            try:
                upload.backend_id.delete(staged_path)
            except Exception:
                _logger.exception("Could not drop staged package %s", staged_path)
            raise
        return {"skill_id": skill.id}

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def skill_download(self, skill_id: int) -> dict[str, Any]:
        """Return a temporary download URL for a skill by id. The bytes do not
        travel through the MCP channel; fetch the URL with curl. Requires read
        access to the skill and MCP read enabled on its backend."""
        skill = self._get_skill_or_raise(skill_id)
        spec = self.env["storage.mcp.tool"]._download_spec(
            skill.backend_id, skill.storage_path
        )
        return {
            "download": spec,
            "curl": self.env["storage.mcp.tool"]._curl(spec["method"], spec["url"]),
        }

    @llm_tool(destructive_hint=False)
    def skill_share(self, skill_id: int, user_ids: list[int]) -> dict[str, Any]:
        """Share a skill with the given user ids. Only the owner may share."""
        skill = self._get_skill_or_raise(skill_id)
        self._require_owner(skill)
        skill.write({"shared_user_ids": [(4, uid) for uid in user_ids]})
        return {"skill_id": skill.id, "shared_user_ids": skill.shared_user_ids.ids}

    @llm_tool(destructive_hint=False)
    def skill_unshare(self, skill_id: int, user_ids: list[int]) -> dict[str, Any]:
        """Revoke sharing of a skill from the given user ids. Only the owner may
        unshare."""
        skill = self._get_skill_or_raise(skill_id)
        self._require_owner(skill)
        skill.write({"shared_user_ids": [(3, uid) for uid in user_ids]})
        return {"skill_id": skill.id, "shared_user_ids": skill.shared_user_ids.ids}

    @llm_tool(destructive_hint=True)
    def skill_archive(self, skill_id: int) -> dict[str, Any]:
        """Archive a skill, hiding it from search. Only the owner may archive."""
        skill = self._get_skill_or_raise(skill_id)
        self._require_owner(skill)
        skill.write({"state": "archived"})
        return {"skill_id": skill.id, "state": skill.state}
