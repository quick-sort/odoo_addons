# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import gzip
import os

from .common import CommonCase


class StreamingCase(CommonCase):
    def test_chunked_write_then_read(self):
        backend = self.backend
        path = "stream/hello.bin"
        payload = b"x" * (1024 * 1024 + 17)  # > 1 MiB, uneven chunk boundary
        with backend.open(path, "wb") as stream:
            for offset in range(0, len(payload), 64 * 1024):
                stream.write(payload[offset : offset + 64 * 1024])
        # the parent directory was created implicitly
        self.assertTrue(backend.file_exists(path))
        # read back in chunks
        chunks = []
        with backend.open(path, "rb") as stream:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        self.assertEqual(b"".join(chunks), payload)

    def test_parent_dir_auto_created(self):
        backend = self.backend
        # unique suffix: the filestore is shared across test databases, so
        # previous runs' files are not rolled back with the transaction
        # colons in the timestamp would leak into the path
        unique = self.env.cr.now().isoformat().replace(":", "")
        path = "deeply/nested_%s/file.txt" % unique
        base = path.rsplit("/", 1)[0]
        self.assertFalse(backend.file_exists(path))
        with backend.open(path, "wb") as stream:
            stream.write(b"hi")
        self.assertTrue(backend.file_exists(path))
        backend.delete(path)
        # remove the now-empty parent chain so the next run starts clean;
        # rmdir may fail on leftovers from other runs, which is fine
        adapter = backend._get_adapter()
        try:
            while base and base != "deeply":
                adapter.rmdir(base)
                base = base.rsplit("/", 1)[0]
            adapter.rmdir("deeply")
        except OSError:
            pass

    def test_open_rejects_bad_mode(self):
        with self.assertRaises(ValueError):
            with self.backend.open("x.bin", "r"):
                pass

    def test_gzip_open_roundtrip(self):
        backend = self.backend
        backend.gzip_extensions = "csv"
        path = "data.csv"
        logical = b"a,b,c\n1,2,3\n"
        with backend.open(path, "wb") as stream:
            stream.write(logical)
        # reading through open() decompresses transparently
        with backend.open(path, "rb") as stream:
            self.assertEqual(stream.read(), logical)
        # the physical file is a valid gzip stream
        physical = os.path.join(
            backend._get_adapter()._basedir(), backend._gzip_physical(path)[0]
        )
        with open(physical, "rb") as raw_file:
            self.assertEqual(raw_file.read(2), b"\x1f\x8b")  # gzip magic
            raw_file.seek(0)
            self.assertEqual(gzip.decompress(raw_file.read()), logical)
        backend.delete(path)
