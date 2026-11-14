import unittest
from core import make_tasks,category_for,is_non_store,seeded_queries
class SeedTests(unittest.TestCase):
 def test_electronics(self):
  self.assertEqual(category_for('iPhone 17'),'electronics')
  self.assertTrue(any('site:bestbuy.com' in x for x in seeded_queries('iPhone 17','')))
 def test_tools(self):
  self.assertTrue(any('site:homedepot.com' in x for x in seeded_queries('DeWalt drill','')))
 def test_no_media(self):
  self.assertTrue(is_non_store('https://www.wired.com/reviews/phones'))
  self.assertFalse(is_non_store('https://www.bestbuy.com/site/test'))
 def test_priority(self):
  tasks=make_tasks('iPhone 17','',True)
  self.assertTrue(tasks)
  self.assertFalse(tasks[0]['query'].startswith('site:'))
  self.assertTrue(tasks[1]['query'].startswith('site:'))
  self.assertTrue(any('site:bestbuy.com' in task['query'] for task in tasks))
  self.assertTrue(all(task['kind']=='search' for task in tasks))
