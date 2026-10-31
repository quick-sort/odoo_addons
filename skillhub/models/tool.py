import hashlib
from typing import Any, Optional

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.llm.decorators import llm_tool

from .skill import CODE_SLUG_RE


class SkillHubTool(models.AbstractModel):
    _name = "skillhub.tool"
    _description = "SkillHub tools"

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

    def _get_consumable_attachment(self, attachment_id):
        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if not attachment:
            raise UserError(f"Attachment {attachment_id} not found.")
        attachment.check_access("read")
        if attachment.res_model or attachment.res_id:
            raise UserError(
                "This file has already been used. Upload a new file with "
                "attachment_stage_upload()."
            )
        if not attachment.file_size:
            raise UserError("The uploaded file is empty.")
        return attachment

    @llm_tool(destructive_hint=False, groups=("base.group_user",))
    def skill_publish(
        self,
        attachment_id: int,
        code: str,
        title: str,
        description: str = "",
        version: str = "",
        category_id: int = 0,
        depends_on_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        """Publish a skill package from an unbound ``ir.attachment`` (the
        ``attachment_id`` returned by ``attachment_commit_upload``).

        The attachment must be readable by the caller and not yet bound to any
        record. Publishing consumes it by binding it to the skill, records its
        ``size`` and ``sha256`` and upserts ``skillhub.skill`` by code. An
        existing package is replaced only after the record is written; a
        publish that fails leaves the previous package untouched.

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
        attachment = self._get_consumable_attachment(attachment_id)
        existing = self.env["skillhub.skill"].search([("code", "=", code)], limit=1)
        if not existing:
            taken = self.env["skillhub.skill"].sudo().search(
                [("code", "=", code)], limit=1
            )
            if taken:
                raise UserError(f"Skill code '{code}' is already taken.")

        data = attachment.raw or b""
        values = {
            "title": title,
            "description": description,
            "version": version,
            "attachment_id": attachment.id,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if category_id:
            values["category_id"] = category_id
        if depends_on_ids is not None:
            values["depends_on_ids"] = [(6, 0, depends_on_ids)]

        previous = existing.attachment_id if existing else self.env["ir.attachment"]
        with self.env.cr.savepoint():
            if existing:
                existing.write({**values, "state": "active"})
                skill = existing
            else:
                skill = self.env["skillhub.skill"].create({"code": code, **values})
            attachment.write({"res_model": "skillhub.skill", "res_id": skill.id})
            if previous and previous != attachment:
                previous.unlink()
        return {"skill_id": skill.id, "attachment_id": attachment.id}

    @llm_tool(
        read_only_hint=True,
        destructive_hint=False,
        groups=("base.group_user",),
    )
    def skill_download(self, skill_id: int) -> dict[str, Any]:
        """Return a temporary download URL for a skill by id. The bytes do not
        travel through the MCP channel; fetch the URL with curl. Access follows
        the skill's own read rules (owner, shared users, public skills)."""
        skill = self._get_skill_or_raise(skill_id)
        if not skill.attachment_id:
            raise UserError("This skill has no package; publish it again.")
        return self.env["llm.mcp.file.tool"].with_user(
            self.env.user
        ).attachment_get_download_url(skill.attachment_id.id)

    @llm_tool(destructive_hint=False, groups=("base.group_user",))
    def skill_share(self, skill_id: int, user_ids: list[int]) -> dict[str, Any]:
        """Share a skill with the given user ids. Only the owner may share."""
        skill = self._get_skill_or_raise(skill_id)
        self._require_owner(skill)
        skill.write({"shared_user_ids": [(4, uid) for uid in user_ids]})
        return {"skill_id": skill.id, "shared_user_ids": skill.shared_user_ids.ids}

    @llm_tool(destructive_hint=False, groups=("base.group_user",))
    def skill_unshare(self, skill_id: int, user_ids: list[int]) -> dict[str, Any]:
        """Revoke sharing of a skill from the given user ids. Only the owner may
        unshare."""
        skill = self._get_skill_or_raise(skill_id)
        self._require_owner(skill)
        skill.write({"shared_user_ids": [(3, uid) for uid in user_ids]})
        return {"skill_id": skill.id, "shared_user_ids": skill.shared_user_ids.ids}

    @llm_tool(destructive_hint=True, groups=("base.group_user",))
    def skill_archive(self, skill_id: int) -> dict[str, Any]:
        """Archive a skill, hiding it from search. Only the owner may archive."""
        skill = self._get_skill_or_raise(skill_id)
        self._require_owner(skill)
        skill.write({"state": "archived"})
        return {"skill_id": skill.id, "state": skill.state}
