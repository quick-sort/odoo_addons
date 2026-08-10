# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from .common import KnowledgeVectorCase


class TestChunking(KnowledgeVectorCase):
    def test_chunking_creates_files_and_records(self):
        content = "\n\n".join(
            ["Paragraph %d with some text content." % i for i in range(40)]
        )
        source = self._seed_extracted(content)
        splitter = self._create_splitter(
            splitter_type="recursive", chunk_size=50, chunk_overlap=5
        )
        chunkset = self._create_chunkset(splitter)
        chunkset._chunk_all()

        self.assertEqual(chunkset.state, "chunked")
        self.assertTrue(chunkset.chunk_ids)
        # Files exist on the backend at the documented layout.
        for chunk in chunkset.chunk_ids:
            self.assertTrue(self.md_backend.exists(chunk.path))
            self.assertEqual(
                chunk.path,
                "%s/chunks/%s/%s.md"
                % (source.id, chunkset.id, chunk.sequence),
            )
        # The union of chunks rejoined approximates the source text.
        joined = "".join(chunk._read_text() for chunk in chunkset.chunk_ids)
        self.assertIn("Paragraph 0", joined)
        self.assertIn("Paragraph 39", joined)

    def test_rechunk_replaces_chunks(self):
        content = "word " * 300
        source = self._seed_extracted(content)
        splitter = self._create_splitter(splitter_type="token", chunk_size=50)
        chunkset = self._create_chunkset(splitter)
        chunkset._chunk_all()
        first_count = len(chunkset.chunk_ids)
        first_chunk_ids = set(chunkset.chunk_ids.ids)
        # Rechunk with a smaller size -> different set of chunks.
        splitter.chunk_size = 20
        chunkset.action_chunk()
        chunkset._chunk_all()
        self.assertNotEqual(len(chunkset.chunk_ids), first_count)
        self.assertNotEqual(set(chunkset.chunk_ids.ids), first_chunk_ids)

    def test_chunk_missing_content_is_skipped(self):
        source = self._add_file_source("nofile.md", "x")  # no content.md written
        chunkset = self._create_chunkset()
        chunkset._chunk_all()
        # The source produced no chunks; chunkset ends up in error (no chunks).
        self.assertFalse(chunkset.chunk_ids.filtered(lambda c: c.source_id == source))
        self.assertEqual(chunkset.state, "error")

    def test_token_splitter_overlap(self):
        splitter = self._create_splitter(splitter_type="token", chunk_size=10, overlap=2)
        chunks = splitter._get_adapter().split("one two three four five six seven eight nine ten eleven twelve")
        self.assertGreater(len(chunks), 1)
        # Overlap means consecutive chunks share words.
        words0 = set(chunks[0].split())
        words1 = set(chunks[1].split())
        self.assertTrue(words0 & words1)
