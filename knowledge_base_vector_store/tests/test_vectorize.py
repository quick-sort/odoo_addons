# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from unittest import mock

from odoo.exceptions import UserError

from odoo.addons.knowledge_base_vector_store.models.knowledge_vector_store import (
    KnowledgeVectorStore,
)
from odoo.addons.llm.models.llm_provider import LLMProvider

from .common import KnowledgeVectorCase


class FakeStore:
    """In-memory stand-in for a real vector store component."""

    def __init__(self):
        self.indexes = {}
        self.upsert_calls = []
        self.drop_calls = []

    def ensure_index(self, index_name, vector_size):
        self.indexes.setdefault(index_name, {"size": vector_size, "points": []})

    def upsert(self, index_name, points):
        self.upsert_calls.append((index_name, points))
        self.indexes[index_name]["points"].extend(points)

    def search(self, index_name, vector, limit=10, filters=None):
        points = self.indexes.get(index_name, {}).get("points", [])
        scored = [(p[2]["chunk_id"], p[0], 0.9) for p in points]
        return [
            {"id": pid, "score": score, "payload": {"chunk_id": cid}}
            for cid, pid, score in scored[:limit]
        ]

    def drop_index(self, index_name):
        self.drop_calls.append(index_name)
        self.indexes.pop(index_name, None)


class TestVectorize(KnowledgeVectorCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeStore()
        self.patcher_store = mock.patch.object(
            KnowledgeVectorStore,
            "_get_client",
            lambda self: self.fake,
        )
        self.patcher_store.start()
        self.addCleanup(self.patcher_store.stop)
        # The test DB has no provider addon installed; register "openai" so
        # the provider/model records can be created (embedding is mocked).
        self.patcher_services = mock.patch.object(
            LLMProvider,
            "_get_available_services",
            return_value=["openai"],
        )
        self.patcher_services.start()
        self.addCleanup(self.patcher_services.stop)

    def _build_vector(self, chunkset=None, model_use="embedding"):
        chunkset = chunkset or self._create_chunkset()
        provider = self.env["llm.provider"].create(
            {
                "name": "Test Provider",
                "service": "openai",
            }
        )
        model = self.env["llm.model"].create(
            {
                "name": "test-embed",
                "provider_id": provider.id,
                "model_use": model_use,
            }
        )
        vector_store = self.env["knowledge.vector.store"].create(
            {
                "name": "Test Store",
                "vector_store_type": "pgvector",
            }
        )
        return self.env["knowledge.vector"].create(
            {
                "name": "Test Vector",
                "chunkset_id": chunkset.id,
                "model_id": model.id,
                "vector_store_id": vector_store.id,
                "vector_size": 8,
            }
        )

    def test_vectorize_embeds_all_chunks(self):
        content = "\n\n".join(["Chunked content line %d." % i for i in range(30)])
        source = self._seed_extracted(content)
        splitter = self._create_splitter(chunk_size=30)
        chunkset = self._create_chunkset(splitter)
        chunkset._chunk_all()
        vector = self._build_vector(chunkset)

        def fake_embedding(self, texts):
            return [[1.0] * 8 for _ in texts]

        with mock.patch.object(
            type(vector.model_id), "embedding", fake_embedding
        ):
            vector._vectorize()

        self.assertEqual(vector.state, "vectorized")
        index = "kb_%s_cs_%s" % (self.kb.id, chunkset.id)
        self.assertIn(index, self.fake.indexes)
        self.assertEqual(
            len(self.fake.indexes[index]["points"]),
            len(chunkset.chunk_ids),
        )

    def test_search_returns_chunk_text(self):
        content = "\n\n".join(["Line %d" % i for i in range(20)])
        self._seed_extracted(content)
        chunkset = self._create_chunkset(self._create_splitter(chunk_size=30))
        chunkset._chunk_all()
        vector = self._build_vector(chunkset)

        def fake_embedding(self, texts):
            return [[1.0] * 8 for _ in texts]

        with mock.patch.object(type(vector.model_id), "embedding", fake_embedding):
            vector._vectorize()

        hits = vector.search_similar("line")
        self.assertTrue(hits)
        self.assertTrue(any(hit["text"] for hit in hits))
        self.assertTrue(any(hit["chunk_id"] for hit in hits))

    def test_vectorize_without_chunks_raises(self):
        chunkset = self._create_chunkset()
        vector = self._build_vector(chunkset)
        with self.assertRaises(UserError):
            vector._vectorize()

    def test_drop_resets_state(self):
        content = "word " * 50
        self._seed_extracted(content)
        chunkset = self._create_chunkset(self._create_splitter(chunk_size=30))
        chunkset._chunk_all()
        vector = self._build_vector(chunkset)

        with mock.patch.object(
            type(vector.model_id),
            "embedding",
            lambda self, texts: [[1.0] * 8 for _ in texts],
        ):
            vector._vectorize()
        vector.action_drop()
        self.assertEqual(vector.state, "draft")
        index = "kb_%s_cs_%s" % (self.kb.id, chunkset.id)
        self.assertIn(index, self.fake.drop_calls)
