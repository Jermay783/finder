"""Windows GUI for US Store Finder 3."""
import os, sys, json, threading, queue, webbrowser, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlsplit
import requests
from core import connect,make_tasks,run_search,snapshot

BASE=os.path.join(os.environ.get('LOCALAPPDATA',os.path.expanduser('~')),'USStoreFinder3')
os.makedirs(BASE,exist_ok=True)
DB=os.path.join(BASE,'store_finder.sqlite3')

class App:
 def __init__(self,root):
  self.root=root;root.title('Finder 3.4.0');root.geometry('1380x880');root.minsize(1050,700)
  self.configure_theme()
  self.conn=connect(DB);self.q=queue.Queue();self.pause=threading.Event();self.worker=None;self.current=None
  self.query=tk.StringVar();self.upc=tk.StringVar();self.key=tk.StringVar();self.small=tk.BooleanVar(value=True)
  self.show_key=tk.BooleanVar(value=False);self.limit=tk.IntVar(value=30);self.budget=tk.IntVar(value=100)
  self.minprice=tk.StringVar();self.maxprice=tk.StringVar();self.stock=tk.BooleanVar();self.newonly=tk.BooleanVar()
  self.progress=tk.StringVar(value='Готов к поиску');self.entries={};self.ids={}
  self.proxy_enabled=tk.BooleanVar(value=False);self.proxy_brave=tk.BooleanVar(value=False);self.proxy_url=tk.StringVar()
  self.load_proxy_config()
  sidebar=ttk.Frame(root,style='Sidebar.TFrame',padding=16);sidebar.pack(side='left',fill='y')
  ttk.Label(sidebar,text='◉  FINDER',style='Brand.TLabel').pack(anchor='w',pady=(8,26))
  ttk.Label(sidebar,text='ПОИСК МАГАЗИНОВ',style='Muted.TLabel').pack(anchor='w',pady=(0,14))
  ttk.Button(sidebar,text='Поиск товаров',command=lambda:self.query_entry.focus_set()).pack(fill='x',pady=5)
  ttk.Button(sidebar,text='История',command=lambda:self.history.focus_set()).pack(fill='x',pady=5)
  ttk.Button(sidebar,text='Прокси и сеть',command=self.open_proxy_settings).pack(fill='x',pady=5)
  ttk.Button(sidebar,text='Обновления',command=self.check_updates).pack(fill='x',pady=5)
  ttk.Label(sidebar,text='Версия 3.4.0',style='Muted.TLabel').pack(side='bottom',anchor='w',pady=12)
  content=ttk.Frame(root,padding=12);content.pack(side='left',fill='both',expand=True)
  ttk.Label(content,text='Поиск товаров',style='Heading.TLabel').pack(anchor='w',pady=(0,8))
  top=ttk.Frame(content,padding=9);top.pack(fill='x')
  for label,var in [('Товар / модель',self.query),('UPC (необязательно)',self.upc),('Brave API key',self.key)]:
   ttk.Label(top,text=label).pack(anchor='w')
   line=ttk.Frame(top);line.pack(fill='x',pady=(0,3))
   entry=ttk.Entry(line,textvariable=var,show='*' if var is self.key else '')
   entry.pack(side='left',fill='x',expand=True);self.entries[label]=entry
   if var is self.query:self.query_entry=entry
   ttk.Button(line,text='Вставить',command=lambda e=entry:self.paste(e)).pack(side='left',padx=5)
   self.edit_menu(entry)
  ttk.Checkbutton(top,text='Показать API-ключ',variable=self.show_key,command=lambda:self.entries['Brave API key'].configure(show='' if self.show_key.get() else '*')).pack(anchor='w')
  ttk.Checkbutton(top,text='Отдельный поиск небольших магазинов',variable=self.small).pack(anchor='w')
  bar=ttk.Frame(top);bar.pack(fill='x',pady=4)
  for label,var,low,high in [('Лимит магазинов:',self.limit,1,200),('Макс. Brave API:',self.budget,1,500)]:
   ttk.Label(bar,text=label).pack(side='left',padx=(8,2));ttk.Spinbox(bar,from_=low,to=high,textvariable=var,width=5).pack(side='left')
  for label,fn in [('Новый поиск',self.start),('Пауза',self.stop),('Продолжить',self.resume),('Сохранить TXT',self.export)]:ttk.Button(bar,text=label,command=fn).pack(side='left',padx=4)
  filt=ttk.Frame(content,padding=(9,0));filt.pack(fill='x')
  for label,var in [('Цена от',self.minprice),('Цена до',self.maxprice)]:
   ttk.Label(filt,text=label).pack(side='left');ttk.Entry(filt,textvariable=var,width=10).pack(side='left',padx=5)
  ttk.Checkbutton(filt,text='Только в наличии',variable=self.stock,command=self.refresh).pack(side='left',padx=6)
  ttk.Checkbutton(filt,text='Только новые',variable=self.newonly,command=self.refresh).pack(side='left',padx=6)
  ttk.Button(filt,text='Применить',command=self.refresh).pack(side='left')
  pane=ttk.Panedwindow(content,orient='horizontal');pane.pack(fill='both',expand=True,padx=9,pady=6)
  left=ttk.Frame(pane);right=ttk.Frame(pane);pane.add(left,weight=1);pane.add(right,weight=5)
  ttk.Label(left,text='История поисков').pack(anchor='w');self.history=tk.Listbox(left,bg='#151D2E',fg='#E4EAF8',selectbackground='#6941B5',selectforeground='#FFFFFF',borderwidth=0,highlightthickness=0,font=('Segoe UI',10));self.history.pack(fill='both',expand=True);self.history.bind('<<ListboxSelect>>',self.select_history)
  ttk.Label(right,text='Товары (страна США проверяется отдельно)').pack(anchor='w')
  columns=('domain','title','price','availability','condition','score','us')
  self.table=ttk.Treeview(right,columns=columns,show='headings',height=11)
  for name,width in [('domain',145),('title',330),('price',100),('availability',100),('condition',110),('score',65),('us',120)]:self.table.heading(name,text=name);self.table.column(name,width=width)
  self.table.pack(fill='both',expand=True);self.table.bind('<Double-1>',lambda e:self.open_url(self.table))
  ttk.Label(right,text='Все найденные ссылки — статус и причина отклонения (двойной клик открывает сайт)').pack(anchor='w')
  self.candidates=ttk.Treeview(right,columns=('domain','title','status','reason'),show='headings',height=9)
  for name,width in [('domain',150),('title',270),('status',220),('reason',320)]:self.candidates.heading(name,text=name);self.candidates.column(name,width=width)
  self.candidates.pack(fill='both',expand=True);self.candidates.bind('<Double-1>',lambda e:self.open_url(self.candidates))
  ttk.Label(content,textvariable=self.progress).pack(anchor='w',padx=9)
  self.log=tk.Text(content,height=4,state='disabled',bg='#101525',fg='#B8C5DD',insertbackground='#FFFFFF',relief='flat',font=('Segoe UI',10));self.log.pack(fill='x',padx=9,pady=(0,9))
  ttk.Button(bar,text='Прокси',command=self.open_proxy_settings).pack(side='left',padx=4)
  self.load_history();root.after(350,self.poll)
 def configure_theme(self):
  self.root.configure(bg='#0B1020')
  style=ttk.Style(self.root)
  style.theme_use('clam')
  style.configure('.',font=('Segoe UI',10),background='#111827',foreground='#E8EEFF')
  style.configure('TFrame',background='#111827')
  style.configure('Sidebar.TFrame',background='#0B1020')
  style.configure('TLabel',background='#111827',foreground='#E8EEFF')
  style.configure('Muted.TLabel',background='#0B1020',foreground='#8F9AB2',font=('Segoe UI',9))
  style.configure('Brand.TLabel',background='#0B1020',foreground='#C58BFF',font=('Segoe UI Semibold',17))
  style.configure('Heading.TLabel',background='#111827',foreground='#F4F0FF',font=('Segoe UI Semibold',19))
  style.configure('TButton',background='#282343',foreground='#F4F0FF',padding=(11,7),borderwidth=0)
  style.map('TButton',background=[('active','#6941B5'),('pressed','#8B5CF6')],foreground=[('disabled','#71798A')])
  style.configure('TEntry',fieldbackground='#1C2437',foreground='#FFFFFF',insertcolor='#FFFFFF',bordercolor='#3C4761',padding=5)
  style.configure('TSpinbox',fieldbackground='#1C2437',foreground='#FFFFFF',arrowcolor='#C58BFF')
  style.configure('TCheckbutton',background='#111827',foreground='#DFE6FA')
  style.map('TCheckbutton',background=[('active','#111827')])
  style.configure('Treeview',background='#151D2E',fieldbackground='#151D2E',foreground='#E4EAF8',rowheight=29,borderwidth=0)
  style.map('Treeview',background=[('selected','#6941B5')])
  style.configure('Treeview.Heading',background='#272F43',foreground='#F2F4FF',font=('Segoe UI Semibold',10),padding=7)
  style.configure('TPanedwindow',background='#111827')
  style.configure('TScrollbar',background='#303851')
 def load_proxy_config(self):
  path=os.path.join(BASE,'network.json')
  try:
   with open(path,encoding='utf-8') as file:data=json.load(file)
   self.proxy_enabled.set(bool(data.get('enabled',False)))
   self.proxy_brave.set(bool(data.get('brave',False)))
   # Credentials are never persisted.
   self.proxy_url.set(data.get('url','') if '@' not in data.get('url','') else '')
  except (OSError,ValueError,TypeError):pass
 def save_proxy_config(self):
  url=self.proxy_url.get().strip()
  parsed=urlsplit(url) if url else None
  if self.proxy_enabled.get() and (not parsed or parsed.scheme.lower() not in ('http','https','socks5','socks5h') or not parsed.hostname or not parsed.port):
   raise ValueError('Укажи прокси в формате http://host:port или socks5h://host:port')
  if parsed and (parsed.username or parsed.password):
   raise ValueError('Не вводи пароль в URL: текущая версия не хранит учётные данные прокси')
  path=os.path.join(BASE,'network.json')
  with open(path,'w',encoding='utf-8') as file:
   json.dump({'enabled':self.proxy_enabled.get(),'brave':self.proxy_brave.get(),'url':url},file)
 def open_proxy_settings(self):
  window=tk.Toplevel(self.root);window.title('Finder — Прокси и сеть');window.geometry('620x345')
  window.configure(bg='#111827');window.transient(self.root)
  area=ttk.Frame(window,padding=22);area.pack(fill='both',expand=True)
  ttk.Label(area,text='Прокси и сеть',style='Heading.TLabel').pack(anchor='w',pady=(0,14))
  ttk.Checkbutton(area,text='Использовать прокси для проверки магазинов',variable=self.proxy_enabled).pack(anchor='w',pady=4)
  ttk.Checkbutton(area,text='Также использовать прокси для Brave API',variable=self.proxy_brave).pack(anchor='w',pady=4)
  ttk.Label(area,text='HTTP / HTTPS / SOCKS5 / SOCKS5H — адрес прокси').pack(anchor='w',pady=(14,4))
  entry=ttk.Entry(area,textvariable=self.proxy_url);entry.pack(fill='x')
  ttk.Label(area,text='Пример: socks5h://127.0.0.1:1080  •  Без пароля',style='TLabel').pack(anchor='w',pady=8)
  status=ttk.Label(area,text='Прокси не увеличивает лимиты Brave API');status.pack(anchor='w',pady=8)
  def save():
   try:self.save_proxy_config()
   except Exception as exc:return messagebox.showerror('Прокси',str(exc),parent=window)
   window.destroy()
  def test():
   try:self.save_proxy_config()
   except Exception as exc:return messagebox.showerror('Прокси',str(exc),parent=window)
   status.configure(text='Проверка соединения...')
   def work():
    try:
     import time
     t=time.monotonic();url=self.proxy_url.get().strip()
     response=requests.get('https://api.github.com',timeout=12,proxies={'http':url,'https':url} if self.proxy_enabled.get() else None)
     response.raise_for_status();message=f'Соединение работает: {int((time.monotonic()-t)*1000)} мс'
    except Exception as exc:message='Ошибка: '+str(exc)[:140]
    window.after(0,lambda:status.configure(text=message) if window.winfo_exists() else None)
   threading.Thread(target=work,daemon=True).start()
  buttons=ttk.Frame(area);buttons.pack(anchor='w',pady=8)
  ttk.Button(buttons,text='Проверить соединение',command=test).pack(side='left',padx=(0,10))
  ttk.Button(buttons,text='Сохранить',command=save).pack(side='left')
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
  for key in ('<Control-v>','<Control-V>','<Shift-Insert>'):entry.bind(key,lambda e:(self.paste(entry),'break')[1])
 def load_history(self):
  self.history.delete(0,'end');self.ids={}
  for i,(sid,name,date) in enumerate(self.conn.execute('SELECT id,query,created FROM searches ORDER BY id DESC')):
   self.ids[i]=sid;self.history.insert('end',f'{sid}: {name[:25]} ({date})')
 def select_history(self,event=None):
  sel=self.history.curselection()
  if sel:self.current=self.ids[sel[0]];self.refresh()
 def start(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning('Поиск','Сначала дождитесь остановки текущего поиска')
  if not self.query.get().strip() or not self.key.get().strip():return messagebox.showerror('Ошибка','Введите товар и Brave API key')
  try:limit=max(1,int(self.limit.get()));budget=max(1,int(self.budget.get()))
  except (ValueError,tk.TclError):return messagebox.showerror('Ошибка','Некорректные лимиты')
  c=self.conn;c.execute('INSERT INTO searches(query,upc,small,api_limit,store_limit) VALUES(?,?,?,?,?)',(self.query.get().strip(),self.upc.get().strip(),int(self.small.get()),budget,limit))
  self.current=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  tasks=make_tasks(self.query.get().strip(),self.upc.get().strip(),self.small.get())
  c.execute('INSERT INTO jobs(search_id,queue,done,status) VALUES(?,?,?,?)',(self.current,json.dumps(tasks),'[]','new'));c.commit()
  self.load_history();self.refresh();self.launch()
 def launch(self):
  if self.worker and self.worker.is_alive():return
  if self.current is None:return
  if not self.key.get().strip():return messagebox.showerror('Brave','Введите API-ключ')
  self.pause.clear();sid=self.current;key=self.key.get().strip()
  self.worker=threading.Thread(target=self.background,args=(sid,key),daemon=True);self.worker.start()
 def background(self,sid,key):
  try:run_search(DB,sid,key,self.pause,lambda msg:self.q.put(msg),workers=5,proxy_url=self.proxy_url.get().strip() if self.proxy_enabled.get() else '',proxy_brave=self.proxy_brave.get())
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
