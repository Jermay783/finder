"""Windows GUI for US Store Finder 3."""
import os, sys, json, threading, queue, webbrowser, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlsplit, quote
import requests
import keyring
from core import connect,make_tasks,run_search,snapshot

BASE=os.path.join(os.environ.get('LOCALAPPDATA',os.path.expanduser('~')),'USStoreFinder3')
os.makedirs(BASE,exist_ok=True)
DB=os.path.join(BASE,'store_finder.sqlite3')

class App:
 def __init__(self,root):
  self.root=root;root.title('Finder 3.5.2');root.geometry('1380x880');root.minsize(1050,700)
  self.configure_theme()
  self.conn=connect(DB);self.q=queue.Queue();self.pause=threading.Event();self.worker=None;self.current=None
  self.query=tk.StringVar();self.upc=tk.StringVar();self.key=tk.StringVar();self.small=tk.BooleanVar(value=True)
  self.show_key=tk.BooleanVar(value=False);self.limit=tk.IntVar(value=30);self.budget=tk.IntVar(value=100)
  self.minprice=tk.StringVar();self.maxprice=tk.StringVar();self.stock=tk.BooleanVar();self.newonly=tk.BooleanVar()
  self.progress=tk.StringVar(value='Готов к поиску');self.entries={};self.ids={}
  self.proxy_enabled=tk.BooleanVar(value=False);self.proxy_brave=tk.BooleanVar(value=False);self.proxy_url=tk.StringVar()
  self.proxy_protocol=tk.StringVar(value='http')
  self.load_proxy_config()
  self.load_app_settings()
  sidebar=ttk.Frame(root,style='Sidebar.TFrame',padding=18);sidebar.pack(side='left',fill='y')
  ttk.Label(sidebar,text='FINDER',style='Brand.TLabel').pack(anchor='w',pady=(8,32))
  for label,page in [('Поиск товаров','search'),('История','history'),('Мои магазины','shops'),('Настройки','settings'),('Обновления','updates')]:
   ttk.Button(sidebar,text=label,style='Nav.TButton',command=lambda p=page:self.show_page(p)).pack(fill='x',pady=5)
  ttk.Label(sidebar,text='Версия 3.5.2',style='Muted.TLabel').pack(side='bottom',anchor='w',pady=12)
  content=ttk.Frame(root,padding=22);content.pack(side='left',fill='both',expand=True)
  self.pages={}
  for name in ('search','history','shops','settings','updates'):
   frame=ttk.Frame(content);self.pages[name]=frame
  search=self.pages['search']
  ttk.Label(search,text='Поиск магазинов',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
  top=ttk.Frame(search,padding=10);top.pack(fill='x')
  ttk.Label(top,text='Название товара или точная модель').pack(anchor='w',pady=(0,6))
  line=ttk.Frame(top);line.pack(fill='x')
  self.query_entry=ttk.Entry(line,textvariable=self.query);self.query_entry.pack(side='left',fill='x',expand=True)
  self.edit_menu(self.query_entry)
  ttk.Button(line,text='Найти магазины',style='Primary.TButton',command=self.start).pack(side='left',padx=(10,0))
  bar=ttk.Frame(search);bar.pack(fill='x',pady=12)
  for label,fn in [('Пауза',self.stop),('Продолжить',self.resume),('Сохранить TXT',self.export)]:
   ttk.Button(bar,text=label,command=fn).pack(side='left',padx=(0,8))
  filt=ttk.Frame(search);filt.pack(fill='x',pady=(0,12))
  for label,var in [('Цена от',self.minprice),('Цена до',self.maxprice)]:
   ttk.Label(filt,text=label).pack(side='left');ttk.Entry(filt,textvariable=var,width=11).pack(side='left',padx=8)
  self.toggle(filt,'Только в наличии',self.stock,self.refresh).pack(side='left',padx=10)
  self.toggle(filt,'Только новые',self.newonly,self.refresh).pack(side='left',padx=10)
  ttk.Button(filt,text='Применить',command=self.refresh).pack(side='left',padx=8)
  right=ttk.Frame(search);right.pack(fill='both',expand=True)
  ttk.Label(right,text='Подтверждённые товары').pack(anchor='w',pady=(0,6))
  columns=('domain','title','price','availability','condition','score','us')
  self.table=ttk.Treeview(right,columns=columns,show='headings',height=11)
  labels={'domain':'Магазин','title':'Товар','price':'Цена','availability':'Наличие','condition':'Состояние','score':'Оценка','us':'США'}
  for name,width in [('domain',145),('title',330),('price',100),('availability',100),('condition',110),('score',65),('us',120)]:self.table.heading(name,text=labels[name]);self.table.column(name,width=width,minwidth=60,stretch=name=='title')
  self.table.pack(fill='both',expand=True);self.table.bind('<Double-1>',lambda e:self.open_url(self.table))
  tools=ttk.Frame(right);tools.pack(fill='x',pady=7)
  ttk.Button(tools,text='Детали проверки',command=self.open_diagnostics).pack(side='left',padx=(0,8))
  ttk.Button(tools,text='Сохранить выбранный магазин',command=self.save_selected_shop).pack(side='left',padx=(0,8))
  ttk.Button(tools,text='Сохранить все найденные',command=self.save_all_shops).pack(side='left')
  self.diagnostics=tk.Toplevel(root);self.diagnostics.title('Finder — детали проверки');self.diagnostics.geometry('1050x600');self.diagnostics.withdraw()
  self.diagnostics.protocol('WM_DELETE_WINDOW',self.diagnostics.withdraw)
  ttk.Label(self.diagnostics,text='Все найденные ссылки и причины отклонения').pack(anchor='w',padx=12,pady=10)
  
  self.candidates=ttk.Treeview(self.diagnostics,columns=('domain','title','status','reason'),show='headings',height=9)
  labels={'domain':'Магазин','title':'Страница','status':'Статус','reason':'Причина отклонения'}
  for name,width in [('domain',150),('title',270),('status',220),('reason',320)]:self.candidates.heading(name,text=labels[name]);self.candidates.column(name,width=width,minwidth=75,stretch=name in ('title','reason'))
  self.candidates.pack(fill='both',expand=True);self.candidates.bind('<Double-1>',lambda e:self.open_url(self.candidates))
  ttk.Label(search,textvariable=self.progress).pack(anchor='w',padx=9)
  self.log=tk.Text(search,height=4,state='disabled',bg='#171B22',fg='#C6CDD7',insertbackground='#FFFFFF',relief='flat',font=('Segoe UI',10));self.log.pack(fill='x',padx=9,pady=(0,9))
  self.build_secondary_pages()
  self.show_page('search')
  self.load_history();root.after(350,self.poll)
  root.after(800,self.report_update_result)
 def show_page(self,name):
  for frame in self.pages.values():frame.pack_forget()
  self.pages[name].pack(fill='both',expand=True)
  if name=='history':self.load_history()
  if name=='shops':self.load_saved_shops()
  if name=='search':self.query_entry.focus_set()
 def toggle(self,parent,label,var,command=None):
  widget=ttk.Checkbutton(parent,text=label,variable=var,style='Switch.TCheckbutton',command=command)
  return widget
 def build_secondary_pages(self):
  history=self.pages['history']
  ttk.Label(history,text='История поисков',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
  searchrow=ttk.Frame(history);searchrow.pack(fill='x',pady=(0,10))
  self.history_filter=tk.StringVar()
  ttk.Label(searchrow,text='Найти поиск:').pack(side='left',padx=(0,8))
  history_input=ttk.Entry(searchrow,textvariable=self.history_filter)
  history_input.pack(side='left',fill='x',expand=True);self.edit_menu(history_input)
  self.history_filter.trace_add('write',lambda *_:self.load_history())
  body=ttk.Panedwindow(history,orient='horizontal');body.pack(fill='both',expand=True)
  left=ttk.Frame(body);right_history=ttk.Frame(body)
  body.add(left,weight=1);body.add(right_history,weight=3)
  self.history=ttk.Treeview(left,columns=('query','date','count'),show='headings',selectmode='browse')
  for key,label,width in [('query','Товар',175),('date','Дата',100),('count','Магазины',85)]:
   self.history.heading(key,text=label);self.history.column(key,width=width,minwidth=60)
  self.history.pack(fill='both',expand=True,padx=(0,10))
  self.history.bind('<<TreeviewSelect>>',self.select_history)
  ttk.Label(right_history,text='Результаты выбранного поиска',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
  self.history_results=ttk.Treeview(right_history,columns=('domain','title','price'),show='headings')
  for key,label,width in [('domain','Магазин',150),('title','Товар',280),('price','Цена',100)]:
   self.history_results.heading(key,text=label);self.history_results.column(key,width=width)
  self.history_results.pack(fill='both',expand=True)
  self.history_results.bind('<Double-1>',lambda e:self.open_url(self.history_results))
  history_actions=ttk.Frame(right_history);history_actions.pack(fill='x',pady=10)
  ttk.Button(history_actions,text='Повторить поиск',command=self.repeat_history).pack(side='left',padx=(0,8))
  ttk.Button(history_actions,text='Экспорт TXT',command=self.export_history).pack(side='left',padx=(0,8))
  ttk.Button(history_actions,text='Удалить из истории',command=self.delete_history).pack(side='left')
  shops=self.pages['shops']
  ttk.Label(shops,text='Мои магазины',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
  ttk.Label(shops,text='Только магазины, которые вы сохранили на этом компьютере').pack(anchor='w',pady=(0,10))
  self.saved_shops=ttk.Treeview(shops,columns=('domain','date','products'),show='headings')
  for key,label,width in [('domain','Магазин',230),('date','Добавлен',145),('products','Найденных товаров',155)]:
   self.saved_shops.heading(key,text=label);self.saved_shops.column(key,width=width)
  self.saved_shops.pack(fill='both',expand=True)
  shop_actions=ttk.Frame(shops);shop_actions.pack(fill='x',pady=10)
  ttk.Button(shop_actions,text='Открыть сайт',command=self.open_saved_shop).pack(side='left',padx=(0,8))
  ttk.Button(shop_actions,text='Удалить',command=self.remove_saved_shop).pack(side='left',padx=(0,8))
  ttk.Button(shop_actions,text='Экспорт CSV',command=self.export_shops).pack(side='left')
  settings=self.pages['settings']
  ttk.Label(settings,text='Настройки',style='Heading.TLabel').pack(anchor='w',pady=(0,18))
  ttk.Label(settings,text='Brave Search API Key').pack(anchor='w')
  keyrow=ttk.Frame(settings);keyrow.pack(fill='x',pady=(6,14))
  self.key_entry=ttk.Entry(keyrow,textvariable=self.key,show='*');self.key_entry.pack(side='left',fill='x',expand=True)
  self.edit_menu(self.key_entry)
  self.toggle(settings,'Показать API-ключ',self.show_key,lambda:self.key_entry.configure(show='' if self.show_key.get() else '*')).pack(anchor='w',pady=6)
  self.toggle(settings,'Дополнительный поиск небольших магазинов',self.small).pack(anchor='w',pady=8)
  for label,var,low,high in [('Лимит магазинов',self.limit,1,200),('Максимум запросов Brave API',self.budget,1,500)]:
   row=ttk.Frame(settings);row.pack(anchor='w',pady=8)
   ttk.Label(row,text=label,width=32).pack(side='left')
   ttk.Spinbox(row,from_=low,to=high,textvariable=var,width=9).pack(side='left')
  ttk.Button(settings,text='Сохранить настройки',style='Primary.TButton',command=self.save_app_settings).pack(anchor='w',pady=15)
  ttk.Separator(settings).pack(fill='x',pady=14)
  ttk.Label(settings,text='Сеть и прокси',style='Heading.TLabel').pack(anchor='w',pady=(0,10))
  self.toggle(settings,'Использовать прокси для магазинов',self.proxy_enabled).pack(anchor='w',pady=4)
  self.toggle(settings,'Также для Brave API',self.proxy_brave).pack(anchor='w',pady=4)
  ttk.Label(settings,text='Протокол').pack(anchor='w',pady=(12,4))
  ttk.Combobox(settings,textvariable=self.proxy_protocol,values=('http','https','socks5','socks5h'),state='readonly',width=14).pack(anchor='w')
  ttk.Label(settings,text='Адрес прокси (host:port:login:password или login:password@host:port)').pack(anchor='w',pady=(12,4))
  self.proxy_entry=ttk.Entry(settings,textvariable=self.proxy_url,show='*');self.proxy_entry.pack(fill='x');self.edit_menu(self.proxy_entry)
  self.proxy_status=tk.StringVar(value='Пароль прокси сохраняется только в защищённом хранилище Windows')
  ttk.Label(settings,textvariable=self.proxy_status).pack(anchor='w',pady=8)
  proxybar=ttk.Frame(settings);proxybar.pack(anchor='w',pady=8)
  ttk.Button(proxybar,text='Проверить прокси',command=self.test_proxy).pack(side='left',padx=(0,8))
  ttk.Button(proxybar,text='Сохранить прокси',command=self.save_proxy_ui).pack(side='left')
  updates=self.pages['updates']
  ttk.Label(updates,text='Обновления',style='Heading.TLabel').pack(anchor='w',pady=(0,15))
  ttk.Label(updates,text='Текущая версия Finder: 3.5.2').pack(anchor='w',pady=8)
  ttk.Button(updates,text='Проверить обновления',style='Primary.TButton',command=self.check_updates).pack(anchor='w',pady=8)
 def load_app_settings(self):
  try:
   with open(os.path.join(BASE,'settings.json'),encoding='utf-8') as file:data=json.load(file)
   self.limit.set(int(data.get('limit',30)));self.budget.set(int(data.get('budget',100)));self.small.set(bool(data.get('small',True)))
  except (OSError,ValueError,TypeError):pass
  try:self.key.set(keyring.get_password('Finder','brave_api_key') or '')
  except Exception:pass
 def save_app_settings(self):
  try:
   keyring.set_password('Finder','brave_api_key',self.key.get().strip()) if self.key.get().strip() else keyring.delete_password('Finder','brave_api_key')
   with open(os.path.join(BASE,'settings.json'),'w',encoding='utf-8') as file:json.dump({'limit':int(self.limit.get()),'budget':int(self.budget.get()),'small':bool(self.small.get())},file)
   messagebox.showinfo('Finder','Настройки сохранены')
  except Exception as exc:messagebox.showerror('Настройки',str(exc))
 def save_proxy_ui(self):
  try:self.save_proxy_config();messagebox.showinfo('Прокси','Настройки прокси сохранены')
  except Exception as exc:messagebox.showerror('Прокси',str(exc))
 def test_proxy(self):
  try:
   url=self.normalized_proxy()
   if not url:raise ValueError('Укажи адрес прокси')
  except Exception as exc:return messagebox.showerror('Прокси',str(exc))
  self.proxy_status.set('Проверка соединения...')
  def work():
   try:
    response=requests.get('https://api.ipify.org?format=json',timeout=15,proxies={'http':url,'https':url})
    response.raise_for_status()
    status='Прокси работает. IP: '+str(response.json().get('ip','не определён'))
   except Exception as exc:status='Проверка не прошла: '+type(exc).__name__
   self.root.after(0,lambda:self.proxy_status.set(status))
  threading.Thread(target=work,daemon=True).start()
 def report_update_result(self):
  """Show a one-time confirmation after a verified self-update."""
  import hashlib
  import pathlib
  marker=pathlib.Path(os.environ.get('LOCALAPPDATA',os.path.expanduser('~')))/'Finder'/'update-success.txt'
  if not marker.is_file() or not getattr(sys,'frozen',False):return
  try:
   expected=marker.read_text(encoding='ascii').strip().lower()
   actual=hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest().lower()
   if expected==actual:
    marker.unlink(missing_ok=True)
    messagebox.showinfo('Finder','Обновление успешно установлено. Текущая версия: 3.5.2')
  except OSError:
   pass
 def configure_theme(self):
  self.root.configure(bg='#171B22')
  style=ttk.Style(self.root)
  style.theme_use('clam')
  style.configure('.',font=('Segoe UI',10),background='#20252D',foreground='#E8EEFF')
  style.configure('TFrame',background='#20252D')
  style.configure('Sidebar.TFrame',background='#171B22')
  style.configure('TLabel',background='#20252D',foreground='#E8EEFF')
  style.configure('Muted.TLabel',background='#171B22',foreground='#8F9AB2',font=('Segoe UI',9))
  style.configure('Brand.TLabel',background='#171B22',foreground='#F1F3F6',font=('Segoe UI Semibold',17))
  style.configure('Heading.TLabel',background='#20252D',foreground='#F4F0FF',font=('Segoe UI Semibold',19))
  style.configure('Nav.TButton',background='#171B22',foreground='#DCE1E8',padding=(16,12),anchor='w',borderwidth=0)
  style.map('Nav.TButton',background=[('active','#303742')])
  style.configure('Primary.TButton',background='#DCE1E8',foreground='#171B22',padding=(16,11))
  style.map('Primary.TButton',background=[('active','#FFFFFF')],foreground=[('active','#171B22')])
  style.configure('Switch.TCheckbutton',indicatorcolor='#56616E',background='#20252D',foreground='#E5E8EE')
  style.configure('TButton',background='#303742',foreground='#F4F0FF',padding=(11,7),borderwidth=0)
  style.map('TButton',background=[('active','#47505C'),('pressed','#56616E')],foreground=[('disabled','#71798A')])
  style.configure('TEntry',fieldbackground='#1C2437',foreground='#FFFFFF',insertcolor='#FFFFFF',bordercolor='#3C4761',padding=5)
  style.configure('TSpinbox',fieldbackground='#1C2437',foreground='#FFFFFF',arrowcolor='#F1F3F6')
  style.configure('TCheckbutton',background='#20252D',foreground='#DFE6FA')
  style.map('TCheckbutton',background=[('active','#20252D')])
  style.configure('Treeview',background='#20252D',fieldbackground='#20252D',foreground='#E4EAF8',rowheight=29,borderwidth=0)
  style.map('Treeview',background=[('selected','#47505C')])
  style.configure('Treeview.Heading',background='#303742',foreground='#F2F4FF',font=('Segoe UI Semibold',10),padding=7)
  style.configure('TPanedwindow',background='#20252D')
  style.configure('TScrollbar',background='#303851')
 def normalized_proxy(self):
  raw=self.proxy_url.get().strip()
  if not raw:return ''
  scheme=self.proxy_protocol.get().lower()
  if '://' in raw:
   parsed=urlsplit(raw);scheme=parsed.scheme.lower()
   if scheme not in ('http','https','socks5','socks5h'):raise ValueError('Неподдерживаемый протокол')
   if not parsed.hostname or not parsed.port:raise ValueError('Неверный адрес прокси')
   return raw
  if '@' in raw:
   auth,hostport=raw.rsplit('@',1)
   if ':' not in auth:raise ValueError('Нужны логин и пароль')
   login,password=auth.split(':',1)
   host,port=hostport.rsplit(':',1)
  else:
   fields=raw.split(':')
   if len(fields)==4:host,port,login,password=fields
   elif len(fields)==2:host,port=fields;login=password=''
   else:raise ValueError('Формат: host:port:login:password')
  if not host or not port.isdigit() or not (1<=int(port)<=65535):raise ValueError('Неверный сервер или порт')
  auth=(quote(login,safe='')+':'+quote(password,safe='')+'@') if login else ''
  return scheme+'://'+auth+host+':'+port
 def load_proxy_config(self):
  try:
   with open(os.path.join(BASE,'network.json'),encoding='utf-8') as file:data=json.load(file)
   self.proxy_enabled.set(bool(data.get('enabled',False)))
   self.proxy_brave.set(bool(data.get('brave',False)))
   self.proxy_protocol.set(data.get('protocol','http'))
  except (OSError,ValueError,TypeError):pass
  try:self.proxy_url.set(keyring.get_password('Finder','proxy') or '')
  except Exception:pass
 def save_proxy_config(self):
  url=self.normalized_proxy()
  if self.proxy_enabled.get() and not url:raise ValueError('Укажи адрес прокси')
  if self.proxy_url.get().strip():keyring.set_password('Finder','proxy',self.proxy_url.get().strip())
  else:
   try:keyring.delete_password('Finder','proxy')
   except Exception:pass
  with open(os.path.join(BASE,'network.json'),'w',encoding='utf-8') as file:
   json.dump({'enabled':self.proxy_enabled.get(),'brave':self.proxy_brave.get(),'protocol':self.proxy_protocol.get()},file)
 def open_proxy_settings(self):
  self.show_page('settings')
 def check_updates(self):
  import updater
  def callback(status, detail):
   self.root.after(0,lambda:self.update_response(status,detail))
  updater.update_async(callback)
 def update_response(self,status,detail):
  if status=='up-to-date':return messagebox.showinfo('Finder','Установлена актуальная версия')
  if status=='error':return messagebox.showerror('Finder','Не удалось проверить обновления: '+str(detail))
  if not messagebox.askyesno('Finder','Доступна версия '+str(detail)+'. Скачать и установить?'):return
  import updater
  def worker():
   try:
    release,asset=updater.check_update()
    binary=updater.download_verified(release,asset)
    updater.install_after_exit(binary)
    self.root.after(0,self.root.destroy)
   except Exception as exc:self.root.after(0,lambda e=str(exc):messagebox.showerror('Finder','Ошибка обновления: '+e))
  threading.Thread(target=worker,daemon=True).start()
 def paste(self,entry):
  try:value=self.root.clipboard_get()
  except tk.TclError:return messagebox.showwarning('Буфер обмена','Сначала скопируйте текст')
  entry.focus_set()
  try:entry.delete('sel.first','sel.last')
  except tk.TclError:pass
  entry.insert('insert',value.strip())
 def edit_menu(self,entry):
  menu=tk.Menu(entry,tearoff=False)
  menu.add_command(label='Вставить',command=lambda:self.paste(entry))
  menu.add_command(label='Копировать',command=lambda:entry.event_generate('<<Copy>>'))
  menu.add_command(label='Выделить всё',command=lambda:(entry.focus_set(),entry.selection_range(0,'end')))
  entry.bind('<Button-3>',lambda e:(menu.tk_popup(e.x_root,e.y_root),menu.grab_release()))
  for key in ('<Control-v>','<Control-V>','<Control-Cyrillic_em>','<Shift-Insert>'):
   entry.bind(key,lambda e:(self.paste(entry),'break')[1])
  # Physical V key on Windows has keycode 86 even with a Cyrillic layout.
  def ctrl_paste(event):
   if (event.state & 0x4) and event.keycode==86:
    self.paste(entry)
    return 'break'
  entry.bind('<Control-KeyPress>',ctrl_paste,add='+')
 def open_diagnostics(self):
  self.diagnostics.deiconify();self.diagnostics.lift()
 def load_history(self):
  if not hasattr(self,'history'):return
  self.history.delete(*self.history.get_children())
  term=self.history_filter.get().lower().strip()
  rows=self.conn.execute('SELECT s.id,s.query,s.created,COUNT(DISTINCT r.domain) FROM searches s LEFT JOIN results r ON r.search_id=s.id GROUP BY s.id ORDER BY s.id DESC')
  for sid,name,date,count in rows:
   if term and term not in name.lower():continue
   self.history.insert('','end',iid=str(sid),values=(name,date[:16],count))
 def select_history(self,event=None):
  selected=self.history.selection()
  if not selected:return
  sid=int(selected[0]);self.history_selected=sid
  self.history_results.delete(*self.history_results.get_children())
  for url,domain,title,price,currency in self.conn.execute('SELECT url,domain,title,price,currency FROM results WHERE search_id=?',(sid,)):
   self.history_results.insert('','end',iid=url,values=(domain,title,f'{price} {currency}' if price is not None else '—'))
 def repeat_history(self):
  sid=getattr(self,'history_selected',None)
  if sid is None:return
  row=self.conn.execute('SELECT query FROM searches WHERE id=?',(sid,)).fetchone()
  if row:self.query.set(row[0]);self.show_page('search')
 def export_history(self):
  sid=getattr(self,'history_selected',None)
  if sid is None:return
  path=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=[('Text','*.txt')])
  if not path:return
  with open(path,'w',encoding='utf-8') as out:
   for url,domain,title,price,currency in self.conn.execute('SELECT url,domain,title,price,currency FROM results WHERE search_id=?',(sid,)):
    out.write(f'{domain} | {title} | {price or "—"} {currency}\\n{url}\\n\\n')
 def delete_history(self):
  sid=getattr(self,'history_selected',None)
  if sid is None or not messagebox.askyesno('История','Удалить этот поиск и его результаты?'):return
  for table in ('results','candidates','jobs'):self.conn.execute(f'DELETE FROM {table} WHERE search_id=?',(sid,))
  self.conn.execute('DELETE FROM searches WHERE id=?',(sid,));self.conn.commit()
  self.history_selected=None;self.history_results.delete(*self.history_results.get_children());self.load_history()
 def save_selected_shop(self):
  selected=self.table.selection()
  if not selected:return messagebox.showinfo('Мои магазины','Выберите магазин в таблице')
  domain=self.table.item(selected[0],'values')[0]
  self.conn.execute('INSERT OR IGNORE INTO saved_shops(domain) VALUES(?)',(domain,));self.conn.commit()
  messagebox.showinfo('Мои магазины',f'{domain} сохранён локально')
 def save_all_shops(self):
  domains={self.table.item(i,'values')[0] for i in self.table.get_children()}
  for domain in domains:self.conn.execute('INSERT OR IGNORE INTO saved_shops(domain) VALUES(?)',(domain,))
  self.conn.commit();messagebox.showinfo('Мои магазины',f'Сохранено магазинов: {len(domains)}')
 def load_saved_shops(self):
  self.saved_shops.delete(*self.saved_shops.get_children())
  for domain,date,count in self.conn.execute('SELECT s.domain,s.saved_at,COUNT(r.url) FROM saved_shops s LEFT JOIN results r ON r.domain=s.domain GROUP BY s.domain ORDER BY s.saved_at DESC'):
   self.saved_shops.insert('','end',iid=domain,values=(domain,date[:16],count))
 def open_saved_shop(self):
  for domain in self.saved_shops.selection():webbrowser.open('https://'+domain)
 def remove_saved_shop(self):
  for domain in self.saved_shops.selection():self.conn.execute('DELETE FROM saved_shops WHERE domain=?',(domain,))
  self.conn.commit();self.load_saved_shops()
 def export_shops(self):
  import csv
  path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')])
  if not path:return
  with open(path,'w',encoding='utf-8-sig',newline='') as out:
   writer=csv.writer(out);writer.writerow(('Домен','Дата сохранения'))
   writer.writerows(self.conn.execute('SELECT domain,saved_at FROM saved_shops ORDER BY saved_at DESC'))
 def start(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning('Поиск','Сначала дождитесь остановки текущего поиска')
  if not self.query.get().strip() or not self.key.get().strip():return messagebox.showerror('Ошибка','Введите товар и Brave API key')
  try:limit=max(1,int(self.limit.get()));budget=max(1,int(self.budget.get()))
  except (ValueError,tk.TclError):return messagebox.showerror('Ошибка','Некорректные лимиты')
  c=self.conn;c.execute('INSERT INTO searches(query,upc,small,api_limit,store_limit) VALUES(?,?,?,?,?)',(self.query.get().strip(),'',int(self.small.get()),budget,limit))
  self.current=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  tasks=make_tasks(self.query.get().strip(),self.upc.get().strip(),self.small.get())
  c.execute('INSERT INTO jobs(search_id,queue,done,status) VALUES(?,?,?,?)',(self.current,json.dumps(tasks),'[]','new'));c.commit()
  self.load_history();self.refresh();self.show_page('search');self.launch()
 def launch(self):
  if self.worker and self.worker.is_alive():return
  if self.current is None:return
  if not self.key.get().strip():return messagebox.showerror('Brave','Введите API-ключ')
  self.pause.clear();sid=self.current;key=self.key.get().strip()
  self.worker=threading.Thread(target=self.background,args=(sid,key),daemon=True);self.worker.start()
 def background(self,sid,key):
  try:run_search(DB,sid,key,self.pause,lambda msg:self.q.put(msg),workers=5,proxy_url=self.normalized_proxy() if self.proxy_enabled.get() else '',proxy_brave=self.proxy_brave.get())
  except Exception as exc:self.q.put('Ошибка: '+str(exc))
  self.q.put('__DONE__')
 def stop(self):self.pause.set();self.q.put('Останавливаемся после текущих запросов...')
 def resume(self):self.launch()
 def refresh(self):
  self.table.delete(*self.table.get_children());self.candidates.delete(*self.candidates.get_children())
  if self.current is None:return
  for url,domain,title,price,currency,availability,condition,score in self.conn.execute('SELECT url,domain,title,price,currency,availability,condition,score FROM results WHERE search_id=? ORDER BY score DESC',(self.current,)):
   try:
    if self.minprice.get().strip() and (price is None or price<float(self.minprice.get())):continue
    if self.maxprice.get().strip() and (price is None or price>float(self.maxprice.get())):continue
   except ValueError:continue
   if self.stock.get() and availability.lower() not in ('instock','limitedavailability'):continue
   if self.newonly.get() and condition.lower() not in ('newcondition','new'):continue
   status=self.conn.execute('SELECT us_status FROM stores WHERE domain=?',(domain,)).fetchone()
   us='Есть свидетельство' if status and status[0]=='evidence' else 'Не проверено'
   self.table.insert('','end',iid=url,values=(domain,title,(str(price)+' '+currency) if price is not None else '—',availability,condition,score,us))
  for url,domain,title,status,reason in self.conn.execute('SELECT url,domain,title,status,reason FROM candidates WHERE search_id=? ORDER BY CASE WHEN status="Подтверждённый магазин" THEN 0 WHEN status="Требуется проверка" THEN 1 WHEN status="Проверяется" THEN 2 ELSE 3 END,url',(self.current,)):
   self.candidates.insert('','end',iid=url,values=(domain,title[:100],status,reason))
  self.progress.set(snapshot(self.conn,self.current))
 def open_url(self,tree):
  selected=tree.selection()
  if selected:webbrowser.open(selected[0])
 def export(self):
  if self.current is None:return
  path=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=[('Text','*.txt')])
  if not path:return
  with open(path,'w',encoding='utf-8') as f:
   f.write('Finder 3.4 | '+snapshot(self.conn,self.current)+'\n\n')
   for iid in self.table.get_children():f.write(' | '.join(map(str,self.table.item(iid)['values']))+'\n'+iid+'\n\n')
  messagebox.showinfo('Сохранено',path)
 def poll(self):
  changed=False
  while True:
   try:msg=self.q.get_nowait()
   except queue.Empty:break
   changed=True
   if msg=='__DONE__':continue
   self.log.configure(state='normal');self.log.insert('end',msg+'\n');self.log.see('end');self.log.configure(state='disabled')
  if changed:self.refresh()
  self.root.after(350,self.poll)

if __name__=='__main__':
 root=tk.Tk();App(root);root.mainloop()
