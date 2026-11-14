"""US Store Finder 3: persistent discovery, evidence-based product matching."""
import json, re, time, sqlite3, threading, html
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from urllib.parse import urlparse, urljoin, urlunparse, parse_qsl, urlencode
import requests
from bs4 import BeautifulSoup

UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'}
API='https://api.search.brave.com/res/v1/web/search'
ACCESSORY=re.compile(r'\b(case|cover|protector|tempered glass|screen guard|charger|charging cable|adapter|mount|holster|skin|wallet|bumper|lens protector|replacement (part|screen|battery)|accessor(?:y|ies)|replacement card|sim card replacement|sticker|strap|sleeve|shell|compatible with|fits for|designed for)\b',re.I)
REFURB=re.compile(r'\b(refurbished|renewed|used|preowned|pre-owned|open box|open-box)\b',re.I)
BLOCKED={'amazon.com','ebay.com','etsy.com','walmart.com','google.com','youtube.com','reddit.com','facebook.com','instagram.com','pinterest.com','tiktok.com','bestbuy.com'}
# The above marketplace list is excluded only from *independent-store discovery* queries, not general discovery.
SCHEMA='''
CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY,query TEXT NOT NULL,upc TEXT DEFAULT '',small INTEGER DEFAULT 1,created TEXT DEFAULT CURRENT_TIMESTAMP,api_limit INTEGER DEFAULT 100,store_limit INTEGER DEFAULT 30);
CREATE TABLE IF NOT EXISTS jobs(search_id INTEGER PRIMARY KEY,queue TEXT NOT NULL,done TEXT NOT NULL,status TEXT NOT NULL,api_used INTEGER DEFAULT 0,processed INTEGER DEFAULT 0,errors INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS candidates(search_id INTEGER,url TEXT,domain TEXT,title TEXT DEFAULT '',status TEXT DEFAULT 'Ожидает',reason TEXT DEFAULT '',PRIMARY KEY(search_id,url));
CREATE TABLE IF NOT EXISTS results(search_id INTEGER,url TEXT,domain TEXT,title TEXT,price REAL,currency TEXT,availability TEXT,condition TEXT,upc TEXT,score REAL,checked TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(search_id,url));
CREATE TABLE IF NOT EXISTS stores(domain TEXT PRIMARY KEY,shop_name TEXT,first_seen TEXT DEFAULT CURRENT_TIMESTAMP,last_seen TEXT DEFAULT CURRENT_TIMESTAMP,us_status TEXT DEFAULT 'unverified',category_terms TEXT DEFAULT '',product_count INTEGER DEFAULT 0,platform TEXT DEFAULT '',last_product_url TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS search_batches(id INTEGER PRIMARY KEY,created TEXT DEFAULT CURRENT_TIMESTAMP,api_limit INTEGER NOT NULL,store_limit INTEGER NOT NULL,status TEXT DEFAULT 'new');
CREATE TABLE IF NOT EXISTS batch_items(batch_id INTEGER NOT NULL,search_id INTEGER NOT NULL UNIQUE,position INTEGER NOT NULL,PRIMARY KEY(batch_id,position));
CREATE TABLE IF NOT EXISTS saved_shops(domain TEXT PRIMARY KEY, saved_at TEXT DEFAULT CURRENT_TIMESTAMP, note TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_results_domain ON results(search_id,domain);
CREATE INDEX IF NOT EXISTS ix_candidates_status ON candidates(search_id,status);
'''
def connect(path):
 c=sqlite3.connect(path,timeout=30)
 c.executescript(SCHEMA)
 # Support upgrading the previous database if pointed at one.
 for table,cols in {'searches':{'api_limit':'INTEGER DEFAULT 100','store_limit':'INTEGER DEFAULT 30'},'jobs':{'api_used':'INTEGER DEFAULT 0','processed':'INTEGER DEFAULT 0','errors':'INTEGER DEFAULT 0'}}.items():
  existing={x[1] for x in c.execute('PRAGMA table_info('+table+')')}
  for name,typ in cols.items():
   if name not in existing:c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {typ}')
 c.commit();return c

