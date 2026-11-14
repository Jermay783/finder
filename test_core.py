import os,sys,tempfile,unittest
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from core import match_product,shop_domain,canonical,connect,make_tasks,gtin_valid
class Tests(unittest.TestCase):
 def test_case(self):self.assertIn('Аксессуар',match_product('iPhone 16 Pro','Case for iPhone 16 Pro')[1])
 def test_model(self):self.assertTrue(match_product('iPhone 16 Pro','iPhone 16 Pro Max 256GB')[1])
 def test_exact(self):self.assertEqual(match_product('iPhone 16 Pro','Apple iPhone 16 Pro 128GB')[1],'')
 def test_other(self):self.assertEqual(match_product('Bosch GSR 18V-55','Bosch GSR 18V-55 Drill')[1],'')
 def test_generic_broad_brand(self):
  self.assertEqual(match_product('Cartier','Cartier Love Bracelet 18K Gold')[1],'')
  self.assertEqual(match_product('Vortex','Vortex Razor HD Spotting Scope')[1],'')
  self.assertEqual(match_product('iPhone','Apple iPhone 16 Pro Max')[1],'')
  self.assertTrue(match_product('Cartier','Van Cleef Alhambra Bracelet')[1])
 def test_generic_exact_variant(self):
  self.assertTrue(match_product('Vortex Razor HD Gen III 1-10x24','Vortex Razor HD Gen III 6-36x56')[1])
 def test_domain(self):self.assertEqual(shop_domain('https://www.shop.example.co.uk/x'),'example.co.uk')
 def test_canonical(self):self.assertEqual(canonical('https://EXAMPLE.com/x?utm_source=a&id=1'),'https://example.com/x?id=1')
 def test_tasks(self):self.assertGreater(len(make_tasks('drill','',True)),20)
 def test_db(self):
  with tempfile.TemporaryDirectory() as d:
   c=connect(os.path.join(d,'a.db'));c.execute('INSERT INTO stores(domain) VALUES(?)',('example.com',));c.commit();self.assertEqual(c.execute('SELECT COUNT(*) FROM stores').fetchone()[0],1);c.close()
if __name__=='__main__':unittest.main()
