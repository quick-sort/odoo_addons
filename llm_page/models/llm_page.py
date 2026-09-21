from odoo import fields, models
from odoo.exceptions import UserError


class LlmPage(models.Model):
    _name = "llm.page"
    _description = "LLM Page"
    _order = "id desc"

    name = fields.Char(required=True)
    slug = fields.Char(required=True)
    html = fields.Text(required=True)
    group_id = fields.Many2one(
        "res.groups", required=True, default=lambda self: self._default_group()
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Review"),
            ("published", "Published"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    website_id = fields.Many2one("website", ondelete="set null")
    date_submit = fields.Datetime()
    date_publish = fields.Datetime()
    date_reject = fields.Datetime()
    reject_reason = fields.Text()
    source_backend_id = fields.Many2one("storage.backend")
    source_sha256 = fields.Char()
    source_size_bytes = fields.Integer()

    _unique_slug = models.Constraint(
        "UNIQUE(slug)", "The URL slug must be unique."
    )

    def _default_group(self):
        return self.env.ref("llm_page.group_viewer").id

    def _url(self):
        self.ensure_one()
        return f"/static/{self.slug}"

    def _can_view(self, user=None):
        user = user or self.env.user
        if user.has_group("llm_page.group_reviewer"):
            return True
        if self.state != "published":
            return False
        return self.group_id.id in user.all_group_ids.ids

    def _ensure_reviewer(self):
        if not self.env.user.has_group("llm_page.group_reviewer"):
            raise UserError(
                "Only members of the LLM Page Reviewer group can perform this action."
            )

    def action_submit(self):
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                raise UserError("Only draft or rejected pages can be submitted.")
            rec.write({
                "state": "pending",
                "date_submit": fields.Datetime.now(),
                "reject_reason": False,
            })

    def action_approve(self):
        self._ensure_reviewer()
        for rec in self:
            if rec.state != "pending":
                raise UserError("Only pending pages can be approved.")
            rec.write({
                "state": "published",
                "date_publish": fields.Datetime.now(),
            })

    def action_reject(self, reason=None):
        self._ensure_reviewer()
        for rec in self:
            if rec.state != "pending":
                raise UserError("Only pending pages can be rejected.")
            rec.write({
                "state": "rejected",
                "date_reject": fields.Datetime.now(),
                "reject_reason": reason or False,
            })

    def action_unpublish(self):
        self._ensure_reviewer()
        for rec in self:
            if rec.state != "published":
                raise UserError("Only published pages can be unpublished.")
            rec.write({"state": "draft", "date_publish": False})

    def action_preview(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self._url(), "target": "new"}
