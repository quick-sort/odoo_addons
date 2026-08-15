# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import io

from .common import OneStorageCommon


class TestStreaming(OneStorageCommon):
    def test_write_stream_then_iter_chunks(self):
        payload = b"streamed content " * 1000
        entry = self.env["one.storage.entry"].create(
            {"name": "big.bin", "entry_type": "file",
             "parent_id": self.root_folder.id}
        )
        entry.write_stream(io.BytesIO(payload))
        self.assertEqual(entry.file_size, len(payload))
        self.assertEqual(entry.state, "synced")
        self.assertEqual(b"".join(entry.iter_chunks()), payload)

    def test_iter_chunks_smaller_than_payload(self):
        payload = b"z" * (64 * 1024 + 5)
        entry = self.env["one.storage.entry"].create(
            {"name": "chunky.bin", "entry_type": "file",
             "parent_id": self.root_folder.id}
        )
        entry.write_stream(io.BytesIO(payload))
        chunks = list(entry.iter_chunks(chunk_size=64 * 1024))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(b"".join(chunks), payload)

    def test_cross_backend_move_streams(self):
        # second backend, mirrored at its own root directory
        second = self.env["storage.backend"].create(
            {
                "name": "Second FS",
                "backend_type": "filesystem",
                "directory_path": "second_fs_%s" % self.tmp_name,
            }
        )
        dest = self.env["one.storage.entry"].create(
            {"name": "dest", "entry_type": "directory",
             "parent_id": self.root_folder.id}
        )
        second.entry_id = dest
        src = self.env["one.storage.entry"].create(
            {"name": "moved.bin", "entry_type": "file",
             "parent_id": self.root_folder.id}
        )
        payload = b"move me " * 500
        src.write_stream(io.BytesIO(payload))

        src._batch_move(dest.id)

        # content now lives on the second backend at the destination path
        with second.open("moved.bin", "rb") as stream:
            self.assertEqual(stream.read(), payload)
        self.assertFalse(self.backend.file_exists("moved.bin"))
        self.assertEqual(src.parent_id, dest)
