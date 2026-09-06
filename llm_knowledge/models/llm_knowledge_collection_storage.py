import logging
import posixpath

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _normalize_source_path(path):
    """Strip slashes so backend-relative comparisons are consistent."""
    return (path or "").strip("/")


class LLMKnowledgeCollectionStorage(models.Model):
    """Scan a source storage backend into file resources."""

    _inherit = "llm.knowledge.collection"

    @api.model
    def _iter_backend_files(self, backend, rel_path):
        """Recursively yield ``(path, info)`` for files under ``rel_path``.

        ``path`` is relative to the backend root (``rel_path`` included).
        Directory detection: trailing "/" markers (S3-style), then
        ``is_dir`` from the listing, then stat, then a listing probe
        (non-empty = directory).
        """
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
        """Whether a backend path is a directory, with cheap fallbacks."""
        try:
            info = backend.stat(child_path)
            if isinstance(info, dict) and "is_dir" in info:
                return bool(info["is_dir"])
        except Exception:  # noqa: BLE001 - no stat support or missing path
            pass
        try:
            return bool(backend.list_files(child_path))
        except Exception:  # noqa: BLE001
            return False

    def _get_source_prefix(self):
        """Backend-root-relative prefix this collection scans."""
        self.ensure_one()
        return _normalize_source_path(self.source_path)

    def scan_storage(self):
        """Synchronize the collection with its source storage backend.

        Creates a file resource per newly discovered file, links resources
        that already exist, clears the to_delete flag of files that
        reappeared, and flags resources whose file is gone from the backend
        (never deletes them). New resources are processed inline.
        """
        for collection in self:
            if not collection.source_backend_id:
                continue
            backend = collection.source_backend_id
            prefix = collection._get_source_prefix()
            try:
                seen = dict(
                    collection._iter_backend_files(backend, prefix)
                )
            except UserError as error:
                collection._post_styled_message(str(error), "error")
                continue

            created_count = 0
            linked_count = 0
            flagged_count = 0
            reappeared_count = 0

            for path in sorted(seen):
                existing = self.env["llm.resource"].search(
                    [
                        ("source_type", "=", "file"),
                        ("source_backend_id", "=", backend.id),
                        ("source_path", "=", path),
                    ],
                    limit=1,
                )
                if existing:
                    if existing.to_delete:
                        existing.write({"to_delete": False})
                        existing._post_styled_message(
                            _("Source file reappeared on the backend."), "success"
                        )
                        reappeared_count += 1
                    if collection not in existing.collection_ids:
                        collection.write({"resource_ids": [(4, existing.id)]})
                        linked_count += 1
                    continue

                resource = self.env["llm.resource"].create(
                    {
                        "name": posixpath.basename(path),
                        "source_type": "file",
                        "source_backend_id": backend.id,
                        "source_path": path,
                        "collection_ids": [(4, collection.id)],
                    }
                )
                created_count += 1
                try:
                    resource.process_resource()
                except Exception as error:  # noqa: BLE001
                    _logger.exception(
                        "Error processing scanned resource %s", resource.id
                    )
                    resource._post_styled_message(
                        _("Processing failed: %s", str(error)), "error"
                    )

            flagged = collection._find_gone_file_resources(backend, seen)
            for resource in flagged:
                resource.write({"to_delete": True})
                resource._post_styled_message(
                    _(
                        "Source file no longer found on backend '%s'. "
                        "Resource kept for manual review.",
                        backend.name,
                    ),
                    "warning",
                )
                flagged_count += 1

            collection._post_styled_message(
                _(
                    "Storage scan complete: created %d, linked %d, "
                    "reappeared %d, marked for deletion %d."
                )
                % (created_count, linked_count, reappeared_count, flagged_count),
                "info" if created_count + flagged_count == 0 else "success",
            )

        return True

    def _find_gone_file_resources(self, backend, seen_paths):
        """Collection file resources on ``backend`` under the scan prefix
        whose path was not seen in the listing and not already flagged."""
        self.ensure_one()
        prefix = self._get_source_prefix()

        def _under_prefix(path):
            path = _normalize_source_path(path)
            if not prefix:
                return True
            return path == prefix or path.startswith(prefix + "/")

        return self.resource_ids.filtered(
            lambda r: r.source_type == "file"
            and r.source_backend_id == backend
            and not r.to_delete
            and r.source_path not in seen_paths
            and _under_prefix(r.source_path)
        )

    @api.model
    def _cron_scan_storage(self):
        """Scan every active collection with a source backend."""
        collections = self.search(
            [
                ("active", "=", True),
                ("source_backend_id", "!=", False),
            ]
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
