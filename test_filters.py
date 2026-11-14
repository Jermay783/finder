import unittest
from core import allowed_domain,non_us_currency
class Filters(unittest.TestCase):
 def test_foreign(self):
  for u in ['https://a.fr/item','https://x.de','https://shop.co.uk/phone','https://foo.com.au/x','https://a.ca']:
   self.assertFalse(allowed_domain(u),u)
 def test_generic(self):
  for u in ['https://example.com/item','https://store.shop/a','https://store.us/a']:
   self.assertTrue(allowed_domain(u),u)
 def test_currency(self):
  self.assertTrue(non_us_currency('EUR'))
  self.assertFalse(non_us_currency('USD'))
  self.assertFalse(non_us_currency(''))
if __name__=='__main__':unittest.main()
