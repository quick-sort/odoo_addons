import ipaddress
import mimetypes
import os
import socket
from urllib.parse import unquote, urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter

from odoo import _, models
from odoo.exceptions import UserError

MAX_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = (10, 60)


def _normalize_ip(address):
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _blocked_ip(address):
    address = _normalize_ip(address)
    return (
        not address.is_global
        or address.is_multicast
        or getattr(address, "is_site_local", False)
    )


def _resolve_url(url, allow_private=False):
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise UserError(_("Only absolute HTTP/HTTPS URLs can be retrieved."))
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as error:
        raise UserError(_("The URL contains an invalid port.")) from error
    try:
        infos = socket.getaddrinfo(
            parts.hostname, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as error:
        raise UserError(_("Could not resolve host '%s'.", parts.hostname)) from error

    addresses = []
    for info in infos:
        try:
            address = _normalize_ip(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise UserError(_("Could not resolve host '%s'.", parts.hostname))
    if not allow_private and any(_blocked_ip(address) for address in addresses):
        raise UserError(
            _("Refusing URL '%s' because it resolves to a restricted address.", url)
        )
    return parts, addresses[0]


def _assert_connected_peer(response, expected_address, allow_private=False):
    """Verify that the request used the address selected during validation."""
    connection = getattr(response.raw, "_connection", None) or getattr(
        response.raw, "connection", None
    )
    peer_socket = getattr(connection, "sock", None)
    if peer_socket is None:
        raise UserError(_("Could not verify the remote server address."))
    try:
        address = _normalize_ip(ipaddress.ip_address(peer_socket.getpeername()[0]))
    except (OSError, ValueError) as error:
        raise UserError(_("Could not verify the remote server address.")) from error
    if address != _normalize_ip(expected_address):
        raise UserError(_("The connected server address changed unexpectedly."))
    if not allow_private and _blocked_ip(address):
        raise UserError(
            _("Refusing the URL because the connected server address is restricted.")
        )


def _request_url_key(url):
    """Normalize an HTTP URL for deciding where cached validators may be sent."""
    return urlsplit(url)._replace(fragment="").geturl()


class _PinnedIPAdapter(HTTPAdapter):
    """Connect to a validated IP while preserving the HTTP host and TLS identity."""

    def __init__(self, parts, address):
        self._parts = parts
        self._address = str(address)
        self._port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        hostname = parts.hostname
        display_hostname = "[%s]" % hostname if ":" in hostname else hostname
        default_port = 443 if parts.scheme.lower() == "https" else 80
        self._host_header = (
            display_hostname
            if self._port == default_port
            else "%s:%s" % (display_hostname, self._port)
        )
        super().__init__()

    def get_connection(self, url, proxies=None):
        pool_kwargs = None
        if self._parts.scheme.lower() == "https":
            pool_kwargs = {
                "assert_hostname": self._parts.hostname,
                "server_hostname": self._parts.hostname,
            }
        return self.poolmanager.connection_from_host(
            self._address,
            port=self._port,
            scheme=self._parts.scheme.lower(),
            pool_kwargs=pool_kwargs,
        )

    def add_headers(self, request, **kwargs):
        super().add_headers(request, **kwargs)
        request.headers["Host"] = self._host_header


class LLMDocumentHTTPRetriever(models.Model):
    _inherit = "llm.document"

    def _allow_private_urls(self):
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("llm_knowledge.allow_private_urls", "False")
        )
        return value.strip().lower() in ("1", "true", "yes")

    def _bounded_content(self, response):
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise UserError(_("Remote response exceeds the 50 MiB size limit."))
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES:
                raise UserError(_("Remote response exceeds the 50 MiB size limit."))
            chunks.append(chunk)
        return b"".join(chunks)

    def _response_filename(self, response, final_url, mimetype):
        disposition = response.headers.get("Content-Disposition", "")
        for part in disposition.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key.lower() in ("filename", "filename*"):
                value = value.strip().strip('"')
                if "''" in value:
                    value = value.split("''", 1)[1]
                filename = os.path.basename(unquote(value))
                if filename:
                    return filename
        filename = os.path.basename(unquote(urlsplit(final_url).path)) or self.name
        if "." not in filename:
            filename += mimetypes.guess_extension(mimetype) or ""
        return filename or "download"

    def _download_url(self, force_refresh=False):
        self.ensure_one()
        base_headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Odoo LLM Knowledge/1.0)"
        }
        validator_url = self.final_url or self.source_url
        current_url = self.source_url
        allow_private = self._allow_private_urls()

        for _hop in range(MAX_REDIRECTS + 1):
            parts, address = _resolve_url(
                current_url, allow_private=allow_private
            )
            request_headers = dict(base_headers)
            conditional_target = force_refresh and _request_url_key(
                current_url
            ) == _request_url_key(validator_url)
            if conditional_target and self.etag:
                request_headers["If-None-Match"] = self.etag
            if conditional_target and self.last_modified:
                request_headers["If-Modified-Since"] = self.last_modified
            conditional_request = bool(
                {"If-None-Match", "If-Modified-Since"} & request_headers.keys()
            )

            session = requests.Session()
            session.trust_env = False
            session.mount(
                "%s://" % parts.scheme.lower(), _PinnedIPAdapter(parts, address)
            )
            response = None
            try:
                response = session.get(
                    current_url,
                    headers=request_headers,
                    timeout=TIMEOUT,
                    allow_redirects=False,
                    stream=True,
                )
                _assert_connected_peer(
                    response, address, allow_private=allow_private
                )
                if response.status_code == 304:
                    if not conditional_request:
                        raise UserError(
                            _("The server returned an unexpected HTTP 304 response.")
                        )
                    return {
                        "not_modified": True,
                        "etag": response.headers.get("ETag") or self.etag,
                        "last_modified": response.headers.get("Last-Modified")
                        or self.last_modified,
                    }
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise UserError(
                            _("HTTP redirect did not provide a Location header.")
                        )
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content = self._bounded_content(response)
                mimetype = response.headers.get("Content-Type", "").split(";", 1)[0]
                mimetype = mimetype.strip().lower() or (
                    mimetypes.guess_type(current_url)[0]
                    or "application/octet-stream"
                )
                return {
                    "content": content,
                    "filename": self._response_filename(
                        response, current_url, mimetype
                    ),
                    "mimetype": mimetype,
                    "final_url": current_url,
                    "source_uri": current_url,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                }
            finally:
                if response is not None:
                    response.close()
                session.close()
        raise UserError(_("HTTP URL exceeded the maximum redirect count."))

    def write(self, vals):
        if "source_url" in vals and len(self) > 1:
            return all(document.write(vals) for document in self)

        source_changed = (
            "source_url" in vals
            and self.source_type == "url"
            and self.source_url != vals["source_url"]
        )
        cached_artifacts = []
        if source_changed:
            if not vals["source_url"]:
                raise UserError(_("A URL source requires a URL."))
            self._invalidate_indexed_content()
            backend = self._artifact_backend()
            cached_artifacts = [
                (backend, path)
                for path in (self.raw_artifact_path, self.markdown_artifact_path)
                if backend and path
            ]
            vals = dict(vals)
            vals.update(
                {
                    "state": "draft",
                    "filename": False,
                    "mimetype": False,
                    "size": 0,
                    "checksum": False,
                    "final_url": False,
                    "etag": False,
                    "last_modified": False,
                    "retrieved_at": False,
                    "processed_at": False,
                    "processed_size": 0,
                    "processed_checksum": False,
                    "processed_metadata": False,
                    "markdown": False,
                    "processing_error": False,
                    "lock_date": False,
                }
            )

        result = super().write(vals)
        for backend, path in cached_artifacts:
            if backend.file_exists(path):
                backend.delete(path)
        return result
