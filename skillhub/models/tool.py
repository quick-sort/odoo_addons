import hashlib
from typing import Any

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.llm.decorators import llm_tool

from .skill import CODE_SLUG_RE


class SkillHubTool(models.AbstractModel):
    _name = "skillhub.tool"
    _description = "SkillHub tools"

    def _skill_path(self, code):
        return f"skillhub/{code}.zip"

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
    ) -> dict[str, Any]:
        """Publish a skill package from a staged upload (the ``file_id`` returned
        by ``storage_stage_upload`` after ``storage_commit_upload``).

        Streams the zip into the backend at a stable path keyed by ``code``,
        records its ``size`` and ``sha256``, then upserts ``skillhub.skill`` by
        code: publishing an existing code overwrites that skill's blob and
        metadata. Only the owner of an existing code may overwrite it.
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
        digest = hashlib.sha256()
        size = 0
        with upload.consume(
            res_model="skillhub.skill",
            res_id=existing.id if existing else 0,
        ) as stream:
            with upload.backend_id.open(storage_path, "wb") as out:
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
        if existing:
            existing.write({**values, "state": "active"})
            skill = existing
        else:
            skill = self.env["skillhub.skill"].create({"code": code, **values})
        return {"skill_id": skill.id}

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def skill_search(self, query: str = "") -> list[dict[str, Any]]:
        """Search published skills by code, title or description (case-insensitive
        substring). With no ``query``, lists all active skills. Only returns
        skills the caller can read (own, shared, or public)."""
        domain = [("state", "=", "active")]
        if query:
            domain += [
                "|",
                "|",
                ("code", "ilike", query),
                ("title", "ilike", query),
                ("description", "ilike", query),
            ]
        skills = self.env["skillhub.skill"].search(domain)
        return [
            {
                "skill_id": skill.id,
                "code": skill.code,
                "title": skill.title,
                "description": skill.description,
                "version": skill.version,
            }
            for skill in skills
        ]

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def skill_get(self, skill_id: int) -> dict[str, Any]:
        """Return the metadata for a skill by id. Raises if the caller cannot
        read it."""
        skill = self._get_skill_or_raise(skill_id)
        return {
            "skill_id": skill.id,
            "code": skill.code,
            "title": skill.title,
            "description": skill.description,
            "version": skill.version,
            "state": skill.state,
            "is_public": skill.is_public,
            "shared_user_ids": skill.shared_user_ids.ids,
            "size": skill.size,
            "sha256": skill.sha256,
        }

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
