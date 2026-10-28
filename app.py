"""ContractPrintApp 1.12.0 - desktop UI, no contract persistence."""
import copy, json, os, sys, tempfile, threading, queue
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from dialogs import messagebox,filedialog,new_dialog,scroll_body
from core import *
from features import Features, VERSION
from preview import Preview
from contract_workflow import Workflow
from contract_ui import Editing, UI_FONT
from comparison_ui import QuantityPanel
from contract_dates import date_line
from update_ui import UpdateUI

DELIVERY_MODES=('От подписания до даты','Дней от подписания','Период дат','Своя формулировка','Пустые поля')

class Application(UpdateUI,QuantityPanel,Editing,Workflow,Preview,Features):
    def __init__(self,root):
        self.root=root;root.title('ContractPrintApp 1.12.0 · Карточка контракта');root.geometry(f'{min(1240,root.winfo_screenwidth()-40)}x{min(820,root.winfo_screenheight()-80)}');root.minsize(1100,650)
        self.contract=None;self.temp=None;self.pdf=None;self.outputs=None;self.page=0;self.zoom=1.;self.busy=False;self.events=queue.Queue()
        from app_paths import settings_path
        self.settings_path=settings_path()
        try:self.settings=json.loads(self.settings_path.read_text('utf-8'))
        except (OSError,ValueError):self.settings={}
        self.init_features()
        self.v={};self.entries={};self.field_widgets={};self.action_buttons=[]
        self._history=[];self._restoring=False
        geometry=self.settings.get('window_size','')
        if re.fullmatch(r'\d{3,4}x\d{3,4}',geometry):
            w,h=map(int,geometry.split('x'));root.geometry(f'{min(max(1100,w),root.winfo_screenwidth()-30)}x{min(max(650,h),root.winfo_screenheight()-60)}')
        self.style=ttk.Style(root)
        self.style.theme_use('clam')
        self.apply_theme()
        top=ttk.Frame(root,padding=14);top.pack(fill='x')
        ttk.Label(top,text='ContractPrintApp  |  Карточка контракта',style='Title.TLabel').pack(side='left')
        ttk.Button(top,text='Загрузить контракт',command=self.load_dialog).pack(side='right',padx=5)
        ttk.Button(top,text='Сбросить',command=lambda:self.reset(confirm=True)).pack(side='right')
        self.status=tk.StringVar(value='Загрузите печатную форму HTML или перетащите её в окно.')
        ttk.Label(root,textvariable=self.status,padding=(16,0,16,10),wraplength=1150).pack(fill='x')
        enrichment=ttk.Frame(root,padding=(14,0,14,8));enrichment.pack(fill='x')
        self.enrichment_buttons=[]
        for label,cmd in [('Получить из ЕИС',self.eis_click),('Сроки из Word',self.delivery_dialog)]:
            b=ttk.Button(enrichment,text=label,command=cmd);b.pack(side='left',padx=(0,6));b.state(['disabled']);self.enrichment_buttons.append(b)
        more=ttk.Menubutton(enrichment,text='ЕИС ▾');more.pack(side='left',padx=4)
        menu=tk.Menu(more,tearoff=0);menu.add_command(label='Загрузить извещение HTML',command=self.notice_dialog);menu.add_command(label='Открыть извещение в браузере',command=self.open_eis);more.configure(menu=menu)
        self.eis_source=tk.StringVar(value='ЕИС загружается только по кнопке после загрузки контракта.')
        ttk.Label(root,textvariable=self.eis_source,padding=(16,0,16,5),wraplength=1100).pack(fill='x')
        self.workspace=ttk.Panedwindow(root,orient='horizontal');self.workspace.pack(fill='both',expand=True,padx=12)
        self.editor=ttk.Frame(self.workspace);self.workspace.add(self.editor,weight=1)
        self.book=ttk.Notebook(self.editor);self.book.pack(fill='both',expand=True)
        self.root.after(100,self.restore_divider)
        self.forms={};self.form_canvases={}
        for title in ('Организации','Закупка','Условия','Реквизиты'):
            tab=ttk.Frame(self.book);self.book.add(tab,text='  '+title+'  ')
            canvas=tk.Canvas(tab,highlightthickness=0)
            scroll=ttk.Scrollbar(tab,orient='vertical',command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
            frame=ttk.Frame(canvas,padding=14);window=canvas.create_window(0,0,anchor='nw',window=frame)
            frame.bind('<Configure>',lambda e,cv=canvas:cv.configure(scrollregion=cv.bbox('all')))
            canvas.bind('<Configure>',lambda e,cv=canvas,w=window:cv.itemconfigure(w,width=e.width))
            frame.columnconfigure(1,weight=1)
            self.forms[title]=frame;self.form_canvases[title]=canvas
        self.form=self.forms['Организации']
        self.field_tab={}
        self.row=0
        self.supplier_selector()
        for key,label in [('inn','ИНН поставщика'),('number','Номер контракта'),('notice','Номер извещения'),('ikz','ИКЗ'),('customer','Краткое название заказчика'),('subject','Предмет контракта')]:self.field(key,label)
        self.entries['inn'].bind('<FocusOut>',self.recognize_supplier)
        ttk.Button(self.form,text='Запомнить название заказчика',command=self.remember_customer).grid(row=self.row,column=1,sticky='w',pady=5);self.row+=1
        self.form=self.forms['Реквизиты'];self.row=0
        for key,label in [('supplier_full','Поставщик полностью'),('customer_full','Полное название заказчика'),('contact','Контактное лицо заказчика'),('phone','Телефон заказчика'),('email','Электронная почта заказчика'),('address','Место поставки'),('end',END_LABEL)]:self.field(key,label)
        self.form=self.forms['Условия'];self.row=0
        self.choice_buttons('concluded','Контракт заключён?',('Нет','Да'),'Нет')
        self.field('conclusion_date','Дата заключения (ДД.ММ.ГГГГ)')
        self.section('Срок поставки')
        self.choice_buttons('delivery_mode','Способ заполнения',DELIVERY_MODES,'Пустые поля')
        self.pair_fields(('days','Количество дней'),('day_type','Вид дней'),day_type=True)
        self.pair_fields(('date_from','С даты'),('date_to','По дату'));self.field('delivery_text','Своя формулировка срока');self.field('deadline','Дата окончания (ДД.ММ.ГГГГ)')
        self.field('request_delivery','Срок поставки по заявке (на обороте)')
        self.form=self.forms['Закупка'];self.row=0
        self.section('Закупка и стоимость')
        self.field('procurement_method','Способ закупки',values=('Электронный аукцион','Электронный запрос котировок','Электронный конкурс'))
        self.choice_buttons('etp','Электронная торговая площадка',ETPS,ETPS[0]);self.field('custom_etp','ЭТП: ручной ввод')
        self.field('nmck','НМЦК, руб.');self.field('total','Цена / максимальная цена контракта, руб.')
        self.choice_buttons('reduction_basis','Расчёт снижения',('По НМЦК и цене контракта','По суммам цен единиц'),'По НМЦК и цене контракта')
        self.field('initial_units','Начальная сумма цен единиц, руб.');self.field('final_units','Итоговая сумма цен единиц, руб.')
        self.increased=tk.BooleanVar()
        ttk.Checkbutton(self.form,text='Количество / цена увеличены',variable=self.increased,command=self.controls).grid(row=self.row,columnspan=2,sticky='w',pady=6);self.row+=1
        self.field('original_price','Цена контракта до увеличения, руб.')
        self.manual=tk.BooleanVar();ttk.Checkbutton(self.form,text='Ввести снижение вручную',variable=self.manual,command=self.controls).grid(row=self.row,columnspan=2,sticky='w',pady=7);self.row+=1
        self.field('reduction','Ручное снижение, %')
        self.reduction_text=tk.StringVar(value='Снижение: заполните НМЦК или введите процент вручную.')
        ttk.Label(self.form,textvariable=self.reduction_text,wraplength=480).grid(row=self.row,columnspan=2,sticky='w',pady=6);self.row+=1
        self.section('Условия закупки')
        self.choice_buttons('smp',SMP_LABEL,('Да','Нет'));self.choice_buttons('life',LIFE_LABEL,('Да','Нет'))
        ttk.Label(self.form,text='Без выбора — поле для ручной отметки.',wraplength=450).grid(row=self.row,columnspan=2,sticky='w',pady=5);self.row+=1
        self.form=self.forms['Условия'];self.row=max(int(w.grid_info().get('row',0)) for w in self.form.winfo_children())+1
        self.section('Примечание и экземпляр')
        self.note_label=ttk.Label(self.form,text='Примечание (необязательно)',wraplength=155);self.note_label.grid(row=self.row,column=0,sticky='nw',pady=5)
        self.note=tk.Text(self.form,height=3,width=20,undo=True,wrap='word',font=(UI_FONT,10),bg=self.palette['entry'],fg=self.palette['fg'],insertbackground=self.palette['fg']);self.note.grid(row=self.row,column=1,sticky='ew',pady=5);self.row+=1
        self.include_note=tk.BooleanVar(value=False);ttk.Checkbutton(self.form,text='Печатать примечание на обороте',variable=self.include_note,command=self.controls).grid(row=self.row,column=0,columnspan=2,sticky='w');self.row+=1
        self.field('created_date','Дата создания экземпляра (ДД.ММ.ГГГГ)',default=datetime.now().strftime('%d.%m.%Y'))
        spec=ttk.Frame(self.book,padding=10);self.book.add(spec,text='Позиции')
        ttk.Label(spec,text='Двойной щелчок — правка позиции.',wraplength=460).pack(anchor='w',pady=6)
        cols=('no','name','qty','price','vat','total');self.tree=ttk.Treeview(spec,columns=cols,show='headings')
        for key,label,width in zip(cols,('№','Наименование','Количество / ед.','Цена','НДС (в сумме)','Сумма'),(40,460,145,105,125,105)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=30,stretch=key=='name')
        hs=ttk.Scrollbar(spec,orient='horizontal',command=self.tree.xview);hs.pack(side='bottom',fill='x');self.tree.configure(xscrollcommand=hs.set)
        sb=ttk.Scrollbar(spec,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True);self.tree.bind('<Double-1>',self.edit_item)
        self.check_tab=ttk.Frame(self.book,padding=14);self.book.add(self.check_tab,text='Проверка')
        self.check_book=ttk.Notebook(self.check_tab);self.check_book.pack(fill='both',expand=True)
        checks=ttk.Frame(self.check_book);comparison=ttk.Frame(self.check_book,padding=6)
        self.check_book.add(checks,text='Замечания');self.check_book.add(comparison,text='Сверка ЕИС')
        self.init_quantity_panel(comparison)
        ttk.Label(checks,text='Проверка обязательных полей и предупреждений',font=(UI_FONT,11,'bold'),wraplength=420).pack(anchor='w',pady=(0,10))
        self.check_list=tk.Listbox(checks,font=(UI_FONT,11),height=14,bg=self.palette['entry'],fg=self.palette['fg'])
        self.check_list.pack(fill='both',expand=True)
        ttk.Button(checks,text='Перейти к полю',command=self.goto_issue).pack(anchor='e',pady=8)
        self.preview=ttk.Frame(self.workspace,padding=8);self.workspace.add(self.preview,weight=1)
        bar=ttk.Frame(self.preview);bar.pack(fill='x')
        self.scale_choice=tk.StringVar(value='Весь лист')
        scale=ttk.Combobox(bar,textvariable=self.scale_choice,values=('Весь лист','По ширине','50%','75%','100%','125%','150%','200%'),width=12,state='readonly');scale.pack(side='left');scale.bind('<<ComboboxSelected>>',self.choose_scale)
        for label,cmd in [('−',lambda:self.scale(-.1)),('+',lambda:self.scale(.1))]:ttk.Button(bar,text=label,width=3,command=cmd).pack(side='left',padx=2)
        self.expand_button=ttk.Button(bar,text='Развернуть',command=self.toggle_preview);self.expand_button.pack(side='right')
        self.page_label=tk.StringVar(value='Загрузите контракт для предпросмотра')
        ttk.Label(self.preview,textvariable=self.page_label,wraplength=470).pack(fill='x',pady=(7,0))
        panel=ttk.Frame(self.preview);panel.pack(fill='both',expand=True,pady=5)
        self.init_thumbnails(panel)
        main=ttk.Frame(panel);main.pack(side='left',fill='both',expand=True)
        self.pcanvas=tk.Canvas(main,bg=self.palette['canvas'],highlightthickness=0)
        vs=ttk.Scrollbar(main,orient='vertical',command=self.pcanvas.yview);hs=ttk.Scrollbar(main,orient='horizontal',command=self.pcanvas.xview)
        self.pcanvas.configure(xscrollcommand=hs.set,yscrollcommand=vs.set);vs.pack(side='right',fill='y');hs.pack(side='bottom',fill='x');self.pcanvas.pack(fill='both',expand=True)
        self.fit_enabled=True;self.fit_mode='Весь лист';self._preview_job=None
        self.pcanvas.bind('<Configure>',self.preview_resize)
        for event in ('<MouseWheel>','<Button-4>','<Button-5>'):self.pcanvas.bind(event,self.preview_wheel)
        bottom=ttk.Frame(root,padding=(12,6));bottom.pack(side='bottom',fill='x');bottom.columnconfigure(1,weight=1)
        self.folder=tk.StringVar(value=self.settings.get('folder',DEFAULT_FOLDER));ttk.Label(bottom,text='Папка PDF').grid(row=0,column=0,sticky='w',padx=(0,12));ttk.Entry(bottom,textvariable=self.folder).grid(row=0,column=1,sticky='ew');ttk.Button(bottom,text='Выбрать',command=self.choose_folder).grid(row=0,column=2,padx=5)
        self.custom_name=tk.BooleanVar();ttk.Checkbutton(bottom,text='Своё имя файла',variable=self.custom_name,command=self.update_name).grid(row=1,column=0,sticky='w');self.file_name=tk.StringVar();self.name_entry=ttk.Entry(bottom,textvariable=self.file_name);self.name_entry.grid(row=1,column=1,columnspan=2,sticky='ew',pady=6)
        actions=ttk.Frame(bottom);actions.grid(row=0,column=3,rowspan=2,sticky='e',padx=(10,0))
        for label,cmd in [('Сохранить PDF',self.save),('Печать',self.print_dialog)]:
            b=ttk.Button(actions,text=label,command=cmd,style='Accent.TButton' if label=='Печать' else 'TButton');b.pack(side='left',padx=3);self.action_buttons.append(b)
        extra=ttk.Menubutton(actions,text='▾',width=2);extra.pack(side='left')
        menu=tk.Menu(extra,tearoff=0);menu.add_command(label='Сохранить лицевые и оборот отдельно',command=self.save_separate);extra.configure(menu=menu)
        self.completion=tk.StringVar(value='Заполните данные контракта')
        ttk.Label(bottom,textvariable=self.completion,wraplength=1100).grid(row=2,column=0,columnspan=4,sticky='w',pady=(8,0))
        self.issues=[]
        self.apply_theme()
        self.install_clipboard_shortcuts();self.install_editing()
        self.book.bind('<<NotebookTabChanged>>',self.tab_changed)
        self.note.bind('<<Modified>>',self.note_changed)
        for var in (self.manual,self.increased,self.include_note):var.trace_add('write',self.schedule_check)
        for key,v in self.v.items():v.trace_add('write',self.schedule_check)
        for key in ('supplier','customer','notice'):self.v[key].trace_add('write',lambda *a:self.update_name())
        for key in ('nmck','total','initial_units','final_units','reduction','original_price'):self.v[key].trace_add('write',lambda *a:self.show_reduction())
        for key in ('delivery_mode','etp','reduction_basis','concluded'):self.v[key].trace_add('write',lambda *a:self.controls())
        try:
            from tkinterdnd2 import DND_FILES
            root.drop_target_register(DND_FILES);root.dnd_bind('<<Drop>>',self.drop)
        except (ImportError,tk.TclError):pass
        root.protocol('WM_DELETE_WINDOW',self.close);root.report_callback_exception=self.callback_error
        self.controls();self.update_name();root.after(150,self.poll)
        # Allocate footer controls before letting the workspace consume the rest.
        self.workspace.pack_forget();self.workspace.pack(fill='both',expand=True,padx=12)
        if '--self-test' not in sys.argv:root.after(2000,self.check_updates)

    def update_check(self):
        if not hasattr(self,'check_list'):return
        required=[('supplier','Организации','Наша фирма'),('number','Организации','Номер контракта'),
                  ('customer','Организации','Заказчик'),('inn','Организации','ИНН поставщика')]
        problems=[]
        if self.contract is None:problems.append((None,'Организации','Не загружен исходный HTML'))
        for key,tab,label in required:
            value=self.v[key].get().strip()
            if not value:problems.append((key,tab,'Не заполнено: '+label))
        if self.contract is not None and not self.contract.unknown:
            try:
                values=[decimal(item.total) for item in self.contract.items]
                declared=decimal(self.v['total'].get(),'Цена контракта')
                if declared is not None and all(v is not None for v in values) and abs(sum(values)-declared)>Decimal('0.01'):
                    problems.append((None,'Закупка','Сумма строк спецификации не совпадает с ценой контракта'))
            except ValueError:
                problems.append(('total','Закупка','Ошибка в числовом формате цены контракта'))
        inn=self.v['inn'].get().strip()
        ikz=self.v['ikz'].get().strip()
        if ikz and not re.fullmatch(r'\d{36}',ikz):problems.append(('ikz','Организации','ИКЗ должен содержать 36 цифр'))
        if inn and (not inn.isdigit() or len(inn) not in (10,12)):
            problems.append(('inn','Организации','Ошибка: ИНН должен содержать 10 или 12 цифр'))
        if self.v['delivery_mode'].get()=='Период дат':
            for key in ('date_from','date_to'):
                if not self.v[key].get().strip():problems.append((key,'Условия','Не указана дата: '+key))
        if self.v['delivery_mode'].get()=='От подписания до даты' and not self.v['deadline'].get().strip():problems.append(('deadline','Условия','Не указана конечная дата поставки'))
        if self.contract:
            for msg in specification_issues(self.contract):problems.append((None,'Спецификация',msg))
            if not self.v['notice'].get().strip():problems.append(('notice','Организации','Не заполнен номер извещения'))
            current_inn=self.v['inn'].get().strip()
            if current_inn in self.firms and self.v['supplier'].get()!=self.firms[current_inn][0]:problems.append(('supplier','Организации','Код фирмы не соответствует ИНН в справочнике'))
            if self.original_inn and self.v['inn'].get()!=self.original_inn:problems.append(('inn','Организации','ИНН изменён относительно исходного HTML: проверьте выбор фирмы'))
            for key,tab,label in [('address','Реквизиты','Место поставки'),('end','Реквизиты',END_LABEL)]:
                if not self.v[key].get().strip():problems.append((key,tab,'Не заполнено: '+label))
        for key in self.active_dates():
            value=self.v[key].get().strip()
            self.entries[key].configure(style='TEntry')
            if value:
                try:datetime.strptime(value,'%d.%m.%Y');self.entries[key].configure(style='TEntry')
                except ValueError:
                    self.entries[key].configure(style='Invalid.TEntry');problems.append((key,'Условия','Неверная дата: '+value))
        if self.v['concluded'].get()=='Да' and not self.v['conclusion_date'].get().strip():
            problems.append(('conclusion_date','Условия','Не указана дата заключения контракта'))
        self.update_quantity_panel()
        self.issues=problems
        self.check_list.delete(0,'end')
        for key,tab,msg in problems:self.check_list.insert('end',('Ошибка: ' if key else '')+msg)
        if not problems:self.check_list.insert('end','Все обязательные сведения заполнены. Проверьте PDF перед сохранением.')
        issues_by_tab={tab for key,tab,msg in problems}
        for tab in ('Организации','Закупка','Условия','Реквизиты'):
            frame=self.forms[tab];self.book.tab(frame.master.master,text=('! ' if tab in issues_by_tab else '')+{'Организации':'Фирмы','Условия':'Сроки'}.get(tab,tab))
        optional=[]
        if self.contract:
            units=self.v['reduction_basis'].get()=='По суммам цен единиц'
            for key,label in [('initial_units' if units else 'nmck','Начальная сумма цен единиц' if units else 'НМЦК'),('smp','СМП'),('life','Жизнеобеспечение')]:
                if not self.v[key].get().strip():optional.append(label)
        summary=f'{len(self.contract.items)} позиций · ' if self.contract else ''
        summary+=(f'Проверить: {len(problems)}' if problems else 'Обязательные поля заполнены')
        if optional:summary+=' · Пустые поля для ручного заполнения: '+', '.join(optional)
        self.completion.set(summary)
        for button in self.enrichment_buttons:button.state(['!disabled'] if self.contract and not self.busy else ['disabled'])

    def goto_issue(self):
        selected=self.check_list.curselection()
        if not selected or selected[0]>=len(self.issues):return
        key,tab,_=self.issues[selected[0]]
        if tab=='Спецификация':self.book.select(self.tree.master);return
        self.book.select(self.forms[tab].master.master);self.root.update_idletasks()
        if key in self.entries:
            w=self.entries[key]
            self.form_canvases[tab].yview_moveto(max(0,(w.winfo_rooty()-self.forms[tab].winfo_rooty())/max(1,self.forms[tab].winfo_height())))
            w.focus_set()

    def install_clipboard_shortcuts(self):
        """Windows keyboard shortcuts that also work with Russian keyboard layouts."""
        # 0x41/43/56/58 are Windows virtual key codes independent of layout.
        keycodes={65:'select',67:'copy',86:'paste',88:'cut'}
        latin={'a':'select','c':'copy','v':'paste','x':'cut'}
        cyrillic={'ф':'select','с':'copy','м':'paste','ч':'cut'}

        def execute(widget, operation):
            text_widget=isinstance(widget,tk.Text)
            editable=isinstance(widget,(tk.Entry,ttk.Entry,ttk.Combobox,tk.Text))
            if not editable:return False
            if isinstance(widget,ttk.Combobox) and str(widget.cget('state'))=='readonly' and operation in ('paste','cut'):
                return False
            try:
                if operation=='select':
                    if text_widget:widget.tag_add('sel','1.0','end-1c')
                    else:widget.selection_range(0,'end')
                    return True
                if text_widget:
                    selected=widget.get('sel.first','sel.last') if widget.tag_ranges('sel') else ''
                else:
                    selected=widget.selection_get() if widget.selection_present() else ''
                if operation in ('copy','cut'):
                    if selected:
                        self.root.clipboard_clear()
                        self.root.clipboard_append(selected)
                        self.root.update_idletasks()
                    if operation=='cut' and selected:
                        if text_widget:widget.delete('sel.first','sel.last')
                        else:widget.delete('sel.first','sel.last')
                elif operation=='paste':
                    try:contents=self.root.clipboard_get()
                    except tk.TclError:return True
                    if text_widget:
                        if widget.tag_ranges('sel'):widget.delete('sel.first','sel.last')
                        widget.insert('insert',contents)
                    else:
                        if widget.selection_present():widget.delete('sel.first','sel.last')
                        widget.insert('insert',contents)
                return True
            except (tk.TclError,ValueError):return False

        def shortcuts(event):
            if not (event.state & 0x4):return
            operation=keycodes.get(event.keycode) if sys.platform=='win32' else None
            operation=operation or latin.get((event.keysym or '').lower()) or cyrillic.get((event.char or '').lower())
            if operation and execute(event.widget,operation):return 'break'

        def context_menu(event):
            widget=event.widget
            menu=tk.Menu(self.root,tearoff=0)
            for name,operation in (('Вырезать','cut'),('Копировать','copy'),('Вставить','paste'),('Выделить всё','select')):
                menu.add_command(label=name,command=lambda op=operation,w=widget:execute(w,op))
            menu.tk_popup(event.x_root,event.y_root)
            menu.grab_release()
            return 'break'

        for cls in ('Entry','TEntry','Text','TCombobox'):
            self.root.bind_class(cls,'<Control-KeyPress>',shortcuts,add='+')
            self.root.bind_class(cls,'<Button-3>',context_menu,add='+')
    def apply_theme(self):
        self.palette={'bg':'#f3f5f8','panel':'#ffffff','entry':'#ffffff','fg':'#223448','muted':'#65778a','accent':'#245a86','selected':'#e0edf7','canvas':'#e5e9ef'}
        c=self.palette;self.root.configure(bg=c['bg'])
        self.style.configure('.',font=(UI_FONT,10),background=c['panel'],foreground=c['fg'])
        self.style.configure('TFrame',background=c['panel'])
        self.style.configure('TLabel',background=c['panel'],foreground=c['fg'])
        self.style.configure('Title.TLabel',font=(UI_FONT,16,'bold'),foreground=c['accent'])
        self.style.configure('TButton',padding=(8,5),background=c['entry'],foreground=c['fg'],borderwidth=1,relief='flat')
        self.style.map('TButton',background=[('active',c['selected'])],foreground=[('active',c['accent'])])
        self.style.configure('Accent.TButton',background=c['accent'],foreground=c['bg'])
        self.style.map('Accent.TButton',background=[('active',c['accent'])],foreground=[('active',c['bg'])])
        self.style.configure('TNotebook',background=c['bg'],borderwidth=0)
        self.style.configure('TNotebook.Tab',padding=(5,7),background=c['panel'],foreground=c['muted'])
        self.style.map('TNotebook.Tab',background=[('selected',c['selected'])],foreground=[('selected',c['accent'])])
        self.style.configure('TEntry',fieldbackground=c['entry'],foreground=c['fg'],insertcolor=c['fg'])
        self.style.configure('Invalid.TEntry',fieldbackground='#fff0ef',foreground='#a32929')
        self.style.configure('TCombobox',fieldbackground=c['entry'],foreground=c['fg'])
        self.style.configure('Treeview',background=c['panel'],fieldbackground=c['panel'],foreground=c['fg'],rowheight=29)
        self.style.configure('Treeview.Heading',background=c['selected'],foreground=c['fg'],font=(UI_FONT,10,'bold'))
        self.style.map('Treeview',background=[('selected',c['selected'])],foreground=[('selected',c['fg'])])
        if hasattr(self,'form_canvases'):
            for canvas in self.form_canvases.values():canvas.configure(bg=c['panel'])
        if hasattr(self,'pcanvas'):self.pcanvas.configure(bg=c['canvas'])
        if hasattr(self,'note'):self.note.configure(bg=c['entry'],fg=c['fg'],insertbackground=c['fg'])
        if hasattr(self,'check_list'):self.check_list.configure(bg=c['entry'],fg=c['fg'],selectbackground=c['selected'],selectforeground=c['fg'])
    def choice_buttons(self,key,label,options,default=''):
        ttk.Label(self.form,text=label,wraplength=460).grid(row=self.row,columnspan=2,sticky='w',pady=(7,3));self.row+=1
        var=self.v[key]=tk.StringVar(value=default)
        bar=ttk.Frame(self.form);bar.grid(row=self.row,columnspan=2,sticky='ew',pady=(0,5))
        buttons=[]
        def redraw(*unused):
            for value,button in buttons:button.configure(style='Accent.TButton' if var.get()==value else 'TButton')
        columns=2 if key in ('delivery_mode','reduction_basis','smp','life') else 3
        for n,choice in enumerate(options):
            btn=ttk.Button(bar,text=choice,command=lambda val=choice:var.set('' if var.get()==val and key in ('smp','life') else val))
            btn.grid(row=n//columns,column=n%columns,sticky='ew',padx=(0,4),pady=2);bar.columnconfigure(n%columns,weight=1);buttons.append((choice,btn))
        var.trace_add('write',redraw);redraw()
        self.entries[key]=buttons[0][1];self.field_widgets[key]=(bar,);self.field_tab[key]=self.form;self.row+=1
    def field(self,key,label,values=None,readonly=False,default=''):
        lbl=ttk.Label(self.form,text=label,wraplength=155);lbl.grid(row=self.row,column=0,sticky='w',padx=(0,16),pady=4)
        v=self.v[key]=tk.StringVar(value=default)
        widget=ttk.Combobox(self.form,textvariable=v,values=values,state='readonly' if readonly else 'normal',width=20) if values else ttk.Entry(self.form,textvariable=v,width=20)
        widget.grid(row=self.row,column=1,sticky='ew',pady=4);self.entries[key]=widget;self.field_widgets[key]=(lbl,widget);self.field_tab[key]=self.form;self.row+=1
    def section(self,title):
        ttk.Separator(self.form).grid(row=self.row,columnspan=2,sticky='ew',pady=(16,8));self.row+=1
        ttk.Label(self.form,text=title,font=(UI_FONT,12,'bold')).grid(row=self.row,columnspan=2,sticky='w',pady=(0,5));self.row+=1
    def callback_error(self,exc,value,tb):
        self.log_error(exc,tb);messagebox.showerror('ContractPrintApp',str(value),parent=self.root)
    def guard(self):
        if self.busy:messagebox.showinfo('Операция выполняется','Дождитесь завершения текущей операции.',parent=self.root);return False
        return True
    def need(self):
        if not self.guard():return False
        if self.contract is None:messagebox.showinfo('Загрузка','Сначала загрузите HTML.',parent=self.root);return False
        return True
    def controls(self):
        mode=self.v['delivery_mode'].get()
        shown={'conclusion_date':self.v['concluded'].get()=='Да','days':mode=='Дней от подписания','day_type':mode=='Дней от подписания',
               'date_from':mode=='Период дат','date_to':mode=='Период дат',
               'delivery_text':mode=='Своя формулировка',
               'deadline':mode=='От подписания до даты',
               'custom_etp':self.v['etp'].get()==ETPS[0],
               'reduction':self.manual.get(),
               'original_price':self.increased.get() and not self.manual.get(),
               'initial_units':self.v['reduction_basis'].get()=='По суммам цен единиц',
               'final_units':self.v['reduction_basis'].get()=='По суммам цен единиц'}
        for k,on in shown.items():
            for widget in self.field_widgets[k]:
                if on:widget.grid()
                else:widget.grid_remove()
        if self.include_note.get():
            self.note_label.grid();self.note.grid()
        else:
            self.note_label.grid();self.note.grid()
        self.show_reduction()
    def basic_options(self):
        return Options(concluded=self.v['concluded'].get()=='Да',conclusion_date=self.v['conclusion_date'].get(),request_delivery=self.v['request_delivery'].get(),price_increased=self.increased.get(),original_price=self.v['original_price'].get(),reduction_basis='units' if self.v['reduction_basis'].get()=='По суммам цен единиц' else 'nmck',platform=self.v['custom_etp'].get().strip() if self.v['etp'].get()==ETPS[0] else self.v['etp'].get(),nmck=self.v['nmck'].get(),initial_units=self.v['initial_units'].get(),final_units=self.v['final_units'].get(),manual_reduction=self.manual.get(),reduction=self.v['reduction'].get(),smp=self.v['smp'].get(),life=self.v['life'].get(),note=self.note.get('1.0','end-1c').strip() if self.include_note.get() else '')
    def show_reduction(self):
        if not self.contract:return
        c=copy.copy(self.contract);c.total=self.v['total'].get()
        try:
            o=self.basic_options();r=reduction(c,o)
            missing='введите процент вручную' if o.manual_reduction else 'укажите начальную и итоговую суммы цен единиц' if o.reduction_basis=='units' else 'укажите НМЦК и цену до увеличения' if o.price_increased else 'укажите НМЦК и цену контракта'
            hint=''
            if c.unknown and not o.manual_reduction and o.reduction_basis=='nmck':
                hint='\nВ HTML количество не определено. Сейчас сравниваются НМЦК и цена контракта; для расчёта по ценам единиц выберите второй способ.'
            self.reduction_text.set('Снижение: '+(r+' %' if r else missing)+hint)
        except ValueError as e:self.reduction_text.set(str(e))
    def update_name(self):
        if not hasattr(self,'custom_name'):return
        self.name_entry.configure(state='normal' if self.custom_name.get() else 'readonly')
        if not self.custom_name.get():
            c=Contract(supplier=self.v['supplier'].get(),customer=self.v['customer'].get(),notice=self.v['notice'].get())
            self.file_name.set(suggested_name(c) if self.contract else '')
    def clear_preview(self):
        if getattr(self,'_auto_job',None):self.root.after_cancel(self._auto_job);self._auto_job=None
        self._preview_state=None
        self.clear_thumbnails()
        if self.pdf:self.pdf.close();self.pdf=None
        if self.temp:self.temp.cleanup();self.temp=None
        self.outputs=None;self.pcanvas.delete('all');self.page_label.set('Сформируйте предпросмотр')
    def reset(self,confirm=False):
        if not self.guard():return
        if confirm and self.contract and not messagebox.askyesno('Сброс','Сбросить все данные текущего контракта?',parent=self.root):return
        self._notice_snapshot=None;self._quantity_key=None;self._history=[];self.contract=None;self.clear_preview();self.original_inn='';self.source_name='';self.eis_info='';self.eis_source.set('ЕИС загружается только по кнопке после загрузки контракта.')
        for k,v in self.v.items():v.set('')
        self.v['concluded'].set('Нет');self.v['created_date'].set(datetime.now().strftime('%d.%m.%Y'));self.v['delivery_mode'].set('Пустые поля');self.v['day_type'].set('календарных');self.v['reduction_basis'].set('По НМЦК и цене контракта');self.v['etp'].set(ETPS[0]);self.manual.set(False);self.increased.set(False);self.custom_name.set(False);self.include_note.set(False)
        self.note.delete('1.0','end');self.note.edit_reset();self.tree.delete(*self.tree.get_children());self.controls();self.update_name();self.reduction_text.set('Снижение: заполните НМЦК или введите процент вручную.');self.status.set('Карточка сброшена. Сохранённые PDF не удалены.');self.book.select(0)
    def load_dialog(self):
        if self.guard():
            path=filedialog.askopenfilename(title='Печатная форма контракта',filetypes=[('Печатная форма HTML','*.html *.htm'),('Все файлы','*.*')])
            if path:self.load(path)
    def drop(self,event):
        paths=self.root.tk.splitlist(event.data)
        if len(paths)!=1:messagebox.showinfo('Загрузка','Перетащите один HTML, DOC или DOCX.');return
        if Path(paths[0]).suffix.lower() in ('.doc','.docx'):self.delivery_dialog(paths[0])
        else:self.load(paths[0])
    def load(self,path):
        if not self.guard():return
        try:c=parse(path,self.firms)
        except Exception as e:messagebox.showerror('Не удалось прочитать HTML',str(e));return
        if not self.confirm_replace():return
        self.reset();self.contract=c;self.original_inn=c.inn;self.source_name=Path(path).name
        c.customer=self.settings.get('customer_names',{}).get(c.customer_inn,c.customer)
        for k in ('supplier','supplier_full','inn','number','notice','ikz','procurement_method','customer','customer_full','subject','contact','phone','email','address','end','total'):self.v[k].set(getattr(c,k))
        if c.unknown:
            values=[decimal(i.price) for i in c.items]
            if all(v is not None for v in values):self.v['final_units'].set(str(sum(values)))
        self.populate();self.controls();self.update_name();self.update_check()
        self.status.set(f'{Path(path).name} · {len(c.items)} позиций'+(' · Количество не определено' if c.unknown else ''))
        self.mark_saved();self.reset_history();self.schedule_preview()
        if c.warnings:messagebox.showwarning('Проверьте данные','\n\n'.join(c.warnings))
    def populate(self):
        self.tree.delete(*self.tree.get_children())
        for n,i in enumerate(self.contract.items):self.tree.insert('','end',iid=str(n),values=(i.no,i.name,i.qty,i.price,(money(str(vat_amount(i.total,i.vat))) if vat_amount(i.total,i.vat) is not None else i.vat),i.total))
    def edit_item(self,event=None):
        if not self.need() or not self.tree.selection():return
        index=int(self.tree.selection()[0]);i=self.contract.items[index]
        win=new_dialog(self.root,'Позиция '+i.no,860,730)
        cv=tk.Canvas(win,highlightthickness=0);sb=ttk.Scrollbar(win,command=cv.yview);cv.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');cv.pack(fill='both',expand=True)
        f=ttk.Frame(cv,padding=12);wid=cv.create_window(0,0,window=f,anchor='nw');f.columnconfigure(1,weight=1)
        f.bind('<Configure>',lambda e:cv.configure(scrollregion=cv.bbox('all')));cv.bind('<Configure>',lambda e:cv.itemconfigure(wid,width=e.width))
        fields={}
        for row,(k,label) in enumerate([('no','№'),('name','Наименование'),('extra','Сведения о товаре / РУ'),('kind','Тип'),('code','Код позиции'),('qty','Количество и единица'),('price','Цена'),('vat','НДС'),('country','Страна'),('total','Сумма'),('chars','Характеристики (каждая с новой строки)')]):
            ttk.Label(f,text=label,wraplength=190).grid(row=row,column=0,sticky='nw',pady=4)
            w=tk.Text(f,height=5 if k in ('extra','chars') else 2,wrap='word',font=(UI_FONT,10));w.grid(row=row,column=1,sticky='ew',pady=4);w.insert('1.0','\n'.join(i.chars) if k=='chars' else getattr(i,k));fields[k]=w
        def commit():
            try:
                values={k:w.get('1.0','end-1c').strip() for k,w in fields.items()}
                if not values['name'] or not re.fullmatch(r'\d+',values['no']):raise ValueError('Нужны наименование и целый номер позиции.')
                if any(j!=index and other.no==values['no'] for j,other in enumerate(self.contract.items)):raise ValueError('Такой номер позиции уже существует.')
                decimal(values['price'],'Цена',False);decimal(values['total'],'Сумма')
                values['chars']=[s.strip() for s in values['chars'].splitlines() if s.strip()]
                self.contract.items[index]=Item(**values);self.populate();self.schedule_check();win.destroy()
            except ValueError as e:messagebox.showerror('Позиция',str(e),parent=win)
        ttk.Button(win,text='Применить',command=commit).pack(side='bottom',pady=8)
        cv.pack_forget();cv.pack(fill='both',expand=True)
    def snapshot(self):
        self.normalize_dates()
        c=copy.deepcopy(self.contract)
        for k in ('supplier','supplier_full','inn','number','notice','ikz','procurement_method','customer','customer_full','subject','contact','phone','email','address','end','total'):setattr(c,k,self.v[k].get().strip())
        if not c.number or not c.supplier or not c.customer:raise ValueError('Заполните номер контракта, нашу фирму и заказчика.')
        if c.inn and (not c.inn.isdigit() or len(c.inn) not in (10,12)):raise ValueError('ИНН поставщика должен содержать 10 или 12 цифр.')
        if c.ikz and not re.fullmatch(r'\d{36}',c.ikz):raise ValueError('ИКЗ должен содержать 36 цифр или оставаться пустым.')
        decimal(c.total,'Цена контракта');o=self.basic_options();o.created_date=self.v['created_date'].get().strip();
        try:datetime.strptime(o.created_date,'%d.%m.%Y')
        except ValueError:raise ValueError('Дата создания экземпляра должна быть в формате ДД.ММ.ГГГГ.')
        decimal(o.nmck,'НМЦК');mode=self.v['delivery_mode'].get()
        if mode=='Дней от подписания':
            s=self.v['days'].get().strip()
            if not s.isdigit() or not 1<=int(s)<=9999:raise ValueError('Укажите количество дней от 1 до 9999.')
            n=int(s);typ=self.v['day_type'].get();unit=('календарного дня' if typ=='календарных' else 'рабочего дня') if n%10==1 and n%100!=11 else typ+' дней'
            o.delivery=f'В течение {n} {unit} с даты подписания контракта'
        elif mode=='Период дат':
            try:a=datetime.strptime(self.v['date_from'].get().strip(),'%d.%m.%Y');b=datetime.strptime(self.v['date_to'].get().strip(),'%d.%m.%Y')
            except ValueError:raise ValueError('Введите обе даты срока поставки в формате ДД.ММ.ГГГГ.')
            if b<a:raise ValueError('Дата окончания поставки раньше даты начала.')
            o.delivery=f'С {a:%d.%m.%Y} по {b:%d.%m.%Y}'
        elif mode=='От подписания до даты':
            try: deadline=datetime.strptime(self.v['deadline'].get().strip(),'%d.%m.%Y')
            except ValueError:raise ValueError('Укажите дату окончания в формате ДД.ММ.ГГГГ.')
            o.delivery=f'С даты подписания контракта по {deadline:%d.%m.%Y}'
        elif mode=='Своя формулировка':o.delivery=self.v['delivery_text'].get().strip()
        date_line(o.concluded,o.conclusion_date)
        o.quantity_note=self.quantity_result().back_note()
        reduction(c,o);return c,o
    def refresh(self,preserve=False):
        import fitz
        from pdf_export import generate
        c,o=self.snapshot();new=tempfile.TemporaryDirectory(prefix='ContractPrintApp-')
        try:outputs=generate(c,o,new.name);pdf=fitz.open(outputs['duplex'])
        except Exception:new.cleanup();raise
        old=(self.page,self.zoom,getattr(self,'fit_enabled',True),self.pcanvas.yview(),self.pcanvas.xview())
        self.clear_preview();self.temp=new;self.outputs=outputs;self.pdf=pdf
        self.page=min(old[0],len(pdf)-1) if preserve else 0;self.zoom=old[1];self.fit_enabled=old[2] if preserve else True
        if not preserve:self.fit_mode='Весь лист';self.scale_choice.set('Весь лист')
        self.build_thumbnails();self.render();self._preview_state=self.card_state()
        if preserve and old[3]:self.pcanvas.yview_moveto(old[3][0]);self.pcanvas.xview_moveto(old[4][0])
    def preview_click(self):
        if not self.need():return
        try:self.root.update_idletasks();self.refresh()
        except Exception as e:messagebox.showerror('Формирование PDF',str(e))
    def remember(self):
        self.settings['folder']=self.folder.get();self.settings.pop('theme',None)
        self.settings['window_size']=f'{self.root.winfo_width()}x{self.root.winfo_height()}'
        if str(self.editor) in self.workspace.panes():self.settings['divider']=self.workspace.sashpos(0)
        try:self.settings_path.parent.mkdir(parents=True,exist_ok=True);self.settings_path.write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),'utf-8')
        except OSError:
            self.status.set('Не удалось сохранить настройки. Проверьте права на папку user-data рядом с программой.')
    def choose_folder(self):
        p=filedialog.askdirectory(title='Папка сохранения PDF',initialdir=self.folder.get() if Path(self.folder.get()).is_dir() else str(Path.home()))
        if p:self.folder.set(p);self.remember()
    def target(self):
        folder=Path(self.folder.get())
        if not folder.is_dir():
            messagebox.showinfo('Папка недоступна','Выберите доступную папку для сохранения.');self.choose_folder();folder=Path(self.folder.get())
        if not folder.is_dir():raise ValueError('Папка сохранения недоступна.')
        return folder/filename(self.file_name.get())
    def save(self):
        from pdf_export import atomic_copy
        if not self.need():return
        try:
            self.refresh();dest=self.target()
            if dest.exists():
                choice=messagebox.askyesnocancel('Файл уже существует',f'{dest.name}\nДа — заменить; Нет — сохранить новую копию; Отмена — вернуться.\nДля замены закройте PDF и панель предпросмотра Проводника (Alt+P).')
                if choice is None:return
                if not choice:
                    n=2;base=dest
                    while dest.exists():dest=base.with_name(base.stem+f' ({n})'+base.suffix);n+=1
            atomic_copy(self.outputs['duplex'],dest);self.mark_saved();self.remember();self.status.set('Сохранено: '+str(dest));self.saved_dialog(dest)
        except Exception as e:messagebox.showerror('Сохранение',str(e))
    def save_separate(self):
        from pdf_export import atomic_copy
        if not self.need():return
        try:
            self.refresh();dest=self.target();targets=[dest.with_name(dest.stem+'_Лицевые.pdf'),dest.with_name(dest.stem+'_Оборот.pdf')]
            if any(p.exists() for p in targets) and not messagebox.askyesno('Заменить файлы?','Отдельные PDF уже существуют. Заменить их?'):return
            for k,p in zip(('fronts','back'),targets):atomic_copy(self.outputs[k],p)
            self.mark_saved();self.remember();messagebox.showinfo('PDF сохранены','\n'.join(map(str,targets)))
        except Exception as e:messagebox.showerror('Сохранение',str(e))
    def print_dialog(self):
        from printing import printers, print_pdf
        if not self.need():return
        try:self.refresh();names,default=printers()
        except Exception as e:messagebox.showerror('Печать',str(e));return
        if not names:messagebox.showinfo('Принтеры','Принтеры Windows не найдены. Можно сохранить PDF и напечатать его на другом компьютере.');return
        win=new_dialog(self.root,'Печать',640,340)
        f=ttk.Frame(win,padding=18);f.pack(fill='both',expand=True)
        name=tk.StringVar(value=self.settings.get('printer',default));
        if name.get() not in names:name.set(default if default in names else names[0])
        ttk.Label(f,text='Принтер').pack(anchor='w');ttk.Combobox(f,textvariable=name,values=names,state='readonly',width=70).pack(fill='x',pady=5)
        modes=('Двусторонняя: весь комплект','Односторонняя: все лицевые','Односторонняя: оборот первого листа');mode=tk.StringVar(value=self.settings.get('print_mode',modes[0]));
        if mode.get() not in modes:mode.set(modes[0])
        ttk.Combobox(f,textvariable=mode,values=modes,state='readonly',width=70).pack(fill='x',pady=8)
        ttk.Label(f,text='Копий').pack(anchor='w');copies=tk.StringVar(value='1');ttk.Spinbox(f,from_=1,to=99,textvariable=copies,width=5).pack(anchor='w')
        ttk.Label(f,text='A4 · книжная · 100% · двусторонняя по длинному краю.\nДля ручной печати сначала печатайте лицевые, затем только оборот\nпервого листа. Ориентацию повторной подачи проверьте на одном листе.',wraplength=590).pack(anchor='w',pady=14)
        def run():
            try:count=int(copies.get());assert 1<=count<=99
            except (ValueError,AssertionError):messagebox.showerror('Копии','Введите число от 1 до 99.',parent=win);return
            selected=name.get();selected_mode=mode.get();idx=modes.index(selected_mode);path=str(self.outputs[('duplex','fronts','back')[idx]])
            self.settings.update(printer=selected,print_mode=selected_mode);self.remember();self.busy=True;win.destroy();self.status.set('Документ передаётся принтеру…')
            def worker():
                try:print_pdf(path,selected,duplex=idx==0,copies=count);self.events.put(('ok','Документ передан в очередь печати.'))
                except Exception as e:self.events.put(('error',str(e)))
            threading.Thread(target=worker,daemon=True).start()
        ttk.Button(f,text='Напечатать',command=run).pack(side='right')
    def poll(self):
        try:
            kind,msg=self.events.get_nowait();self.busy=False
            if kind=='notice':self.status.set('Извещение получено. Проверьте найденные поля.');self.review_notice(msg)
            elif kind=='delivery':self.status.set('Поиск сроков завершён. Проверьте результат.');self.review_delivery(*msg)
            else:
                self.status.set(msg)
                if kind in ('error','eis_error','delivery_error'):messagebox.showerror('Word' if kind=='delivery_error' else 'ЕИС' if kind=='eis_error' else 'Печать',msg)
            self.update_check();self.schedule_preview()
        except queue.Empty:pass
        self.root.after(150,self.poll)
    def close(self):
        if not self.guard():return
        self.remember();self.clear_preview();self.root.destroy()

