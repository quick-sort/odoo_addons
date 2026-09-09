import logging
import posixpath

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _normalize_source_path(path):
    return (path or "").strip("/")


class LLMKnowledgeCollectionStorage(models.Model):
    _inherit = "llm.knowledge.collection"

    @api.model
    def _iter_backend_files(self, backend, rel_path):
        try:
            entries = backend.list_files(rel_path, detail=True)
        except Exception as error:  # noqa: BLE001
            _logger.exception(
                "Could not list %s on backend %s", rel_path or "/", backend.name
            )
            raise UserError(
                _("Could not list '%s' on backend '%s': %s")
                % (rel_path or "/", backend.name, error)
            ) from error

        for item in entries:
            raw_name = item["name"]
            name = raw_name.rstrip("/")
            if not name or name in (".", ".."):
                continue
            child_path = posixpath.join(rel_path, name) if rel_path else name
            if raw_name.endswith("/"):
                is_dir = True
            elif item.get("is_dir") is not None:
                is_dir = bool(item["is_dir"])
            else:
                is_dir = self._backend_child_is_dir(backend, child_path)
            if is_dir:
                yield from self._iter_backend_files(backend, child_path)
            else:
                yield child_path, item

    @api.model
    def _backend_child_is_dir(self, backend, child_path):
        try:
            info = backend.stat(child_path)
            if isinstance(info, dict) and "is_dir" in info:
                return bool(info["is_dir"])
        except Exception:  # noqa: BLE001
            pass
        try:
            return bool(backend.list_files(child_path))
        except Exception:  # noqa: BLE001
            return False

    def _get_source_prefix(self):
        self.ensure_one()
        return _normalize_source_path(self.source_path)

    def scan_storage(self):
        """Synchronize each collection with its own file documents."""
        for collection in self:
            if not collection.source_backend_id:
                continue
            backend = collection.source_backend_id
            prefix = collection._get_source_prefix()
            try:
                seen = dict(collection._iter_backend_files(backend, prefix))
            except UserError as error:
                collection._post_styled_message(str(error), "error")
                continue

            created_count = 0
            reappeared_count = 0
            flagged_count = 0
            for path in sorted(seen):
                document = self.env["llm.document"].search(
                    [
                        ("collection_id", "=", collection.id),
                        ("source_type", "=", "file"),
                        ("source_backend_id", "=", backend.id),
                        ("source_path", "=", path),
                    ],
                    limit=1,
                )
                if document:
                    if document.to_delete:
                        document.write({"to_delete": False})
                        document._post_styled_message(
                            _("Source file reappeared on the backend."), "success"
                        )
                        reappeared_count += 1
                    continue

                document = self.env["llm.document"].create(
                    {
                        "name": posixpath.basename(path),
                        "collection_id": collection.id,
                        "source_type": "file",
                        "source_backend_id": backend.id,
                        "source_path": path,
                    }
                )
                created_count += 1
                try:
                    document.process_document()
                except Exception as error:  # noqa: BLE001
                    _logger.exception("Error processing scanned document %s", document.id)
                    document._post_styled_message(
                        _("Processing failed: %s", str(error)), "error"
                    )

            flagged = collection._find_gone_file_documents(backend, seen)
            for document in flagged:
                document.write({"to_delete": True})
                document._post_styled_message(
                    _(
                        "Source file no longer found on backend '%s'. Document kept "
                        "for manual review.",
                        backend.name,
                    ),
                    "warning",
                )
                flagged_count += 1

            collection._post_styled_message(
                _(
                    "Storage scan complete: created %(created)d, reappeared "
                    "%(reappeared)d, marked for deletion %(flagged)d.",
                    created=created_count,
                    reappeared=reappeared_count,
                    flagged=flagged_count,
                ),
                "info" if created_count + flagged_count == 0 else "success",
            )
        return True

    def _find_gone_file_documents(self, backend, seen_paths):
        self.ensure_one()
        prefix = self._get_source_prefix()

        def _under_prefix(path):
            path = _normalize_source_path(path)
            return not prefix or path == prefix or path.startswith(prefix + "/")

        return self.document_ids.filtered(
            lambda document: document.source_type == "file"
            and document.source_backend_id == backend
            and not document.to_delete
            and document.source_path not in seen_paths
            and _under_prefix(document.source_path)
        )

    @api.model
    def _cron_scan_storage(self):
        collections = self.search(
            [("active", "=", True), ("source_backend_id", "!=", False)]
        )
        for collection in collections:
            try:
                collection.scan_storage()
            except Exception as error:  # noqa: BLE001
                _logger.exception(
                    "Scheduled storage scan failed for collection %s",
                    collection.display_name,
                )
                collection._post_styled_message(
                    _("Scheduled storage scan failed: %s", str(error)), "error"
                )
        return True
