"""Version 1.5 features: explicit enrichment, editable directories, file actions."""
import json, os, sys, threading, webbrowser, traceback, re, tempfile
from pathlib import Path
from datetime import datetime
from contract_ui import UI_FONT
import tkinter as tk
from tkinter import ttk
from dialogs import messagebox,filedialog,new_dialog,scroll_body
from core import clean, money, extract_inn, normalized_label
from eis import notice_url, fetch_notice, load_notice

VERSION='1.11.1'
NOTICE_FIELDS=(('procurement_method','Способ закупки'),('nmck','НМЦК'),('smp','СМП / СОНКО · ч. 3 ст. 30'),('life','Жизнеобеспечение · ч. 9 ст. 37'),('etp','ЭТП'),('ikz','ИКЗ'))
class Features:
    def supplier_selector(self):
        label=ttk.Label(self.form,text='Наша фирма')
        label.grid(row=self.row,column=0,columnspan=2,sticky='w',pady=(0,4));self.row+=1
        self.v['supplier']=tk.StringVar()
        panel=ttk.Frame(self.form);panel.grid(row=self.row,column=0,columnspan=2,sticky='ew',pady=(0,10))
        self.supplier_choice=ttk.Combobox(panel,textvariable=self.v['supplier'],state='readonly',width=18)
        self.supplier_choice.pack(side='left')
        self.supplier_choice.bind('<<ComboboxSelected>>',lambda event:self.choose_supplier(self.v['supplier'].get()))
        self.entries['supplier']=self.supplier_choice
        settings=ttk.Menubutton(panel,text='Настройки ▾');settings.pack(side='left',padx=6)
        menu=tk.Menu(settings,tearoff=0);menu.add_command(label='Справочник организаций',command=self.directory_dialog)
        menu.add_separator()
        menu.add_command(label='Папка обновлений…',command=self.update_settings)
        menu.add_command(label='Проверить обновления',command=lambda:self.check_updates(manual=True))
        menu.add_command(label='Отключить проверку обновлений',command=self.disable_updates)
        settings.configure(menu=menu)
        self.field_widgets['supplier']=(label,panel);self.field_tab['supplier']=self.form
        self.rebuild_supplier_choices()
        self.row+=1

    def rebuild_supplier_choices(self):
        self.supplier_choice.configure(values=list(dict.fromkeys(pair[0] for pair in self.firms.values())))
        if self.v['supplier'].get() not in [pair[0] for pair in self.firms.values()]:
            self.v['supplier'].set('')

    def init_features(self):
        self.firms={}
        # Explicit replacement list avoids keeping an obsolete INN after editing it.
        if isinstance(self.settings.get('firm_directory'),list):
            rows=self.settings['firm_directory']
            valid={r['inn']:(r['code'],r['name']) for r in rows if isinstance(r,dict) and all(isinstance(r.get(k),str) for k in ('inn','code','name')) and re.fullmatch(r'\d{10}|\d{12}',r['inn']) and r['code'] and r['name']}
            self.firms=valid
        self.last_saved=None;self.eis_info='';self.source_name='';self.original_inn=''
        self._check_job=None

    def schedule_check(self,*args):
        if self._check_job:self.root.after_cancel(self._check_job)
        self._check_job=self.root.after(120,self.run_check)
        if getattr(self,'outputs',None):self.page_label.set('Данные изменены — обновление предпросмотра…')

    def run_check(self):
        self._check_job=None;self.update_check();self.capture_edit();self.schedule_preview()

    def choose_supplier(self,code):
        self.v['supplier'].set(code)
        matches=[(inn,pair) for inn,pair in self.firms.items() if pair[0]==code]
        if len(matches)==1:
            inn,pair=matches[0]
            self.v['inn'].set(inn);self.v['supplier_full'].set(pair[1])
        self.update_check()

    def recognize_supplier(self,event=None):
        inn=re.sub(r'\s+','',self.v['inn'].get())
        pair=self.firms.get(inn)
        self.v['supplier'].set(pair[0] if pair else '')
        if pair:self.v['supplier_full'].set(pair[1])
        self.update_check()

    def directory_dialog(self):
        if not self.guard():return
        win=new_dialog(self.root,'Справочник наших фирм',800,470)
        ttk.Label(win,text='Изменения сохраняются как настройки. Данные контрактов не сохраняются.',padding=12).pack(anchor='w')
        frame=ttk.Frame(win,padding=12);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=('code','inn','name'),show='headings',height=7)
        for col,title,width in [('code','Код',70),('inn','ИНН',140),('name','Название',450)]:tree.heading(col,text=title);tree.column(col,width=width)
        tree.pack(fill='both',expand=True)
        for inn,(code,name) in self.firms.items():tree.insert('','end',values=(code,inn,name))
        form=ttk.Frame(frame);form.pack(fill='x',pady=12);form.columnconfigure(2,weight=1)
        v=[tk.StringVar() for _ in range(3)]
        for col,(label,width) in enumerate([('Код',8),('ИНН',16),('Название',42)]):
            ttk.Label(form,text=label).grid(row=0,column=col,sticky='w');ttk.Entry(form,textvariable=v[col],width=width).grid(row=1,column=col,sticky='ew',padx=(0,8))
        def select(e=None):
            if tree.selection():
                for var,value in zip(v,tree.item(tree.selection()[0],'values')):var.set(value)
        tree.bind('<<TreeviewSelect>>',select)
        def put():
            code,inn,name=[clean(x.get()) for x in v];inn=re.sub(r'\s+','',inn)
            if not code or len(code)>12 or not name or not re.fullmatch(r'\d{10}|\d{12}',inn):
                messagebox.showerror('Справочник','Нужны код (до 12 символов), название и ИНН из 10 или 12 цифр.',parent=win);return
            selected=tree.selection();current=selected[0] if selected else None
            for item in tree.get_children():
                oldcode,oldinn,_=tree.item(item,'values')
                if item!=current and (oldinn==inn or oldcode==code):
                    messagebox.showerror('Справочник','ИНН или код уже занят другой строкой.',parent=win);return
            if current:tree.item(current,values=(code,inn,name))
            else:tree.insert('','end',values=(code,inn,name))
        def new():
            tree.selection_remove(*tree.selection())
            for var in v:var.set('')
        def delete():
            for item in tree.selection():tree.delete(item)
            new()
        bar=ttk.Frame(frame);bar.pack(fill='x')
        for label,cmd in [('Новая строка',new),('Применить строку',put),('Удалить строку',delete)]:ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=3)
        def save():
            rows=[dict(zip(('code','inn','name'),tree.item(i,'values'))) for i in tree.get_children()]
            self.firms={r['inn']:(r['code'],r['name']) for r in rows}
            self.settings['firm_directory']=rows;self.remember()
            self.rebuild_supplier_choices()
            self.recognize_supplier();win.destroy()
        ttk.Button(bar,text='Сохранить справочник',command=save).pack(side='right')

    def remember_customer(self):
        if not self.contract:return
        inn=self.contract.customer_inn;name=clean(self.v['customer'].get())
        if not inn or not name:
            messagebox.showinfo('Название заказчика','Для сохранения нужны распознанный ИНН заказчика и короткое название.');return
        self.settings.setdefault('customer_names',{})[inn]=name;self.remember()
        self.status.set('Короткое название заказчика сохранено по ИНН '+inn)

    def open_eis(self):
        if not self.need():return
        try:webbrowser.open(notice_url(self.v['notice'].get()))
        except ValueError as e:messagebox.showerror('ЕИС',str(e))

    def eis_click(self):
        if not self.need():return
        number=self.v['notice'].get().strip()
        try:notice_url(number)
        except ValueError as e:messagebox.showerror('ЕИС',str(e));return
        self.busy=True;self.status.set('Получаем извещение из ЕИС… Карточка останется открыта.')
        def worker():
            try:self.events.put(('notice',fetch_notice(number)))
            except Exception as e:self.events.put(('eis_error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def notice_dialog(self):
        if not self.need():return
        path=filedialog.askopenfilename(title='Печатная форма извещения ЕИС',filetypes=[('HTML извещения','*.html *.htm')])
        if not path:return
        try:
            number=self.v['notice'].get().strip();notice_url(number)
            self.review_notice(load_notice(path,number))
        except Exception as e:messagebox.showerror('Извещение',str(e))

    def review_notice(self,result):
        if not self.contract or result.number!=self.v['notice'].get().strip():
            messagebox.showerror('Извещение','Номер извещения в карточке изменился. Повторите загрузку.');return
        win=new_dialog(self.root,'Данные извещения — проверьте перед применением',930,680)
        area=ttk.Frame(win);area.pack(fill='both',expand=True)
        canvas=tk.Canvas(area,highlightthickness=0);scroll=ttk.Scrollbar(area,command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        f=ttk.Frame(canvas,padding=16);window=canvas.create_window(0,0,window=f,anchor='nw');f.columnconfigure(2,weight=1)
        f.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        ttk.Label(f,text='Извещение № '+result.number,font=(UI_FONT,12,'bold')).grid(row=0,columnspan=4,sticky='w')
        ttk.Label(f,text=result.revision,wraplength=850).grid(row=1,columnspan=4,sticky='w',pady=6)
        ttk.Label(f,text='Выберите поля для переноса. Уже заполненные значения по умолчанию сохраняются.',wraplength=850).grid(row=2,columnspan=4,sticky='w',pady=6)
        for col,label in enumerate(('Перенести','Поле','В карточке','Из извещения')):ttk.Label(f,text=label).grid(row=3,column=col,sticky='w',padx=8)
        selections={};row=4
        for key,label in NOTICE_FIELDS:
            value=result.values.get(key);target=key
            current=self.v[target].get();empty=not current or (key=='etp' and current=='Ручной ввод' and not self.v['custom_etp'].get())
            applicable=True
            flag=tk.BooleanVar(value=bool(value is not None and empty and applicable))
            widget=ttk.Checkbutton(f,variable=flag);widget.grid(row=row,column=0)
            if value is None or not applicable:widget.state(['disabled'])
            selections[key]=(flag,target,value)
            ttk.Label(f,text=label).grid(row=row,column=1,sticky='w',padx=8,pady=8)
            ttk.Label(f,text=current or '—',wraplength=200).grid(row=row,column=2,sticky='w',padx=8)
            ttk.Label(f,text=value if value is not None else 'Не определено',wraplength=240).grid(row=row,column=3,sticky='w',padx=8)
            row+=1
        from quantity_check import compare
        comparison=compare(self.contract,result)
        info=list(result.warnings)+['Сверка количества: '+comparison.status+'. '+comparison.reason,
            'После применения таблица сравнения доступна: Проверка → Сверка ЕИС.']
        if self.contract.unknown:info.append('Количество не определено: проверьте основание расчёта снижения во вкладке «Закупка». НМЦК, максимальная цена и сумма цен единиц — разные поля.')
        if self.manual.get():info.append('Ручной процент снижения сохранится.')
        ttk.Label(f,text='\n'.join(info),wraplength=850).grid(row=row,columnspan=4,sticky='w',pady=12);row+=1
        def apply():
            self.capture_edit();self._restoring=True
            changed=[]
            for key,(flag,target,value) in selections.items():
                if flag.get() and value is not None:self.v[target].set(value);changed.append(key)
            self._notice_snapshot=result
            self._quantity_key=None
            self._restoring=False;self.capture_edit()
            self.eis_info=f'Извещение № {result.number}; '+result.revision
            self.eis_source.set(self.eis_info)
            self.controls();self.update_check();self.status.set('Извещение проверено. Перенесено полей: '+str(len(changed))+' · Сверка количества: '+self.quantity_result().status);win.destroy()
        actions=ttk.Frame(win,padding=12);actions.pack(side='bottom',fill='x')
        area.pack_forget();area.pack(fill='both',expand=True)
        ttk.Button(actions,text='Отмена',command=win.destroy).pack(side='right',padx=6)
        ttk.Button(actions,text='Применить выбранные',style='Accent.TButton',command=apply).pack(side='right')

    def saved_dialog(self,dest):
        self.last_saved=Path(dest)
        win=new_dialog(self.root,'PDF сохранён',700,170)
        ttk.Label(win,text=str(dest),padding=18,wraplength=650).pack()
        bar=ttk.Frame(win,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='Открыть PDF',command=lambda:self.open_saved(False)).pack(side='left',padx=4)
        ttk.Button(bar,text='Показать в папке',command=lambda:self.open_saved(True)).pack(side='left',padx=4)
        ttk.Button(bar,text='Закрыть',command=win.destroy).pack(side='right',padx=4)

    def open_saved(self,folder):
        if not self.last_saved:return
        path=self.last_saved
        try:
            if sys.platform=='win32':
                if folder:
                    import subprocess
                    subprocess.Popen(['explorer.exe','/select,',str(path)])
                else:os.startfile(path)
            else:webbrowser.open((path.parent if folder else path).as_uri())
        except Exception as e:messagebox.showerror('Открытие файла',str(e))

    def log_error(self,exc,tb):
        # Do not store exception messages, locals, contract text, identifiers or paths.
        try:
            file=self.settings_path.parent/'technical.log';file.parent.mkdir(parents=True,exist_ok=True)
            if file.exists() and file.stat().st_size>200000:file.write_text('',encoding='utf-8')
            frames=traceback.extract_tb(tb)
            details=' > '.join(f'{Path(x.filename).name}:{x.lineno}:{x.name}' for x in frames)
            with file.open('a',encoding='utf-8') as out:out.write(f'{datetime.now():%Y-%m-%d %H:%M:%S} {VERSION} {exc.__name__} {details}\n')
        except OSError:pass