def make_root():
    from branding import set_taskbar_identity, set_window_icon
    set_taskbar_identity()
    if sys.platform=='win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:pass
    try:
        from tkinterdnd2 import TkinterDnD
        root=TkinterDnD.Tk()
    except ImportError:root=tk.Tk()
    set_window_icon(root)
    return root

def self_test(output):
    """Small startup/PDF check with synthetic data in an isolated directory."""
    import traceback
    import app_paths
    root=None;report={'status':'error'}
    previous=app_paths.SETTINGS_OVERRIDE
    try:
        with tempfile.TemporaryDirectory(prefix='ContractPrintApp-check-') as tmp:
            app_paths.SETTINGS_OVERRIDE=Path(tmp)/'settings.json'
            root=make_root();app=Application(root)
            root.update_idletasks()
            from branding import window_icon_state
            icon_state=window_icon_state(root)
            if not all(icon_state.values()):
                raise RuntimeError('Application icon check failed: '+str(icon_state))
            if app.firms:raise RuntimeError('Initial directory must be empty')
            demo_inn='0'*10
            app.firms={demo_inn:('DEMO','Демонстрационная организация')}
            app.rebuild_supplier_choices();app.choose_supplier('DEMO')
            if app.v['inn'].get()!=demo_inn:raise RuntimeError('Local supplier recognition failed')
            app.contract=Contract(number='DEMO',supplier='DEMO',customer='Пример',total='100.00',
                items=[Item(no='1',name='Демонстрационная позиция',qty='1 шт.',price='100.00',total='100.00')])
            for key in ('number','supplier','customer','total'):app.v[key].set(getattr(app.contract,key))
            root.update();app.restore_divider();app.refresh()
            from startup_check import wait_for_preview
            state=wait_for_preview(app)
            if len(app.pdf)!=2:raise RuntimeError('Unexpected PDF page count')
            report={'status':'ok','icon_state':icon_state,'preview_state':state,'checks':['application_icon','empty_directory','local_supplier','window','pdf','preview','thumbnails']}
            app.clear_preview();root.destroy();root=None
    except Exception as e:
        report={'status':'error','error':str(e),'traceback':traceback.format_exc()}
    finally:
        if root is not None:
            try:root.destroy()
            except Exception:pass
        app_paths.SETTINGS_OVERRIDE=previous
        Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['status']=='ok' else 1

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--apply-update':
        from updater import apply_plan
        try:apply_plan(sys.argv[2])
        except Exception as e:
            if sys.platform=='win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,str(e),'Обновление ContractPrintApp',0x10)
            else:raise
            sys.exit(1)
        sys.exit(0)
    if len(sys.argv)==3 and sys.argv[1]=='--self-test':
        sys.exit(self_test(sys.argv[2]))
    instance_lock=None
    if getattr(sys,'frozen',False):
        from updater import InstallLock
        try:instance_lock=InstallLock(Path(sys.executable).resolve().parent).acquire()
        except OSError:
            if sys.platform=='win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,'Не удалось получить блокировку папки программы. Возможно, идёт обновление или нет права записи. Дождитесь завершения обновления и проверьте права на папку.','ContractPrintApp',0x10)
            sys.exit(1)
    root=make_root();root.withdraw();Application(root);root.deiconify();root.mainloop()
    if instance_lock:instance_lock.close()
