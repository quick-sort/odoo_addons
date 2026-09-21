from markupsafe import Markup
from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request


class LlmPageController(http.Controller):

    @http.route(
        "/static/<string:slug>", type="http", auth="public",
        website=True, sitemap=False,
    )
    def page(self, slug, **kw):
        page = request.env["llm.page"].sudo().search(
            [("slug", "=", slug)], limit=1
        )
        if not page:
            raise NotFound()

        user = request.env.user
        if not user.has_group("llm_page.group_reviewer"):
            # Never reveal the existence of an unpublished page.
            if page.state != "published":
                raise NotFound()
            if page.group_id.id not in user.all_group_ids.ids:
                if user._is_public():
                    return request.redirect(
                        f"/web/login?redirect={request.httprequest.path}"
                    )
                raise Forbidden()

        return request.render("llm_page.page_template", {
            "page": page,
            "html": Markup(page.html),
        })
