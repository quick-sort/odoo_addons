.. image:: https://img.shields.io/badge/licence-LGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
   :alt: License: LGPL-3

==================
One Storage
==================

**Unified file storage with mountable VFS and async batch ops**

One Storage is a virtual file system (VFS) layer on top of
`storage_backend <https://github.com/OCA/storage>`_ and its provider
adapters (filesystem, S3, FTP, SFTP). It gives end users a single
browsable file tree where backends can be mounted at any folder, with
per-folder lazy sync and asynchronous batch operations.

Design document
===============

Architecture
------------

Layering (component-based, per the OCA convention for multi-provider
integrations):

``one.storage.entry``
    The VFS model. A tree of directories/files persisted in the
    database. Entries under a mounted folder *mirror* a backend's
    contents; entries elsewhere are *owned* by the VFS and the backend
    is simply the storage target.

``storage.backend``
    Core backend model (provided by the ``storage_backend`` addon).
    Each backend owns a hidden *mirror root* entry via ``entry_id``
    that mirrors the backend's ``/``. A folder mounts a backend by
    pointing its ``binding_id`` at that mirror root (a bind mount).

Adapters (``base.storage.adapter`` components)
    One component per backend type in a dedicated addon
    (``storage_backend_s3``, ``storage_backend_ftp``,
    ``storage_backend_sftp``). One Storage never talks to a provider
    directly — only through the adapter contract below.

``one.storage.operation``
    Queue-job bridge for batch work (sync tree, delete, move, upload).
    One operation record groups one or more ``queue.job`` rows and
    exposes a rolled-up state for the UI.

Key design requirements
-----------------------

* **No backend scans on open.** Opening a folder or "Manage Files"
  reads already-synced entries only. Freshness is explicit: the
  per-folder *Refresh* kanban action or the backend *Sync File Tree*
  button. First open of an empty mirror root seeds one level so the
  browser is never blank.
* **Lazy, one level per listing.** A listing pulls exactly the
  requested folder's children from the backend. Deeper levels are
  fetched when the user opens them. Mounting makes zero backend calls;
  the mirror tree survives unmount so remounting is instant.
* **Mirror roots are internal.** A backend's mirror root is a hidden
  (``active=False``) entry and is exempt from the same-name-in-parent
  uniqueness constraint; a user folder named like a backend never
  conflicts (no ``s3 (2)``).
* **Async batch operations.** Recursive delete, cross-folder move and
  full-tree sync go through ``queue_job`` (channel
  ``root.one_storage``), one job per folder for syncs (breadth-first:
  each folder's job enqueues its subdirectories), so no job ever
  blocks on a recursive scan.
* **Batched sync writes.** A folder sync does one backend listing,
  creates new children in a single ``create()`` call, writes existing
  children only when size/mimetype/state actually changed, and prunes
  entries whose files disappeared on the backend.
* **Folder totals are stored.** ``total_size`` is a stored recursive
  computed field (files: ``file_size``; directories: sum of children),
  so the tree shows sizes and child counts without recomputation;
  displayed via human-readable ``display_size`` (``8M``, ``199K``,
  ``19B``).
* **Path safety.** All adapter paths are logical paths relative to the
  backend root; ``_check_relative_path`` rejects absolute paths,
  backslashes and ``..`` components in every adapter at once.
* **Default backend.** A single global backend backs the root folder,
  resolved through the ``one_storage.default_backend_id`` system
  parameter (repointable from Settings). An unclaimed top-level entry
  resolves to the default backend.

Adapter interface contract
--------------------------

Every adapter component implements the ``base.storage.adapter``
interface (see ``storage_backend/components/base_adapter.py``). The
critical contract for directory-aware backends is ``list(detail=True)``:

.. code-block:: python

    adapter.list("some/dir", detail=True)
    # -> [{"name": "file.txt", "size": 12, "is_dir": False},
    #     {"name": "sub",      "size": 0,  "is_dir": True}, ...]

* ``detail=False`` returns plain names (``str``) as before.
* ``detail=True`` returns **one dict per entry** — never tuples —
  with the ``stat()`` shape: ``name`` (directory names may carry a
  trailing ``/``; the entry layer strips it), ``size`` (int, ``0`` for
  directories), ``is_dir`` (bool). ``mtime`` (epoch seconds) is
  optional.
* Object stores without real directories (e.g. S3) synthesize
  directory entries from common prefixes.
* Each provider test suite carries a ``test_list_detail_shape`` test
  enforcing this shape — new adapters must add one too.

Other interface members: ``open(path, mode)`` (streaming binary
context manager), ``exists``, ``get_size``, ``stat`` (same dict shape),
``find_files(pattern)``, ``move_files``, ``rename`` (default
implementation streams through open+delete; adapters with a native,
atomic primitive override it — it must also work for directories),
``rmdir`` (no-op by default for object stores), ``delete``, and the
optional ``validate_config`` (raise on failure, enables the UI
validation button).

VFS entry API
-------------

Public methods of ``one.storage.entry`` (safe to call from other addons):

``list_children(sync=False)``
    Children of the directory; syncs one level from the backend when
    ``sync=True``.
``resolve_path(segments)``
    Walk names from this entry; returns the entry or an empty recordset.
``create_file(name, data=None)`` / ``mkdir(name, parents=False)``
    Create an owned child; writes through to the backend.
``set_content(data, binary=True)``, ``read_bytes()``, ``write_bytes(data)``,
``read_text()`` / ``write_text()``, ``open(mode)``, ``iter_chunks()``,
``write_stream(fileobj)``
    File content I/O, streamed through the adapter.
``rename(new_name)`` / ``move(dest_dir)``
    Rename in place / move under another directory.
``action_open_children(sync=False)`` / ``action_refresh()``
    Kanban actions: open children (read-only) / sync + reopen.

Model extension points: ``storage.backend.entry_id`` (mirror root) and
``one.storage.entry.binding_id`` (bind mount to a mirror root).

Batch operation API (``one.storage.operation``):

``start_sync_tree(backend, root)``, ``start_delete(entries)``,
``start_move(entries, dest)``
    Create the operation record, enqueue the work, return the action.
    Execution happens in queue jobs; the operation's ``state`` is
    computed from its jobs.

Usage
-----

* Storage → One Storage: browse the tree. Folder cards offer
  Upload / Create / Rename / Move / Refresh in their dropdown.
* Storage → Storage Backends: configure a backend, then *Manage Files*
  to open its mirror, or *Sync File Tree* for a background full sync.
* Mount: on any folder card, use the mount wizard to bind a backend
  at that folder. Unmount keeps the mirror tree for instant remount.

Known issues / Roadmap
----------------------

* Object-store directories are virtual: ``mtime`` for synthesized
  directory entries is not available.
* [FEATURE] resumable uploads
* [FEATURE] shareable links

Bug Tracker
-----------

Bugs are tracked on `GitHub Issues
<https://github.com/OCA/storage/issues>`_. In case of trouble, please
check there if your issue has already been reported.

Credits
=======

Authors
~~~~~~~

* One Storage

Contributors
~~~~~~~~~~~~

* One Storage team

Maintainer
~~~~~~~~~~

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

This module is part of the ``OCA/storage`` project on GitHub.
