import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import core


class FinderBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "finder.sqlite3")
        self.conn = core.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_split_products_preserves_models_and_deduplicates(self):
        self.assertEqual(core.split_products("iPhone 17\niPhone 17 Pro\niPhone 17 Pro Max\nIPHONE 17\n"),
                         ["iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max"])

    def test_batch_persists_separate_searches_and_shared_limit(self):
        batch = core.create_batch(self.conn, "iPhone 17\niPhone 17 Pro\niPhone 17 Pro Max", True, 7, 15)
        self.assertEqual(self.conn.execute("SELECT api_limit FROM search_batches WHERE id=?", (batch,)).fetchone()[0], 7)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM batch_items WHERE batch_id=?", (batch,)).fetchone()[0], 3)
        self.assertEqual([r[0] for r in self.conn.execute(
            "SELECT s.query FROM searches s JOIN batch_items i ON i.search_id=s.id WHERE i.batch_id=? ORDER BY i.position", (batch,))],
            ["iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max"])

    def test_marketplace_subdomains_are_excluded(self):
        for url in ["https://www.ebay.com/itm/123", "https://seller.amazon.com/shop", "https://etsy.com/listing/2"]:
            self.assertTrue(core.is_marketplace(url))
            self.assertFalse(core.add_candidate(self.conn, 1, url))
        self.assertFalse(core.is_marketplace("https://independent-shop.com/products/1"))

    def test_vortex_specs_not_interchangeable(self):
        query = "Vortex Razor HD Gen III 1-10x24"
        score, reason = core.match_product(query, "Vortex Razor HD Gen III 6-36x56")
        self.assertEqual(score, 0)
        self.assertIn("характеристики", reason)
        score, reason = core.match_product(query, "Vortex Razor HD Gen III 1-10x24")
        self.assertGreaterEqual(score, 0.75)
        self.assertEqual(reason, "")

    def test_local_saved_shops_initially_empty(self):
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM saved_shops").fetchone()[0], 0)
        self.conn.execute("INSERT OR IGNORE INTO saved_shops(domain) VALUES('example.com')")
        self.conn.commit()
        self.assertEqual(core.connect(self.db).execute("SELECT COUNT(*) FROM saved_shops").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
