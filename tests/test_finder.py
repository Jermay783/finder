from core import allowed_domain,non_us_currency,canonical,match_product,seeded_queries,make_tasks,category_for,is_non_store
def test_foreign():assert not allowed_domain('https://store.fr/item')
def test_us():assert allowed_domain('https://bestbuy.com/site/item')
def test_currency():assert non_us_currency('EUR') and not non_us_currency('USD')
def test_tracking():assert canonical('https://EXAMPLE.com/x?utm_source=a&id=1')=='https://example.com/x?id=1'
def test_accessory():assert match_product('iPhone 16 Pro','Case for iPhone 16 Pro')[0]==0
def test_model():assert match_product('iPhone 16 Pro','iPhone 16 Pro Max 256GB')[0]==0
def test_exact():assert match_product('iPhone 16 Pro','Apple iPhone 16 Pro 128GB')[0]==1
def test_seeds():assert any('site:bestbuy.com' in x for x in seeded_queries('iPhone 17',''))
def test_tasks():assert len(make_tasks('drill','',True))>20
def test_news():assert is_non_store('https://www.wired.com/reviews/phones')
