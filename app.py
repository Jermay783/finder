"""Finder Windows desktop interface."""
import os,threading,queue,webbrowser,tkinter as tk
from tkinter import ttk,messagebox,filedialog
from core import connect,run_search,snapshot
BASE=os.path.join(os.environ.get('LOCALAPPDATA',os.path.expanduser('~')),'Finder')
os.makedirs(BASE,exist_ok=True);DB=os.path.join(BASE,'finder.sqlite3')
class Finder:
 def __init__(self,root):
  self.root=root;root.title('Finder');root.geometry('1120x760')
  self.db=connect(DB);self.events=queue.Queue();self.pause=threading.Event();self.worker=None;self.sid=None
  self.product=tk.StringVar();self.upc=tk.StringVar();self.api=tk.StringVar();self.state=tk.StringVar(value='Готов к поиску')
  top=ttk.Frame(root,padding=10);top.pack(fill='x')
  for label,var in [('Товар / точная модель',self.product),('UPC (необязательно)',self.upc),('Brave API key',self.api)]:
   ttk.Label(top,text=label).pack(anchor='w')
   e=ttk.Entry(top,textvariable=var,show='*' if var is self.api else '');e.pack(fill='x',pady=3)
  bar=ttk.Frame(top);bar.pack(fill='x',pady=6)
  for label,cmd in [('Найти',self.start),('Пауза',self.stop),('Продолжить',self.resume),('Экспорт TXT',self.export),('Обновить список',self.refresh)]:
   ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=4)
  ttk.Label(root,textvariable=self.state).pack(anchor='w',padx=10)
  columns=('domain','title','status','reason')
  self.table=ttk.Treeview(root,columns=columns,show='headings')
  for col,width in [('domain',190),('title',350),('status',190),('reason',340)]:
   self.table.heading(col,text=col);self.table.column(col,width=width)
  self.table.pack(fill='both',expand=True,padx=10,pady=5)
  self.table.bind('<Double-1>',self.open)
  ttk.Label(root,text='Двойной клик по результату открывает страницу магазина').pack(anchor='w',padx=10)
  self.log=tk.Text(root,height=7);self.log.pack(fill='x',padx=10,pady=8)
  self.history=ttk.Combobox(root,state='readonly');self.history.pack(fill='x',padx=10,pady=5)
  self.history.bind('<<ComboboxSelected>>',self.history_select)
  self.load_history();root.after(400,self.poll)
 def load_history(self):
  self.ids=[x[0] for x in self.db.execute('SELECT id FROM searches ORDER BY id DESC')]
  self.history['values']=[f'{sid}: {q}' for sid,q in self.db.execute('SELECT id,query FROM searches ORDER BY id DESC')]
 def history_select(self,event=None):
  index=self.history.current()
  if index>=0:self.sid=self.ids[index];self.refresh()
 def start(self):
  if self.worker and self.worker.is_alive():return
  if not self.product.get().strip() or not self.api.get().strip():
   return messagebox.showerror('Finder','Введите модель и Brave API key')
  cur=self.db.execute('INSERT INTO searches(query,upc) VALUES(?,?)',(self.product.get().strip(),self.upc.get().strip()))
  self.sid=cur.lastrowid;self.db.commit();self.load_history();self.resume()
 def resume(self):
  if self.worker and self.worker.is_alive():return
  if self.sid is None or not self.api.get().strip():return
  self.pause.clear();self.worker=threading.Thread(target=self.search,args=(self.sid,self.api.get().strip()),daemon=True);self.worker.start()
 def search(self,sid,key):
  try:run_search(DB,sid,key,self.pause,self.events.put)
  except Exception as exc:self.events.put('Ошибка: '+str(exc))
  self.events.put('Поиск завершён')
 def stop(self):self.pause.set()
 def refresh(self):
  self.table.delete(*self.table.get_children())
  if self.sid is None:return
  for sid,url,domain,title,price,status,reason in self.db.execute('SELECT * FROM results WHERE search_id=? ORDER BY CASE status WHEN "Подтверждённый магазин" THEN 0 WHEN "Требуется проверка" THEN 1 ELSE 2 END,domain',(self.sid,)):
   self.table.insert('','end',iid=url,values=(domain,title[:100],status,reason))
  self.state.set(snapshot(self.db,self.sid))
 def open(self,event=None):
  ids=self.table.selection()
  if ids:webbrowser.open(ids[0])
 def export(self):
  if self.sid is None:return
  path=filedialog.asksaveasfilename(defaultextension='.txt',filetypes=[('Text','*.txt')])
  if path:
   with open(path,'w',encoding='utf-8') as f:
    for iid in self.table.get_children():f.write(' | '.join(map(str,self.table.item(iid)['values']))+'\n'+iid+'\n')
 def poll(self):
  updated=False
  while not self.events.empty():
   msg=self.events.get_nowait();self.log.insert('end',msg+'\n');self.log.see('end');updated=True
  if updated:self.refresh()
  self.root.after(400,self.poll)
if __name__=='__main__':
 root=tk.Tk();Finder(root);root.mainloop()
