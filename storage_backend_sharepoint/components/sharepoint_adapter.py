import errno
import posixpath
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import quote, urlparse

import requests

from odoo import _
from odoo.addons.component.core import Component
from odoo.exceptions import AccessError, UserError


_SPOOL_MAX_SIZE = 8 * 1024 * 1024
_SIMPLE_UPLOAD_MAX_SIZE = 4 * 1024 * 1024
_UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024  # 32 * 320 KiB
_ITEM_SELECT = "id,name,size,file,folder,lastModifiedDateTime,parentReference,eTag"


class SharePointStorageAdapter(Component):
    _name = "sharepoint.storage.adapter"
    _inherit = "base.storage.adapter"
    _usage = "sharepoint"

    def _service(self):
        return self.env["sharepoint.graph.service"]

    def _request(self, method, path, **kwargs):
        return self._service()._request(self.collection, method, path, **kwargs)

    def _drive_id(self):
        drive_id = self.collection.sudo().sharepoint_drive_id
        return quote(drive_id, safe="")

    def _root_base_endpoint(self):
        root_item_id = self.collection.sudo().sharepoint_root_item_id
        if root_item_id:
            return f"/v1.0/drives/{self._drive_id()}/items/{quote(root_item_id, safe='')}"
        return f"/v1.0/drives/{self._drive_id()}/root"

    def _rooted_path(self, relative_path):
        path = self._fullpath(relative_path).strip("/")
        return "" if path == "." else path

    def _path_endpoint(self, relative_path="", suffix=""):
        path = self._rooted_path(relative_path)
        base = self._root_base_endpoint()
        if not path:
            return f"{base}{suffix}"
        encoded_path = quote(path, safe="/")
        return f"{base}:/{encoded_path}:{suffix}"

    def _item_endpoint(self, item_id, suffix=""):
        return (
            f"/v1.0/drives/{self._drive_id()}/items/"
            f"{quote(item_id, safe='')}{suffix}"
        )

    def _metadata(self, relative_path=""):
        return self._request(
            "GET",
            self._path_endpoint(relative_path),
            params={"$select": _ITEM_SELECT},
        )

    def _root_item(self):
        return self._request(
            "GET", self._root_base_endpoint(), params={"$select": _ITEM_SELECT}
        )

    def _iter_children(self, parent_id, limit=None):
        path = self._item_endpoint(parent_id, "/children")
        params = {"$select": _ITEM_SELECT}
        if limit:
            params["$top"] = min(int(limit), 999)
        count = 0
        while path:
            payload = self._request("GET", path, params=params)
            params = None
            for item in payload.get("value", []):
                yield item
                count += 1
                if limit and count >= limit:
                    return
            path = payload.get("@odata.nextLink")

    def _find_child(self, parent_id, name):
        folded_name = name.casefold()
        for item in self._iter_children(parent_id):
            if item.get("name", "").casefold() == folded_name:
                return item
        return None

    def _ensure_full_directory(self, full_path):
        parent = self._root_item()
        for name in filter(None, full_path.strip("/").split("/")):
            child = self._find_child(parent["id"], name)
            if child:
                if "folder" not in child:
                    raise NotADirectoryError(full_path)
                parent = child
                continue
            child = self._request(
                "POST",
                self._item_endpoint(parent["id"], "/children"),
                json={
                    "name": name,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "fail",
                },
            )
            parent = child
        return parent

    def _check_writable(self):
        if self.collection.sharepoint_read_only:
            raise AccessError(_("This SharePoint storage backend is read-only."))

    def _check_mutable_path(self, relative_path):
        self._check_relative_path(relative_path)
        if not relative_path or not relative_path.strip("/"):
            raise AccessError(_("The SharePoint backend root cannot be modified."))

    @staticmethod
    def _mtime(item):
        value = item.get("lastModifiedDateTime")
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return None

    def _detail(self, item):
        result = {
            "name": item.get("name", ""),
            "size": item.get("size") or 0,
            "is_dir": "folder" in item,
        }
        mtime = self._mtime(item)
        if mtime is not None:
            result["mtime"] = mtime
        return result

    def validate_config(self):
        self.collection._sharepoint_validate_configuration()
        self._root_item()

    @contextmanager
    def open(self, relative_path, mode="rb", **kwargs):
        if mode not in ("rb", "wb"):
            raise ValueError("mode must be 'rb' or 'wb'")
        if mode == "rb":
            item = self._metadata(relative_path)
            if "folder" in item:
                raise IsADirectoryError(relative_path)
            response = self._request(
                "GET", self._item_endpoint(item["id"], "/content"), stream=True
            )
            response.raw.decode_content = True
            try:
                yield response.raw
            finally:
                response.close()
            return

        self._check_writable()
        with tempfile.SpooledTemporaryFile(
            max_size=_SPOOL_MAX_SIZE, mode="w+b"
        ) as spool:
            yield spool
            spool.seek(0, 2)
            size = spool.tell()
            spool.seek(0)
            self._upload(relative_path, spool, size, kwargs.get("mimetype"))

    def _upload(self, relative_path, stream, size, mimetype=None):
        self._check_mutable_path(relative_path)
        full_path = self._rooted_path(relative_path)
        parent_path, name = posixpath.split(full_path)
        if not name:
            raise IsADirectoryError(relative_path)
        parent = self._ensure_full_directory(parent_path)
        if size <= _SIMPLE_UPLOAD_MAX_SIZE:
            content = stream.read()
            self._request(
                "PUT",
                self._item_endpoint(
                    parent["id"], f":/{quote(name, safe='')}:/content"
                ),
                data=content,
                headers={"Content-Type": mimetype or "application/octet-stream"},
            )
            return
        self._upload_large(parent["id"], name, stream, size)

    def _upload_large(self, parent_id, name, stream, size):
        session = self._request(
            "POST",
            self._item_endpoint(
                parent_id, f":/{quote(name, safe='')}:/createUploadSession"
            ),
            json={
                "item": {
                    "@microsoft.graph.conflictBehavior": "replace",
                    "name": name,
                }
            },
        )
        upload_url = session.get("uploadUrl")
        parsed = urlparse(upload_url or "")
        if parsed.scheme != "https" or not parsed.hostname:
            raise UserError(_("Microsoft Graph returned an invalid upload URL."))

        offset = 0
        while offset < size:
            chunk = stream.read(min(_UPLOAD_CHUNK_SIZE, size - offset))
            end = offset + len(chunk) - 1
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{end}/{size}",
            }
            response = None
            for attempt in range(3):
                try:
                    response = requests.put(
                        upload_url, data=chunk, headers=headers, timeout=120
                    )
                except requests.RequestException as error:
                    if attempt == 2:
                        raise UserError(
                            _("The SharePoint upload session is unavailable.")
                        ) from error
                    time.sleep(attempt + 1)
                    continue
                if response.status_code == 429 and attempt < 2:
                    try:
                        delay = min(
                            float(response.headers.get("Retry-After", "1")), 3.0
                        )
                    except ValueError:
                        delay = 1.0
                    response.close()
                    time.sleep(delay)
                    continue
                break
            if response is None or response.status_code not in (200, 201, 202):
                status = response.status_code if response is not None else 0
                if response is not None:
                    response.close()
                raise UserError(
                    _("SharePoint chunk upload failed with HTTP status %s.", status)
                )
            next_offset = end + 1
            if response.status_code == 202:
                try:
                    ranges = response.json().get("nextExpectedRanges", [])
                except ValueError:
                    ranges = []
                if ranges:
                    try:
                        next_offset = int(ranges[0].split("-", 1)[0])
                    except (TypeError, ValueError):
                        response.close()
                        raise UserError(
                            _("SharePoint returned an invalid upload range.")
                        )
                    if not 0 <= next_offset <= size:
                        response.close()
                        raise UserError(
                            _("SharePoint returned an invalid upload range.")
                        )
            response.close()
            offset = next_offset
            stream.seek(offset)

    def list(self, relative_path="", limit=None, detail=False):
        directory = self._metadata(relative_path)
        if "folder" not in directory:
            raise NotADirectoryError(relative_path)
        items = list(self._iter_children(directory["id"], limit=limit))
        if detail:
            return [self._detail(item) for item in items]
        return [item.get("name", "") for item in items]

    def exists(self, relative_path):
        try:
            self._metadata(relative_path)
        except FileNotFoundError:
            return False
        return True

    def get_size(self, relative_path):
        try:
            return self.stat(relative_path)["size"]
        except FileNotFoundError:
            return 0

    def stat(self, relative_path):
        return self._detail(self._metadata(relative_path))

    def delete(self, relative_path):
        self._check_writable()
        self._check_mutable_path(relative_path)
        try:
            item = self._metadata(relative_path)
        except FileNotFoundError:
            return False
        if "folder" in item:
            raise IsADirectoryError(relative_path)
        self._request("DELETE", self._item_endpoint(item["id"]))
        return True

    def rename(self, relative_path, new_path):
        self._check_writable()
        self._check_mutable_path(relative_path)
        self._check_mutable_path(new_path)
        source = self._metadata(relative_path)
        destination = self._rooted_path(new_path)
        parent_path, name = posixpath.split(destination)
        if not name:
            raise ValueError(_("The destination must include a file or folder name."))
        parent = self._ensure_full_directory(parent_path)
        values = {"name": name}
        source_parent_id = source.get("parentReference", {}).get("id")
        if source_parent_id != parent["id"]:
            values["parentReference"] = {"id": parent["id"]}
        self._request(
            "PATCH", self._item_endpoint(source["id"]), json=values
        )
        return True

    def move_files(self, files, destination_path, **kwargs):
        for relative_path in files:
            self.rename(
                relative_path,
                posixpath.join(destination_path, posixpath.basename(relative_path)),
            )
        return True

    def rmdir(self, relative_path):
        self._check_writable()
        self._check_mutable_path(relative_path)
        try:
            item = self._metadata(relative_path)
        except FileNotFoundError:
            return False
        if "folder" not in item:
            raise NotADirectoryError(relative_path)
        if next(self._iter_children(item["id"], limit=1), None):
            raise OSError(errno.ENOTEMPTY, _("The SharePoint folder is not empty."))
        self._request("DELETE", self._item_endpoint(item["id"]))
        return True
