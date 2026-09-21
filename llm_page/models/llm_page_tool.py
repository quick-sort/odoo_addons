import re
from typing import Any

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.llm.decorators import llm_tool


class LlmPageTool(models.AbstractModel):
    _name = "llm.page.tool"
    _description = "LLM Page tools"

    @staticmethod
    def _extract_body(html_text):
        """Return the inner HTML of ``<body>`` for a full document, else the
        text unchanged (treated as a body fragment)."""
        match = re.search(
            r"<body[^>]*>(.*)</body>", html_text, re.IGNORECASE | re.DOTALL
        )
        if match:
            return match.group(1).strip()
        return html_text.strip()

    def _normalize_slug(self, slug):
        slug = self.env["ir.http"]._slugify(slug or "").strip("-")
        if not slug:
            raise UserError("A non-empty slug is required.")
        return slug

    @llm_tool(destructive_hint=False)
    def llm_page_create(
        self, file_id: int, name: str, slug: str, submit: bool = False
    ) -> dict[str, Any]:
        """Create an LLM Page from a staged upload (``file_id``), optionally
        submitting it for review. The upload is consumed and its body HTML is
        stored as the page content."""
        upload = self.env["storage.upload"].browse(file_id)
        if not upload.exists():
            raise UserError(f"Upload {file_id} not found.")

        with upload.consume(res_model="llm.page") as stream:
            raw = stream.read()
            if not raw:
                raise UserError("Uploaded content is empty.")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise UserError("Uploaded content is not valid UTF-8.")
            html = self._extract_body(text)

        page = self.env["llm.page"].sudo().create({
            "name": name,
            "slug": self._normalize_slug(slug),
            "html": html,
            "state": "pending" if submit else "draft",
            "date_submit": fields.Datetime.now() if submit else False,
            "source_backend_id": upload.backend_id.id,
            "source_sha256": upload.sha256,
            "source_size_bytes": upload.size_bytes,
        })
        upload.write({"consumed_res_id": page.id})
        return {
            "page_id": page.id,
            "slug": page.slug,
            "url": page._url(),
            "state": page.state,
        }

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def llm_page_list(self) -> list[dict[str, Any]]:
        """List LLM Pages with their review state and URL."""
        pages = self.env["llm.page"].sudo().search([])
        return [
            {
                "page_id": p.id,
                "name": p.name,
                "slug": p.slug,
                "state": p.state,
                "url": p._url(),
            }
            for p in pages
        ]

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def llm_page_status(self, page_id: int) -> dict[str, Any]:
        """Return the review state of a single LLM Page."""
        page = self.env["llm.page"].sudo().browse(page_id)
        if not page.exists():
            raise UserError(f"LLM Page {page_id} not found.")
        return {
            "page_id": page.id,
            "name": page.name,
            "slug": page.slug,
            "state": page.state,
            "url": page._url(),
            "reject_reason": page.reject_reason,
        }

    @llm_tool(destructive_hint=False)
    def llm_page_submit(self, page_id: int) -> dict[str, Any]:
        """Submit an LLM Page for review (draft/rejected → pending)."""
        page = self.env["llm.page"].sudo().browse(page_id)
        if not page.exists():
            raise UserError(f"LLM Page {page_id} not found.")
        page.action_submit()
        return {"page_id": page.id, "state": page.state}
