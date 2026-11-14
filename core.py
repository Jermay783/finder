"""Finder: US store discovery with conservative verification."""
import re,sqlite3,urllib.parse,threading,json,time,concurrent.futures
import requests,bs4,tldextract
US_DOMAINS={'com','us','shop','store','net','org','io'}
FOREIGN={'fr','de','uk','au','ca','it','es','nl','jp','cn','ru','br','in','mx'}
BLOCK={'wired.com','businessinsider.com','theverge.com','cnet.com','reddit.com','youtube.com','amazon.com','ebay.com','google.com','bing.com','pricerunner.com'}
SEEDS={'electronics':['apple.com','bestbuy.com','costco.com','walmart.com','target.com','bhphotovideo.com','newegg.com','t-mobile.com','verizon.com','att.com','samsclub.com','microcenter.com'],'tools':['homedepot.com','lowes.com','acehardware.com','harborfreight.com','grainger.com'],'general':['walmart.com','target.com','costco.com','samsclub.com','bestbuy.com']}
def connect(path):
 c=sqlite3.connect(path,timeout=30)
 c.executescript("""CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY,query TEXT,upc TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
 CREATE TABLE IF NOT EXISTS results(search_id INTEGER,url TEXT,domain TEXT,title TEXT,price TEXT,status TEXT,reason TEXT,PRIMARY KEY(search_id,url));
 CREATE TABLE IF NOT EXISTS stores(domain TEXT PRIMARY KEY);""")
 return c
def canonical(url):
 p=urllib.parse.urlsplit(url); q=urllib.parse.parse_qsl(p.query);q=[(k,v) for k,v in q if not k.lower().startswith(('utm_','fbclid','gclid'))]
 return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urllib.parse.urlencode(q),''))
def shop_domain(url):
 host=urllib.parse.urlsplit(url).hostname or ''
 x=tldextract.extract(host);return '.'.join(z for z in (x.domain,x.suffix) if z)
def allowed_domain(url):
 host=urllib.parse.urlsplit(url).hostname or '';x=tldextract.extract(host)
 return bool(x.domain and x.suffix and x.suffix.split('.')[-1] not in FOREIGN)
def non_us_currency(s):return bool(s and s.upper() not in ('USD','US$','$'))
def gtin_valid(s):
 s=re.sub(r'\D','',s)
 return len(s) in (8,12,13,14) and (10-sum(int(n)*(3 if i%2 else 1) for i,n in enumerate(s[-2::-1]))%10)%10==int(s[-1])
def match_product(query,title,upc='',found_upc=''):
 q=re.findall(r'[a-z0-9]+',query.lower());t=title.lower()
 if upc and found_upc and upc!=found_upc:return 0,'UPC не совпадает'
 if re.search(r'\b(case|cover|protector|charger|cable|adapter|screen guard)\b',t) and not re.search(r'\b(case|cover|protector|charger|cable|adapter)\b',query.lower()):return 0,'Аксессуар'
 if 'iphone' in query.lower():
  for token in ('pro max','pro','plus'):
   if (token in query.lower())!=(token in t):return 0,'Другая модель'
 missing=[x for x in q if x not in re.findall(r'[a-z0-9]+',t)]
 return (1,'') if not missing else (0,'Не совпадает модель: '+', '.join(missing))
def category_for(q):
 q=q.lower()
 if any(x in q for x in ('iphone','ipad','macbook','laptop','phone','samsung','pixel','airpods')):return 'electronics'
 if any(x in q for x in ('drill','dewalt','bosch','milwaukee','tool')):return 'tools'
 return 'general'
def seeded_queries(q,upc):
 return ['site:'+d+' '+(upc or q) for d in SEEDS[category_for(q)]]
def make_tasks(q,upc,small):
 seeds=seeded_queries(q,upc);extra=[q+' buy online USA',q+' in stock USD',q+' shop',q+' official store',q+' purchase United States']
 if small:extra += [q+' independent retailer USA',q+' authorized dealer US',q+' small business store']
 return [{'query':x,'offset':i} for i,x in enumerate(seeds+extra*5)]
def is_non_store(url):
 d=shop_domain(url);return d in BLOCK or any(x in urllib.parse.urlsplit(url).path.lower() for x in ('/news/','/review/','/article/','/blog/'))
def search_brave(session,key,q):
 r=session.get('https://api.search.brave.com/res/v1/web/search',params={'q':q,'count':20},headers={'X-Subscription-Token':key,'Accept':'application/json'},timeout=25);r.raise_for_status()
 return r.json().get('web',{}).get('results',[])
def verify(url,query):
 try:
  r=requests.get(url,headers={'User-Agent':'Mozilla/5.0 Finder/1.0'},timeout=16);r.raise_for_status()
  soup=bs4.BeautifulSoup(r.text,'html.parser');title=(soup.title.get_text(' ',strip=True) if soup.title else '')
  for s in soup.select('script[type="application/ld+json"]'):
   try:
    data=json.loads(s.string or s.get_text())
    stack=[data]
    while stack:
     x=stack.pop()
     if isinstance(x,list):stack+=x;continue
     if not isinstance(x,dict):continue
     stack.extend(v for v in x.values() if isinstance(v,(dict,list)))
     if 'Product' in str(x.get('@type','')):
      title=x.get('name',title);offers=x.get('offers',{})
      if isinstance(offers,list):offers=offers[0] if offers else {}
      currency=offers.get('priceCurrency','') if isinstance(offers,dict) else ''
      if non_us_currency(currency):return title,'Отклонено','Валюта не USD'
      score,why=match_product(query,title)
      return title,'Подтверждённый магазин' if score else 'Отклонено',why or 'Product schema'
   except (ValueError,TypeError,AttributeError):pass
  score,why=match_product(query,title)
  return title,'Требуется проверка' if score else 'Отклонено',why or 'Нет подтверждённой товарной карточки'
 except Exception as e:return '','Требуется проверка','Ошибка загрузки: '+type(e).__name__
def run_search(path,sid,key,pause,emit,workers=5):
 c=connect(path);q,upc=c.execute('SELECT query,upc FROM searches WHERE id=?',(sid,)).fetchone();seen=set();session=requests.Session()
 for task in make_tasks(q,upc,True)[:100]:
  if pause.is_set():break
  try:items=search_brave(session,key,task['query'])
  except Exception as e:emit('Brave: '+str(e));continue
  for item in items:
   if pause.is_set():break
   url=canonical(item.get('url',''))
   if not url.startswith('http') or url in seen:continue
   seen.add(url);domain=shop_domain(url)
   if not allowed_domain(url) or is_non_store(url):status,reason,title='Отклонено','Не магазин США',item.get('title','')
   else:title,status,reason=verify(url,q)
   c.execute('INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?,?)',(sid,url,domain,title,'',status,reason));c.execute('INSERT OR IGNORE INTO stores VALUES(?)',(domain,));c.commit()
  emit('Проверено ссылок: '+str(len(seen)))
  if c.execute("SELECT COUNT(DISTINCT domain) FROM results WHERE search_id=? AND status='Подтверждённый магазин'",(sid,)).fetchone()[0]>=30:break
 c.close()
def snapshot(c,sid):
 rows=c.execute('SELECT status,COUNT(*) FROM results WHERE search_id=? GROUP BY status',(sid,)).fetchall()
 return ' | '.join('%s: %s'%x for x in rows) or 'Пока нет результатов'
