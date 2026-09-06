from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import common


class TestDataset(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls.env["dataset.source"].create(
            {"name": "Test Hugging Face", "code": "test_hf"}
        )

    def test_source_unique_code(self):
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["dataset.source"].create({"name": "Other", "code": "test_hf"})

    def test_package_hierarchy(self):
        parent = self.env["dataset.package"].create({"name": "NLP", "code": "nlp"})
        child = self.env["dataset.package"].create(
            {"name": "Classification", "code": "classification", "parent_id": parent.id}
        )
        self.assertEqual(child.parent_path, f"{parent.id}/{child.id}/")

    def test_build_and_parse_chunk_key(self):
        dataset = self.env["dataset"].create(
            {"name": "IMDB", "code": "imdb", "source_id": self.source.id, "chunk_type": "parquet", "key_fields": ["split", "shard"]}
        )
        key = dataset.build_chunk_key({"split": "train", "shard": "0001"})
        self.assertEqual(key, "test_hf/imdb/train/0001.parquet")
        self.assertEqual(
            dataset.parse_chunk_key(key, dataset.key_fields)["metadata"],
            {"split": "train", "shard": "0001"},
        )

    def test_build_and_parse_key_without_metadata(self):
        dataset = self.env["dataset"].create(
            {"name": "Titanic", "code": "titanic", "source_id": self.source.id, "chunk_type": "csv"}
        )
        key = dataset.build_chunk_key({})
        self.assertEqual(key, "test_hf/titanic.csv")
        parsed = dataset.parse_chunk_key(key)
        self.assertEqual(parsed["source_code"], "test_hf")
        self.assertEqual(parsed["dataset_code"], "titanic")

    def test_unsafe_or_missing_key_components_are_rejected(self):
        dataset = self.env["dataset"].create(
            {"name": "Safe", "code": "safe", "source_id": self.source.id, "chunk_type": "csv", "key_fields": ["split"]}
        )
        for metadata in ({}, {"split": ""}, {"split": "."}, {"split": ".."}, {"split": "a/b"}, {"split": "a\\b"}):
            with self.subTest(metadata=metadata), self.assertRaises(ValidationError):
                dataset.build_chunk_key(metadata)

    def test_dataset_code_is_unique_per_source(self):
        self.env["dataset"].create(
            {"name": "IMDB", "code": "imdb", "source_id": self.source.id}
        )
        other_source = self.env["dataset.source"].create({"name": "Other", "code": "other"})
        other = self.env["dataset"].create(
            {"name": "IMDB", "code": "imdb", "source_id": other_source.id}
        )
        self.assertTrue(other)

    def test_chunk_and_fill_rate(self):
        manifest = self.env["dataset.manifest"].create(
            {"name": "manifest", "values": [{"split": "train"}, {"split": "test"}]}
        )
        dataset = self.env["dataset"].create(
            {"name": "Rows", "code": "rows", "source_id": self.source.id, "key_fields": ["split"], "manifest_id": manifest.id}
        )
        chunk = self.env["dataset.data_chunk"].create(
            {"dataset_id": dataset.id, "metadata": {"split": "train"}, "size": 10}
        )
        self.assertEqual(chunk.key, "test_hf/rows/train.csv")
        self.assertEqual(chunk.state, "exists")
        self.assertEqual(dataset.fill_rate, 0.5)
