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

    def test_total_brave_budget_is_shared(self):
        batch = core.create_batch(self.conn, "iPhone 17\niPhone 17 Pro\niPhone 17 Pro Max", False, 5, 30)
        calls = []
        def fake_search(session, key, query, offset, proxy_url=''):
            calls.append(query)
            return []
        with patch.object(core, "search_brave", side_effect=fake_search):
            core.run_batch(self.db, batch, "test-key", threading.Event(), lambda message: None)
        used = self.conn.execute(
            "SELECT COALESCE(SUM(j.api_used),0) FROM jobs j JOIN batch_items i ON i.search_id=j.search_id WHERE i.batch_id=?",
            (batch,)
        ).fetchone()[0]
        self.assertLessEqual(used, 5)
        self.assertEqual(used, len(calls))

    def test_local_saved_shops_initially_empty(self):
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM saved_shops").fetchone()[0], 0)
        self.conn.execute("INSERT OR IGNORE INTO saved_shops(domain) VALUES('example.com')")
        self.conn.commit()
        check_conn = core.connect(self.db)
        try:
            self.assertEqual(check_conn.execute("SELECT COUNT(*) FROM saved_shops").fetchone()[0], 1)
        finally:
            check_conn.close()


if __name__ == "__main__":
    unittest.main()