def canonical(url):
 p=urlparse(url)
 if p.scheme not in ('http','https') or not p.hostname:return ''
 q=[(k,v) for k,v in parse_qsl(p.query) if not (k.lower().startswith('utm_') or k.lower() in ('fbclid','gclid','ref','source','tag'))]
 return urlunparse((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/', '',urlencode(q),'') )

def shop_domain(url):
 host=(urlparse(url).hostname or '').lower().removeprefix('www.')
 try:
  import tldextract
  ext=tldextract.extract(host)
  return '.'.join(x for x in (ext.domain,ext.suffix) if x) or host
 except ImportError:
  parts=host.split('.')
  if len(parts)>=3 and '.'.join(parts[-2:]) in ('co.uk','com.au','co.nz','com.br'):return '.'.join(parts[-3:])
  return '.'.join(parts[-2:]) if len(parts)>1 else host

# Country-code domains outside the US are excluded before any page request.
# Generic TLDs (.com/.shop/.net etc.) remain candidates, not proof of US location.
USABLE_COUNTRY_TLDS={'us'}
GENERIC_CC_TLDS={'io','ai','co','me','tv','cc','fm','gg','sh','to'}
KNOWN_NON_US={'uk','fr','de','ca','au','nz','ru','cn','jp','in','br','es','it','nl','be','ch','at','pl','se','no','dk','fi','ie','pt','gr','tr','mx','ar','cl','za','kr','tw','hk','sg','my','id','th','vn','ph','ua','by','kz','il','ae','sa','eg','pk','bd','lk','ro','cz','sk','hu','bg','hr','si','rs','lt','lv','ee','is','lu','cy','mt','ge','am','az','uz','md','ba','mk','al','ng','ke','gh','ma','tn','dz','pe','uy','ve','ec','bo','py','cr','pa','gt','do','cu'}
NON_US_CURRENCY={'EUR','GBP','CAD','AUD','NZD','CHF','JPY','CNY','RUB','INR','BRL','MXN','SEK','NOK','DKK','PLN','AED','SAR','KRW','SGD','HKD'}

def allowed_domain(url):
 host=(urlparse(url).hostname or '').lower().rstrip('.')
 if not host or host=='localhost':return False
 suffix=host.rsplit('.',1)[-1]
 if suffix in KNOWN_NON_US:return False
 # The complete ISO 3166 ccTLD list is not an allowlist for US shops.
 # Country domains unknown to this set are conservatively excluded by the stdlib ISO list
 # provided in the bundled dependency `pycountry`, when available.
 try:
  import pycountry
  codes={x.alpha_2.lower() for x in pycountry.countries}
  if suffix in codes and suffix not in USABLE_COUNTRY_TLDS|GENERIC_CC_TLDS:return False
 except ImportError:pass
 return True

def non_us_currency(value):
 return str(value or '').strip().upper() in NON_US_CURRENCY or (bool(value) and str(value).strip().upper() not in ('USD','US$','$'))

# Marketplace sellers and their subdomains are never independent stores.
MARKETPLACE_DOMAINS={'ebay.com','amazon.com','etsy.com','aliexpress.com','temu.com','mercari.com','poshmark.com','bonanza.com','offerup.com','facebook.com','craigslist.org','walmart.com'}
def is_marketplace(url):
 host=(urlparse(url).hostname or '').lower().rstrip('.')
 return any(host==domain or host.endswith('.'+domain) for domain in MARKETPLACE_DOMAINS)

def split_products(text):
 """Preserve model names; one product per line, stable case-insensitive deduplication."""
 items=[];seen=set()
 for raw in text.splitlines():
  name=raw.strip()
  if name and name.casefold() not in seen:
   items.append(name);seen.add(name.casefold())
 return items

def query_tokens(s):return set(re.findall(r'[a-z0-9]+',s.lower()))
def iphone_model(s):
 m=re.search(r'\biphone\s*(\d{1,2})\s*(pro\s*max|pro|plus|mini)?\b',s,re.I)
 return (m.group(1),re.sub(r'\s+',' ',(m.group(2) or '').lower())) if m else None

def gtin_valid(value):
 digits=re.sub(r'\D','',str(value))
 if len(digits) not in (8,12,13,14):return False
 total=sum(int(d)*(3 if i%2 else 1) for i,d in enumerate(reversed(digits[:-1])))
 return (10-total%10)%10==int(digits[-1])

def match_product(query,title,upc='',found_upc=''):
 if not title.strip():return 0.0,'Нет названия товара'
 if ACCESSORY.search(title) and not ACCESSORY.search(query):return 0.0,'Аксессуар или запасная часть'
 if upc and found_upc and re.sub(r'\D','',upc)!=re.sub(r'\D','',found_upc):return 0.0,'Другой UPC'
 expected=iphone_model(query);actual=iphone_model(title)
 if expected and actual!=expected:return 0.0,'Другая модель / модификация iPhone'
 if expected and not actual:return 0.0,'Модель iPhone не подтверждена'
 # A model's numeric specifications must not silently change (e.g. 1-10x24 vs 6-36x56).
 spec_pattern=r'(?<![a-z0-9])\\d{1,3}\\s*[-–]\\s*\\d{1,3}\\s*[x×]\\s*\\d{1,3}(?![a-z0-9])'
 qspec={re.sub(r'\\s+','',x.lower()).replace('×','x').replace('–','-') for x in re.findall(spec_pattern,query,re.I)}
 tspec={re.sub(r'\\s+','',x.lower()).replace('×','x').replace('–','-') for x in re.findall(spec_pattern,title,re.I)}
 if qspec and not qspec.issubset(tspec):return 0.0,'Не совпадают характеристики модели'
 # Reject contradictory model numbers for other brands when both appear.
 model_pattern=r'\b(?=[a-z0-9-]*\d)[a-z]+[a-z0-9]*[- ]?\d[a-z0-9-]*\b'
 qmodels={re.sub(r'\W','',x.lower()) for x in re.findall(model_pattern,query,re.I)}
 tmodels={re.sub(r'\W','',x.lower()) for x in re.findall(model_pattern,title,re.I)}
 if qmodels and tmodels and not qmodels.intersection(tmodels) and not expected:return 0.0,'Номер модели не совпадает'
 q=query_tokens(query);t=query_tokens(title)
 if not q:return 0.0,'Пустой запрос'
 score=len(q&t)/len(q)
 if upc and found_upc and re.sub(r'\D','',upc)==re.sub(r'\D','',found_upc):score=1.0
 if score<0.75:return round(score,3),'Низкое совпадение названия'
 return round(score,3),''

def queries(name,upc,small):
 base=[f'"{name}" buy online',f'"{name}" price USA',f'"{name}" in stock',f'"{name}" retailer',f'"{name}" shop',f'"{name}" product',f'"{name}" shipping USA',f'"{name}" online store']
 if upc:base.extend([f'"{upc}" buy',f'"{upc}" product',f'"{upc}" price'])
 if small:base.extend([f'"{name}" independent store',f'"{name}" specialty shop',f'"{name}" small business',f'"{name}" boutique',f'"{name}" -amazon -ebay -walmart',f'"{name}" site:myshopify.com',f'"{name}" site:bigcommerce.com'])
 return list(dict.fromkeys(base))

def search_brave(session,key,q,offset,proxy_url=''):
 r=session.get(API,params={'q':q,'count':20,'offset':offset,'country':'us','search_lang':'en'},headers={**UA,'X-Subscription-Token':key,'Accept':'application/json'},timeout=(8,20),proxies={'https':proxy_url,'http':proxy_url} if proxy_url else None)
 if r.status_code!=200:raise RuntimeError(f'Brave HTTP {r.status_code}: {r.text[:160]}')
 return [canonical(x.get('url','')) for x in r.json().get('web',{}).get('results',[]) if x.get('url')]

def objects(x):
 if isinstance(x,list):
  for v in x:yield from objects(v)
 elif isinstance(x,dict):
  types=x.get('@type',[]);types=[types] if isinstance(types,str) else types
  if 'Product' in types:yield x
  for v in x.values():yield from objects(v)

def extract_offer(offers):
 if isinstance(offers,list):offers=next((o for o in offers if isinstance(o,dict)),{})
 if not isinstance(offers,dict):return {}
 if 'offers' in offers and 'price' not in offers: return extract_offer(offers['offers'])
 return offers

def parse_price(value):
 if value is None:return None
 try:
  n=float(str(value).replace(',','').replace('$','').strip())
  return n if n>0 else None
 except (TypeError,ValueError):return None

def parse_page(url,query,upc):
 """Never assert US status merely from .com or US search ranking."""
 try:
  r=requests.get(url,headers=UA,timeout=(6,12),allow_redirects=True)
  if r.status_code!=200:return None,'HTTP '+str(r.status_code)
  if not allowed_domain(r.url):return None,'FOREIGN_DOMAIN'
  if 'html' not in r.headers.get('Content-Type','').lower():return None,'Не HTML'
  soup=BeautifulSoup(r.text[:2_000_000],'html.parser')
  candidates=[]
  for script in soup.find_all('script',type='application/ld+json'):
   try:parsed=json.loads(script.string or script.get_text() or '{}')
   except (ValueError,TypeError):continue
   for obj in objects(parsed):
    title=str(obj.get('name') or '').strip()
    offer=extract_offer(obj.get('offers'))
    upc_found=next((str(obj[k]) for k in ('gtin12','gtin13','gtin14','gtin','upc') if obj.get(k)), '')
    score,reason=match_product(query,title,upc,upc_found)
    availability=str(offer.get('availability','')).rsplit('/',1)[-1] or 'Unknown'
    condition=str(offer.get('itemCondition','')).rsplit('/',1)[-1] or ('RefurbishedCondition' if REFURB.search(title) else 'Unknown')
    # Positive evidence only: merchant postal address or shipping destination US in structured data.
    evidence=json.dumps(obj,ensure_ascii=False).lower()
    us_status='verified' if re.search(r'"addresscountry"\s*:\s*"(?:us|usa|united states)"',evidence) or re.search(r'"addresscountry"\s*:\s*\{[^}]*"name"\s*:\s*"united states"',evidence) else 'unverified'
    item={'us_status':us_status,'url':canonical(r.url),'domain':shop_domain(r.url),'title':title,'price':parse_price(offer.get('price') or offer.get('lowPrice')),'currency':str(offer.get('priceCurrency') or ''),'availability':availability,'condition':condition,'upc':upc_found,'score':score,'reason':reason}
    candidates.append(item)
  if not candidates:
   # Do not infer a sale from arbitrary mentions or prices on a page.
   return None,'Нет структурированных данных Product'
  best=max(candidates,key=lambda x:(not x['reason'],x['score'],x['price'] is not None))
  if non_us_currency(best['currency']):return None,'FOREIGN_CURRENCY'
  if not allowed_domain(r.url):return None,'FOREIGN_DOMAIN'
  return best,''
 except requests.RequestException as exc:return None,'Ошибка сети: '+type(exc).__name__


# v3.2: category pages and dynamic storefronts. Never treat a search snippet as a sale.
from urllib.parse import urlsplit
from decimal import Decimal

PRODUCT_PATH=re.compile(r'/(?:ip|p|product|products|item|dp|sku)/',re.I)
LISTING_PATH=re.compile(r'/(?:search|browse|category|categories|c/kp|collections|s\?|shop/)',re.I)
ARTICLE_PATH=re.compile(r'/(?:news|guides|reviews|blog|articles|stories|best-|how-to)/',re.I)
PRICE_PATTERN=re.compile(r'(?<!\w)\$\s*([0-9]{1,5}(?:,[0-9]{3})*(?:\.[0-9]{2})?)')

def page_html(url, dynamic=False, proxy_url=''):
    if dynamic:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser=None
                for channel in ('msedge','chrome'):
                    try:
                        browser=p.chromium.launch(channel=channel,headless=True,timeout=12000,proxy={'server':proxy_url} if proxy_url else None)
                        break
                    except Exception:pass
                if browser is None:
                    browser=p.chromium.launch(headless=True,timeout=12000,proxy={'server':proxy_url} if proxy_url else None)
                try:
                    page=browser.new_page(locale='en-US',viewport={'width':1300,'height':900})
                    page.goto(url,wait_until='domcontentloaded',timeout=16000)
                    try:page.wait_for_timeout(1400)
                    except Exception:pass
                    return page.url,page.content()
                finally:browser.close()
        except Exception:return None,None
    try:
        r=requests.get(url,headers=UA,timeout=(6,10),allow_redirects=True,proxies={'https':proxy_url,'http':proxy_url} if proxy_url else None)
        if r.status_code!=200 or 'html' not in r.headers.get('Content-Type','').lower():return None,None
        return r.url,r.text[:3_000_000]
    except requests.RequestException:return None,None

def collect_cards(soup,base,query,upc):
    found=[];seen=set()
    # Product links from listing pages, each verified on its own page later.
    for a in soup.find_all('a',href=True):
        href=urljoin(base,a['href']);norm=canonical(href)
        if not norm or not allowed_domain(norm) or shop_domain(norm)!=shop_domain(base) or norm in seen:continue
        if not PRODUCT_PATH.search(urlsplit(norm).path):continue
        label=a.get_text(' ',strip=True)
        if not label:
            img=a.find('img');label=(img.get('alt','') if img else '')
        if label:
            score,why=match_product(query,label,upc)
            if why and score<0.5:continue
        seen.add(norm);found.append(norm)
        if len(found)>=30:break
    return found

def dom_product(soup,url,query,upc):
    if ARTICLE_PATH.search(urlsplit(url).path):return None,'Информационная статья'
    title=(soup.find('h1').get_text(' ',strip=True) if soup.find('h1') else '')
    if not title:
        m=soup.find('meta',property='og:title');title=m.get('content','') if m else ''
    score,reason=match_product(query,title,upc)
    if reason:return None,reason
    # Require an actual product route and commerce cues. Never take arbitrary article prices.
    route=bool(PRODUCT_PATH.search(urlsplit(url).path))
    commerce=bool(soup.select('button[name*="cart" i], button[id*="cart" i], [data-testid*="add-to-cart" i], [itemprop="offers"]'))
    body=soup.get_text(' ',strip=True)[:35000]
    commerce=commerce or bool(re.search(r'\b(add to cart|buy now|pay in full|choose (your )?storage|delivery and pickup options)\b',body,re.I))
    if not (route and commerce):return None,'Нет подтверждения товарной карточки и покупки'
    price=None
    for meta in soup.select('[itemprop="price"], meta[property="product:price:amount"], meta[property="og:price:amount"]'):
        price=parse_price(meta.get('content') or meta.get_text(' ',strip=True))
        if price:break
    if price is None:
        match=PRICE_PATTERN.search(body)
        if match:price=parse_price(match.group(1))
    currency='USD' if price is not None else ''
    if re.search(r'€|\bEUR\b|\bGBP\b|£',body[:6000],re.I) and not re.search(r'\bUSD\b|\$',body[:6000]):return None,'FOREIGN_CURRENCY'
    condition='RefurbishedCondition' if REFURB.search(title) else 'Unknown'
    avail='InStock' if re.search(r'\b(add to cart|buy now|pay in full)\b',body,re.I) else 'Unknown'
    return {'us_status':'unverified','url':canonical(url),'domain':shop_domain(url),'title':title,'price':price,'currency':currency,'availability':avail,'condition':condition,'upc':'','score':score,'reason':''},''

def parse_page(url,query,upc,proxy_url=''):
    if not allowed_domain(url):return None,'FOREIGN_DOMAIN'
    if is_non_store(url):return None,'NOT_STORE'
    final,html_text=page_html(url,proxy_url=proxy_url)
    if not html_text:return None,'Ошибка загрузки HTML'
    if not allowed_domain(final):return None,'FOREIGN_DOMAIN'
    def inspect(final,html_text):
        soup=BeautifulSoup(html_text,'html.parser')
        items=[]
        for script in soup.find_all('script',type='application/ld+json'):
            try:obj=json.loads(script.string or script.get_text() or '{}')
            except (ValueError,TypeError):continue
            for product in objects(obj):
                title=str(product.get('name') or '').strip();offer=extract_offer(product.get('offers'))
                score,why=match_product(query,title,upc,next((str(product[k]) for k in ('gtin12','gtin13','gtin14','gtin','upc') if product.get(k)),''))
                currency=str(offer.get('priceCurrency') or '')
                if non_us_currency(currency):continue
                # Price and product JSON-LD alone are not enough on articles or collections.
                if ARTICLE_PATH.search(urlsplit(final).path):continue
                if not PRODUCT_PATH.search(urlsplit(final).path) and LISTING_PATH.search(urlsplit(final).path):continue
                item={'us_status':'unverified','url':canonical(final),'domain':shop_domain(final),'title':title,'price':parse_price(offer.get('price') or offer.get('lowPrice')),'currency':currency,'availability':str(offer.get('availability','')).rsplit('/',1)[-1] or 'Unknown','condition':str(offer.get('itemCondition','')).rsplit('/',1)[-1] or ('RefurbishedCondition' if REFURB.search(title) else 'Unknown'),'upc':'','score':score,'reason':why}
                if not why:items.append(item)
        if items:return max(items,key=lambda i:(i['price'] is not None,i['score'])),'',[]
        links=collect_cards(soup,final,query,upc)
        if links and (LISTING_PATH.search(urlsplit(final).path) or len(links)>2):return None,'Каталог: обнаружены карточки',links
        item,why=dom_product(soup,final,query,upc)
        return item,why,[]
    item,why,links=inspect(final,html_text)
    if item:return item,''
    if links:return {'_links':links},'CATALOG'
    # Browser fallback only for pages that need it; Edge/Chrome or Playwright Chromium.
    final2,html2=page_html(url,dynamic=True,proxy_url=proxy_url)
    if html2 and allowed_domain(final2):
        item,why2,links=inspect(final2,html2)
        if item:return item,''
        if links:return {'_links':links},'CATALOG'
        why=why2
    return None,why or 'Товар не подтверждён'

# Seed catalog: known retail domains, not assertions of stock or specific prices.
RETAIL_SEEDS = {
 'electronics':['apple.com','bestbuy.com','costco.com','walmart.com','target.com','bhphotovideo.com','newegg.com','microcenter.com','adorama.com','samsclub.com','t-mobile.com','att.com','verizon.com','boostmobile.com','backmarket.com'],
 'tools':['homedepot.com','lowes.com','acehardware.com','harborfreight.com','grainger.com','zoro.com','northerntool.com','tractorsupply.com','acmetools.com'],
 'clothing':['macys.com','nordstrom.com','kohls.com','gap.com','oldnavy.gap.com','zappos.com','rei.com','dickssportinggoods.com'],
 'auto':['autozone.com','oreillyauto.com','rockauto.com','advanceautoparts.com','carparts.com','napaonline.com'],
 'beauty':['ulta.com','sephora.com','target.com','walmart.com','cvs.com','walgreens.com'],
 'general':['walmart.com','target.com','amazon.com','costco.com','samsclub.com','ebay.com']
}
NON_STORE_DOMAINS={'businessinsider.com','wired.com','smartprix.com','appleinventorycheck.com','applepricehunt.com','theverge.com','cnet.com','techradar.com','tomsguide.com','gsmarena.com','reddit.com','youtube.com','pinterest.com','wikipedia.org','forbes.com','nytimes.com','androidauthority.com','phonearena.com','pcmag.com'}
def is_non_store(url):
 domain=shop_domain(url)
 return domain in NON_STORE_DOMAINS

def category_for(query):
 q=query.lower()
 if re.search(r'\b(iphone|ipad|macbook|samsung|pixel|laptop|headphone|ssd|camera|television|tv|smartphone|phone|airpods|tablet|computer|gpu|monitor)\b',q):return 'electronics'
 if re.search(r'\b(drill|saw|wrench|bosch|dewalt|makita|milwaukee|power tool|screwdriver)\b',q):return 'tools'
 if re.search(r'\b(shirt|shoe|dress|jacket|jeans|sneaker|hoodie|pants|coat)\b',q):return 'clothing'
 if re.search(r'\b(brake|filter|spark plug|car part|rotor|alternator|radiator)\b',q):return 'auto'
 if re.search(r'\b(perfume|makeup|lipstick|shampoo|skincare|cosmetic)\b',q):return 'beauty'
 return 'general'

def seeded_queries(query,upc):
 domains=list(dict.fromkeys(RETAIL_SEEDS[category_for(query)]+RETAIL_SEEDS['general']))
 term=f'"{upc}"' if upc else f'"{query}"'
 return [f'site:{domain} {term}' for domain in domains]

def make_tasks(query,upc,small):
 # Deep search uses 2 offsets per query, capped by API budget at runtime.
 return ([{'kind':'search','query':q,'offset':0} for q in seeded_queries(query,upc)] + [{'kind':'search','query':q,'offset':off} for q in queries(query,upc,small) for off in (0,1)])

def add_candidate(conn,sid,url,status='Ожидает проверки'):
 url=canonical(url)
 if not url or not allowed_domain(url) or is_non_store(url) or is_marketplace(url):return False
 exists=conn.execute('SELECT 1 FROM candidates WHERE search_id=? AND url=?',(sid,url)).fetchone()
 if exists:return False
 conn.execute('INSERT INTO candidates(search_id,url,domain,status) VALUES(?,?,?,?)',(sid,url,shop_domain(url),status))
 return True

def snapshot(conn,sid):
 job=conn.execute('SELECT api_used,processed,errors,status FROM jobs WHERE search_id=?',(sid,)).fetchone() or (0,0,0,'unknown')
 n=conn.execute('SELECT COUNT(DISTINCT domain) FROM results WHERE search_id=?',(sid,)).fetchone()[0]
 total=conn.execute('SELECT COUNT(*) FROM candidates WHERE search_id=?',(sid,)).fetchone()[0]
 return f'Магазинов {n} | Ссылок {total} | Проверено {job[1]} | Ошибок {job[2]} | API {job[0]} | {job[3]}'

def run_search(db_path,sid,key,pause,emit,workers=5,proxy_url='',proxy_brave=False):
 c=connect(db_path)
 try:
  search=c.execute('SELECT query,upc,small,api_limit,store_limit FROM searches WHERE id=?',(sid,)).fetchone()
  if not search:return
  query,upc,small,api_limit,store_limit=search
  batch=c.execute('SELECT b.id,b.api_limit,b.store_limit FROM search_batches b JOIN batch_items i ON i.batch_id=b.id WHERE i.search_id=?',(sid,)).fetchone()
  if batch:
   batch_id,batch_api_limit,batch_store_limit=batch
   already=c.execute('SELECT COALESCE(SUM(j.api_used),0) FROM jobs j JOIN batch_items i ON i.search_id=j.search_id WHERE i.batch_id=? AND i.search_id<>?',(batch_id,sid)).fetchone()[0]
   api_limit=max(0,batch_api_limit-already)
   # The store cap applies to each requested product, while Brave budget is shared.
   store_limit=batch_store_limit
  row=c.execute('SELECT queue,done,api_used,processed,errors FROM jobs WHERE search_id=?',(sid,)).fetchone()
  if not row:return
  tasks=json.loads(row[0]);done=set(json.loads(row[1]));api_used,processed,errors=row[2:]
  known_pages={t['url'] for t in tasks if t['kind']=='page'}
  c.execute("UPDATE jobs SET status='running' WHERE search_id=?",(sid,));c.commit()
  def save():
   c.execute('UPDATE jobs SET queue=?,done=?,api_used=?,processed=?,errors=? WHERE search_id=?',(json.dumps(tasks),json.dumps(sorted(done)),api_used,processed,errors,sid));c.commit()
  def ingest(url):
   url=canonical(url)
   if not url or not allowed_domain(url) or is_non_store(url) or is_marketplace(url) or url in known_pages:return
   known_pages.add(url);tasks.insert(index,{'kind':'page','url':url});add_candidate(c,sid,url)
  index=0
  # Persistent store knowledge is a hint for discovery, not proof of inventory.
  for (url,) in c.execute("SELECT last_product_url FROM stores WHERE last_product_url!='' ORDER BY last_seen DESC LIMIT 100"):
   if query_tokens(query)&query_tokens(url):ingest(url)
  save()
  with ThreadPoolExecutor(max_workers=max(1,min(5,workers))) as pool:
   pending={};index=0
   while True:
    n=c.execute('SELECT COUNT(DISTINCT domain) FROM results WHERE search_id=?',(sid,)).fetchone()[0]
    if pause.is_set() or n>=store_limit:break
    while index<len(tasks) and len(pending)<max(1,min(5,workers)) and not pause.is_set():
     task=tasks[index];index+=1
     task_id=json.dumps(task,sort_keys=True)
     if task_id in done:continue
     if task['kind']=='search':
      if api_used>=api_limit:
       done.add(task_id);continue
      api_used+=1;save()
      try:
       with requests.Session() as session:links=search_brave(session,key,task['query'],task['offset'],proxy_url if proxy_brave else '')
       for url in links:ingest(url)
       emit(f'Brave: {len(links)} ссылок | API {api_used}/{api_limit}')
      except Exception as exc:
       errors+=1;emit('Ошибка Brave: '+str(exc))
       if 'HTTP 401' in str(exc) or 'HTTP 403' in str(exc) or 'HTTP 429' in str(exc):
        pause.set();emit('Поиск приостановлен: проверьте ключ или лимит Brave')
      done.add(task_id);save()
     else:
      url=task['url']
      c.execute("UPDATE candidates SET status='Проверяется' WHERE search_id=? AND url=?",(sid,url));c.commit()
      pending[pool.submit(parse_page,url,query,upc,proxy_url)]=(task_id,url)
    if pending:
     completed,_=wait(pending,timeout=0.4,return_when=FIRST_COMPLETED)
     for future in completed:
      task_id,url=pending.pop(future)
      try:item,issue=future.result()
      except Exception as exc:item,issue=None,'Ошибка обработки: '+type(exc).__name__
      domain=shop_domain(url);reason=issue;status='Требуется проверка';title=''
      if issue=='CATALOG' and item:
       for child in item['_links']:ingest(child)
       item=None;issue='Каталог: добавлены отдельные товарные страницы'
      if issue in ('FOREIGN_CURRENCY','FOREIGN_DOMAIN','NOT_STORE'):
       c.execute('DELETE FROM candidates WHERE search_id=? AND url=?',(sid,url))
       done.add(task_id);processed+=1;save();continue
      if item:
       title=item['title'];domain=item['domain'];reason=item['reason']
       if reason:status='Отклонено'
       else:
        # Do not certify country from TLD or search locale. Mark as unverified.
        duplicate=c.execute('SELECT 1 FROM results WHERE search_id=? AND domain=?',(sid,domain)).fetchone()
        if duplicate:status='Отклонено';reason='Повтор магазина'
        else:
         status='Подтверждённый магазин' if item['us_status']=='verified' else 'Требуется проверка';reason='' if item['us_status']=='verified' else 'Не подтверждена работа продавца в США'
         c.execute('INSERT OR REPLACE INTO results(search_id,url,domain,title,price,currency,availability,condition,upc,score) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,item['url'],domain,title,item['price'],item['currency'],item['availability'],item['condition'],item['upc'],item['score']))
         if item['us_status']=='verified':c.execute('INSERT INTO stores(domain,shop_name,category_terms,last_product_url,product_count) VALUES(?,?,?,?,1) ON CONFLICT(domain) DO UPDATE SET last_seen=CURRENT_TIMESTAMP,product_count=product_count+1,last_product_url=excluded.last_product_url,category_terms=excluded.category_terms',(domain,domain,query,item['url']))
         if item['us_status']=='verified':c.execute("UPDATE stores SET us_status='evidence' WHERE domain=?",(domain,))
         emit('Товар: '+title[:75]+' | '+domain)
      if issue:errors+=1
      c.execute('UPDATE candidates SET title=?,domain=?,status=?,reason=? WHERE search_id=? AND url=?',(title,domain,status,reason,sid,url))
      done.add(task_id);processed+=1;save()
      if processed%5==0:emit(snapshot(c,sid))
    elif index>=len(tasks):break
   # If paused, wait for in-flight requests to finish; preserve their results.
   for future,(task_id,url) in list(pending.items()):
    try:item,issue=future.result(timeout=20)
    except Exception:item,issue=None,'Ошибка или тайм-аут'
    if issue=='CATALOG' and item:
     for child in item['_links']:ingest(child)
     item=None;issue='Каталог: добавлены отдельные товарные страницы'
    if issue in ('FOREIGN_CURRENCY','FOREIGN_DOMAIN','NOT_STORE'):
     c.execute('DELETE FROM candidates WHERE search_id=? AND url=?',(sid,url));done.add(task_id);processed+=1;continue
    if item and not item['reason']:
     domain=item['domain']
     if not c.execute('SELECT 1 FROM results WHERE search_id=? AND domain=?',(sid,domain)).fetchone():
      c.execute('INSERT OR REPLACE INTO results(search_id,url,domain,title,price,currency,availability,condition,upc,score) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,item['url'],domain,item['title'],item['price'],item['currency'],item['availability'],item['condition'],item['upc'],item['score']))
      if item['us_status']=='verified':c.execute('INSERT INTO stores(domain,shop_name,category_terms,last_product_url,product_count) VALUES(?,?,?,?,1) ON CONFLICT(domain) DO UPDATE SET last_seen=CURRENT_TIMESTAMP,product_count=product_count+1,last_product_url=excluded.last_product_url',(domain,domain,query,item['url']))
     status='Подтверждённый магазин' if item['us_status']=='verified' else 'Требуется проверка';reason='' if item['us_status']=='verified' else 'Не подтверждена работа продавца в США'
    else:status='Отклонено' if item else 'Требуется проверка';reason=item['reason'] if item else issue
    c.execute('UPDATE candidates SET title=?,status=?,reason=? WHERE search_id=? AND url=?',((item or {}).get('title',''),status,reason,sid,url))
    done.add(task_id);processed+=1
   save()
  n=c.execute('SELECT COUNT(DISTINCT domain) FROM results WHERE search_id=?',(sid,)).fetchone()[0]
  status='paused' if pause.is_set() else 'complete'
  c.execute('UPDATE jobs SET status=? WHERE search_id=?',(status,sid));c.commit()
  emit(snapshot(c,sid)+(' | достигнут лимит магазинов' if n>=store_limit else ''))
 finally:c.close()

def create_batch(conn,products,small,api_limit,store_limit):
 """Create a resumable batch. One job per product, one total Brave budget."""
 names=split_products(products)
 if not names:raise ValueError('Добавьте хотя бы один товар')
 if len(names)>200:raise ValueError('Максимум 200 товаров за запуск')
 cur=conn.execute('INSERT INTO search_batches(api_limit,store_limit) VALUES(?,?)',(api_limit,store_limit))
 batch_id=cur.lastrowid
 for position,name in enumerate(names):
  sid=conn.execute('INSERT INTO searches(query,upc,small,api_limit,store_limit) VALUES(?,?,?,?,?)',(name,'',int(small),api_limit,store_limit)).lastrowid
  tasks=make_tasks(name,'',small)
  conn.execute('INSERT INTO jobs(search_id,queue,done,status) VALUES(?,?,?,?)',(sid,json.dumps(tasks),'[]','new'))
  conn.execute('INSERT INTO batch_items(batch_id,search_id,position) VALUES(?,?,?)',(batch_id,sid,position))
 conn.commit()
 return batch_id

def run_batch(db_path,batch_id,key,pause,emit,workers=5,proxy_url='',proxy_brave=False):
 """Process batch sequentially; each run_search rechecks aggregate API usage."""
 c=connect(db_path)
 try:
  ids=[row[0] for row in c.execute('SELECT search_id FROM batch_items WHERE batch_id=? ORDER BY position',(batch_id,))]
  for sid in ids:
   if pause.is_set():break
   status=c.execute('SELECT status FROM jobs WHERE search_id=?',(sid,)).fetchone()
   if status and status[0]=='complete':continue
   name=c.execute('SELECT query FROM searches WHERE id=?',(sid,)).fetchone()[0]
   emit('Товар: '+name)
   run_search(db_path,sid,key,pause,emit,workers=workers,proxy_url=proxy_url,proxy_brave=proxy_brave)
   c.commit()
  c.execute('UPDATE search_batches SET status=? WHERE id=?',('paused' if pause.is_set() else 'complete',batch_id));c.commit()
 finally:c.close()
