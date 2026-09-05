import base64
import logging
import mimetypes
import re
from urllib.parse import urljoin, urlparse

import requests
from markdownify import markdownify

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

META_REFRESH_RE = re.compile(
    r"""<meta[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*"""
    r"""content\s*=\s*["']?\d+\s*;\s*url=([^"'>]+)["']?""",
    re.IGNORECASE | re.DOTALL,
)


class LLMResourceHTTPRetriever(models.Model):
    _inherit = "llm.resource"

    retriever = fields.Selection(
        selection_add=[("http", "HTTP Retriever")],
        ondelete={"http": "set default"},
    )

    def retrieve_http(self, retrieval_details, record):
        self.ensure_one()
        if retrieval_details["type"] != "url":
            return False
        return self._http_retrieve(retrieval_details, record)

    def _ensure_full_urls(self, markdown_content, base_url):
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"

        def replace_link(match):
            text, url = match.groups()
            if url.startswith(("http://", "https://", "mailto:", "tel:")):
                return match.group(0)
            try:
                return f"[{text}]({urljoin(base_url, url)})"
            except ValueError:
                _logger.warning(
                    "Could not join base URL %r with relative URL %r", base_url, url
                )
                return match.group(0)

        return re.sub(link_pattern, replace_link, markdown_content)

    def _is_text_content_type(self, content_type):
        main_type = content_type.split(";")[0].strip()
        text_types = (
            "text/html",
            "text/plain",
            "text/markdown",
            "application/xhtml+xml",
            "application/xml",
            "application/json",
            "application/javascript",
        )
        return any(main_type.startswith(item) for item in text_types)

    def _http_fetch_final_response(self, initial_url, headers, max_refreshes=1):
        response = requests.get(
            initial_url, timeout=30, headers=headers, allow_redirects=True
        )
        response.raise_for_status()
        current_url = response.url

        for _refresh in range(max_refreshes):
            content_type = response.headers.get("Content-Type", "").split(";")[0]
            if not self._is_text_content_type(content_type):
                break
            try:
                text_content = response.content.decode(
                    response.encoding or "utf-8", errors="ignore"
                )
                match = META_REFRESH_RE.search(text_content)
                if not match:
                    break
                refresh_url = urljoin(current_url, match.group(1).strip())
                response = requests.get(
                    refresh_url, timeout=30, headers=headers, allow_redirects=True
                )
                response.raise_for_status()
                current_url = response.url
            except Exception as error:  # noqa: BLE001
                _logger.warning("Unable to follow meta refresh for %s: %s", current_url, error)
                break

        return response, current_url

    def _http_determine_file_details(self, response, final_url):
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        if not content_type:
            content_type, _encoding = mimetypes.guess_type(final_url)
        content_type = content_type or "application/octet-stream"

        filename = self.name or urlparse(final_url).path.split("/")[-1] or "downloaded_file"
        if "." not in filename:
            extension = mimetypes.guess_extension(content_type)
            if extension:
                filename += extension
        return {"content_type": content_type, "filename": filename}

    def _http_process_text(self, response, content, final_url):
        encodings = [response.encoding or "utf-8", "latin-1", "windows-1252"]
        text_content = None
        for encoding in dict.fromkeys(encodings):
            try:
                text_content = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text_content is None:
            return {"markdown_content": None, "decoded_successfully": False}

        content_type = response.headers.get("Content-Type", "").split(";")[0]
        if "html" in content_type:
            try:
                text_content = markdownify(text_content)
            except Exception as error:  # noqa: BLE001
                _logger.warning("Markdown conversion failed for %s: %s", final_url, error)
        return {
            "markdown_content": self._ensure_full_urls(text_content, final_url),
            "decoded_successfully": True,
        }

    def _http_store_content(
        self, content, content_type, filename, retrieval_details, record
    ):
        target_fields = retrieval_details["target_fields"]
        content_field = target_fields.get("content")
        content_field_type = (
            record._fields[content_field].type if content_field else None
        )
        if content_field:
            value = (
                base64.b64encode(content)
                if content_field_type == "binary"
                else content
            )
            record.write({content_field: value})
        if target_fields.get("mimetype"):
            record.write({target_fields["mimetype"]: content_type})
        if target_fields.get("filename"):
            record.write({target_fields["filename"]: filename})
        if target_fields.get("type"):
            record.write({target_fields["type"]: content_field_type})

    def _http_retrieve(self, retrieval_details, record):
        self.ensure_one()
        initial_url = record[retrieval_details["field"]]
        if not initial_url:
            self._post_styled_message(
                _("No URL found for this resource %s", record.name), "error"
            )
            return False

        response, final_url = self._http_fetch_final_response(
            initial_url,
            {"User-Agent": "Mozilla/5.0 (compatible; Odoo LLM Resource/1.0)"},
        )
        details = self._http_determine_file_details(response, final_url)
        content = response.content

        if self._is_text_content_type(details["content_type"]):
            result = self._http_process_text(response, content, final_url)
            markdown_content = result["markdown_content"]
            self._write_content_to_backend(markdown_content or "")
            self._http_store_content(
                content,
                details["content_type"],
                details["filename"],
                retrieval_details,
                record,
            )
            return {"state": "parsed"}

        content_field = retrieval_details["target_fields"].get("content")
        if not content_field or record._fields[content_field].type != "binary":
            raise UserError(
                _(
                    "Cannot store binary data in field %s for model %s from URL %s",
                    content_field,
                    record._name,
                    final_url,
                )
            )
        self._http_store_content(
            content,
            details["content_type"],
            details["filename"],
            retrieval_details,
            record,
        )
        return {"state": "retrieved"}
