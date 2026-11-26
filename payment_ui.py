"""Lazy execution-security tab and a separate one-page preview/export path."""
import tempfile,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from dialogs import messagebox,filedialog,new_dialog
from payment_data import PaymentSource,PARTY_FIELDS,MODES,parse_payment_html,calculate,validate

LABELS={'name':'Полное наименование','inn':'ИНН','kpp':'КПП','account':'Расчётный / казначейский счёт','bank':'Наименование банка','bik':'БИК','bank_account':'Корреспондентский счёт / ЕКС'}

class PaymentUI:
    def init_payment(self):
        self.payment_tab=ttk.Frame(self.book);self.book.add(self.payment_tab,text='Платёжное поручение');self.book.insert(1,self.payment_tab)
        self._payment_built=False;self._payment_job=None;self._payment_temp=None
        self._payment_source_path=None;self._payment_raw=None;self._payment_identity=None
        self._payment_dirty=set();self._payment_updating=False;self._payment_render_key=None
        self.payment_vars={};self._payment_eis=None
        ttk.Label(self.payment_tab,text='Обеспечение исполнения контракта.\nОткройте вкладку после загрузки HTML.',padding=18).pack(anchor='w')

    def payment_active(self):
        return hasattr(self,'payment_tab') and self.book.select()==str(self.payment_tab)

    def reset_payment(self,path=None):
        if self._payment_job:self.root.after_cancel(self._payment_job);self._payment_job=None
        self._payment_source_path=Path(path) if path else None;self._payment_raw=None;self._payment_identity=None
        self._payment_dirty.clear();self._payment_render_key=None;self._payment_eis=None
        if self._payment_built:
            self._payment_updating=True
            try:
                for var in self.payment_vars.values():var.set('')
            finally:self._payment_updating=False
            self.payment_canvas.delete('all');self.payment_info.set('Загрузите контракт для заполнения поручения.')
        if self._payment_temp:self._payment_temp.cleanup();self._payment_temp=None

    def build_payment_tab(self):
        if self._payment_built:return
        for child in self.payment_tab.winfo_children():child.destroy()
        canvas=tk.Canvas(self.payment_tab,highlightthickness=0)
        scroll=ttk.Scrollbar(self.payment_tab,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        body=ttk.Frame(canvas,padding=12);window=canvas.create_window(0,0,anchor='nw',window=body)
        body.columnconfigure(1,weight=1)
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        self.form_canvases['Платёжное поручение']=canvas
        ttk.Label(body,text='Обеспечение исполнения контракта',font=('Segoe UI',11,'bold'),wraplength=440).grid(row=0,columnspan=2,sticky='w',pady=(0,7))
        self.payment_info=tk.StringVar()
        ttk.Label(body,textvariable=self.payment_info,wraplength=440).grid(row=1,columnspan=2,sticky='w',pady=(0,10))
        row=2
        def section(title):
            nonlocal row
            ttk.Separator(body).grid(row=row,columnspan=2,sticky='ew',pady=9);row+=1
            ttk.Label(body,text=title,font=('Segoe UI',10,'bold')).grid(row=row,columnspan=2,sticky='w',pady=4);row+=1
        def field(key,label,values=None):
            nonlocal row
            ttk.Label(body,text=label,wraplength=165).grid(row=row,column=0,sticky='nw',padx=(0,8),pady=4)
            var=self.payment_vars[key]=tk.StringVar()
            if values:
                widget=ttk.Combobox(body,textvariable=var,values=values,state='readonly',width=22)
            else:widget=ttk.Entry(body,textvariable=var,width=24)
            widget.grid(row=row,column=1,sticky='ew',pady=4)
            var.trace_add('write',lambda *args,k=key:self.payment_edited(k));row+=1
        field('mode','Размер обеспечения',MODES)
        field('percent','Процент, %');field('notice_amount','Сумма из HTML / извещения, руб.')
        field('custom','Своя сумма, руб.')
        self.payment_amount=tk.StringVar(value='Сумма не определена')
        ttk.Label(body,textvariable=self.payment_amount,wraplength=440,font=('Segoe UI',11,'bold')).grid(row=row,columnspan=2,sticky='w',pady=7);row+=1
        section('Плательщик — наша организация')
        field('payer_name',LABELS['name'])
        section('Получатель обеспечения исполнения')
        for key in PARTY_FIELDS:field('recipient_'+key,LABELS[key])
        section('Платёжное поручение')
        field('purpose','Назначение платежа')
        ttk.Label(body,text='Длинные названия и назначение печатаются целиком, с переносом строк.',wraplength=440).grid(row=row,columnspan=2,sticky='w',pady=6);row+=1
        section('Дополнительные реквизиты — при необходимости')
        for key,label in (('account_type','Тип счёта'),('personal','Лицевой счёт'),('counterparty','Контрагент для п/п'),('kbk','КБК'),('oktmo','ОКТМО'),('uin','УИН'),('status','Статус (101)'),('tax_basis','Основание (106)'),('tax_period','Период (107)'),('tax_number','Номер документа (108)'),('tax_date','Дата документа (109)'),('tax_type','Тип платежа (110)')):field(key,label)
        buttons=ttk.Frame(body);buttons.grid(row=row,columnspan=2,sticky='ew',pady=12)
        ttk.Button(buttons,text='Сохранить PDF',command=self.save_payment).pack(side='left')
        ttk.Button(buttons,text='Печать',command=self.print_payment).pack(side='left',padx=6)
        self.payment_overlay=ttk.Frame(self.preview,padding=8)
        ttk.Label(self.payment_overlay,text='Документ для бухгалтерии · A4',font=('Segoe UI',11,'bold')).pack(anchor='w')
        self.payment_preview_info=tk.StringVar(value='')
        ttk.Label(self.payment_overlay,textvariable=self.payment_preview_info,wraplength=460).pack(fill='x')
        frame=ttk.Frame(self.payment_overlay);frame.pack(fill='both',expand=True,pady=7)
        self.payment_canvas=tk.Canvas(frame,bg='#dfe3e8',highlightthickness=0)
        bar=ttk.Scrollbar(frame,command=self.payment_canvas.yview);self.payment_canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');self.payment_canvas.pack(fill='both',expand=True)
        self.payment_canvas.bind('<Configure>',lambda e:self.schedule_payment())
        self._payment_built=True

    def payment_tab_changed(self):
        if self.payment_active():
            self.build_payment_tab();self.payment_overlay.place(x=0,y=0,relwidth=1,relheight=1);self.payment_overlay.lift()
            self.sync_payment();self.schedule_payment()
        elif self._payment_built:
            self.payment_overlay.place_forget()
            if self._payment_job:self.root.after_cancel(self._payment_job);self._payment_job=None

    def payment_edited(self,key):
        if self._payment_updating:return
        self._payment_dirty.add(key)
        self.schedule_check()
        self.schedule_payment()

    def sync_payment(self):
        if not self.payment_active() or not self.contract:return
        if self._payment_identity is not self.contract:
            self._payment_identity=self.contract
            try:
                self._payment_raw=parse_payment_html(self._payment_source_path.read_bytes(),'HTML контракта') if self._payment_source_path else PaymentSource()
            except Exception as error:
                self._payment_raw=PaymentSource(warnings=['Не удалось прочитать реквизиты HTML: '+str(error)])
        source=self._payment_raw or PaymentSource()
        notice=getattr(self,'_notice_snapshot',None)
        # A cached notice belongs only to its exact current number.
        if notice and notice.number==self.v['notice'].get().strip() and notice.payment:
            eis=PaymentSource(**notice.payment)
        else:eis=PaymentSource()
        active=source if source.amount or source.percent or source.terms else eis
        defaults={key:'' for key in self.payment_vars}
        defaults.update({'recipient_'+key:source.recipient.get(key,'') for key in PARTY_FIELDS})
        defaults['recipient_name']=self.v['customer_full'].get().strip() or defaults['recipient_name']
        defaults['recipient_inn']=self.contract.customer_inn or defaults['recipient_inn']
        defaults['payer_name']=self.v['supplier_full'].get().strip()
        if not defaults['payer_name'] and self.v['inn'].get().strip()==self.contract.inn:
            defaults['payer_name']=source.payer.get('name','')
        defaults.update(source.extra)
        defaults.update(mode=active.mode,percent=active.percent,notice_amount=active.amount)
        contract_number=self.v['number'].get().strip();notice_number=self.v['notice'].get().strip()
        defaults['purpose']=source.purpose or ('Обеспечение исполнения контракта'+(' № '+contract_number if contract_number else '')+
            ('; извещение № '+notice_number if notice_number else '')+'; без НДС.')
        self._payment_updating=True
        try:
            for key,value in defaults.items():
                if key not in self._payment_dirty:self.payment_vars[key].set(value)
        finally:self._payment_updating=False
        self._payment_warnings=list(dict.fromkeys(source.warnings+eis.warnings))
        self._payment_origin=active.source or 'HTML: условия обеспечения не найдены'

    def payment_data(self):
        data={key:var.get().strip() for key,var in self.payment_vars.items()}
        error=''
        try:
            amount=calculate(data['mode'],percent=data['percent'],notice_amount=data['notice_amount'],
                contract_total=self.v['total'].get(),nmck=self.v['nmck'].get(),custom=data['custom'])
            data['amount']=str(amount)
        except ValueError as exc:data['amount']='0';error=str(exc)
        if data['mode'] in MODES[1:3]:
            data['rate_basis']=data['mode'].removeprefix('% от ')
        data['contract_number']=self.v['number'].get().strip()
        if data.get('personal'):
            data['purpose']+=(' Лицевой счёт '+data['personal']+'.') if data['personal'] not in data['purpose'] else ''
        problems=validate(data)
        if error:problems.insert(0,error)
        if not self.contract:problems.insert(0,'Загрузите HTML контракта')
        return data,problems

    def schedule_payment(self):
        if not self.payment_active() or not self._payment_built:return
        if self._payment_job:self.root.after_cancel(self._payment_job)
        self._payment_job=self.root.after(350,self.render_payment)

    def render_payment(self):
        self._payment_job=None
        if not self.payment_active() or not self.contract:return
        try:
            self.sync_payment();data,problems=self.payment_data()
            from core import money
            self.payment_amount.set('Обеспечение: '+money(data['amount'])+' руб.')
            notes=[self._payment_origin]+getattr(self,'_payment_warnings',[])
            notes+=problems
            self.payment_info.set('\n'.join(notes))
            draft=bool(problems)
            key=(tuple(sorted(data.items())),draft)
            if key!=self._payment_render_key:
                from payment_pdf import generate_payment
                if not self._payment_temp:self._payment_temp=tempfile.TemporaryDirectory(prefix='ContractPrintApp-payment-')
                path=Path(self._payment_temp.name)/'payment.pdf'
                generate_payment(data,path,draft=draft);self._payment_render_key=key
            import fitz
            from PIL import Image,ImageTk
            with fitz.open(Path(self._payment_temp.name)/'payment.pdf') as doc:
                page=doc[0];w=max(200,self.payment_canvas.winfo_width());h=max(300,self.payment_canvas.winfo_height())
                scale=max(.15,min((w-24)/page.rect.width,(h-24)/page.rect.height,1.5))
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            self._payment_image=ImageTk.PhotoImage(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
            self.payment_canvas.delete('all');self.payment_canvas.create_image(max(12,(w-pix.width)//2),12,anchor='nw',image=self._payment_image)
            self.payment_canvas.configure(scrollregion=(0,0,max(w,pix.width+24),pix.height+24))
            self.payment_preview_info.set('ЧЕРНОВИК · проверьте замечания слева' if draft else 'Документ для передачи в бухгалтерию')
        except Exception as error:
            # Never leave a stale, valid-looking document after an invalid edit.
            self._payment_render_key=None;self.payment_canvas.delete('all')
            self.payment_preview_info.set('Поручение не сформировано: '+str(error))

    def prepare_payment(self):
        if not self.need():return None
        self.build_payment_tab();self.sync_payment()
        data,problems=self.payment_data()
        if problems:
            if not messagebox.askyesno('Незаполненное поручение','\n'.join(problems)+'\n\nСформировать черновик с отметкой «ЧЕРНОВИК»?',parent=self.root):return None
        from payment_pdf import generate_payment
        if not self._payment_temp:self._payment_temp=tempfile.TemporaryDirectory(prefix='ContractPrintApp-payment-')
        path=Path(self._payment_temp.name)/'export.pdf'
        return generate_payment(data,path,draft=bool(problems))

    def save_payment(self):
        try:
            path=self.prepare_payment()
            if path is None:return
            import re
            from core import filename
            dest=filedialog.asksaveasfilename(parent=self.root,title='Сохранить платёжное поручение',
                initialdir=self.folder.get(),initialfile=filename('Обеспечение исполнения '+re.sub(r'[<>:"/\\|?*]','_',self.v['number'].get())[:100].rstrip(' .')),defaultextension='.pdf',filetypes=[('PDF','*.pdf')])
            if not dest:return
            from pdf_export import atomic_copy
            atomic_copy(path,Path(dest));self.status.set('Платёжное поручение сохранено: '+dest)
            self.mark_saved();self.saved_dialog(Path(dest))
        except Exception as error:messagebox.showerror('Платёжное поручение',str(error),parent=self.root)

    def print_payment(self):
        try:
            path=self.prepare_payment()
            if path is None:return
            from printing import printers,print_pdf
            names,default=printers()
            if not names:
                messagebox.showinfo('Принтеры','Принтеры Windows не найдены. Сохраните поручение в PDF.',parent=self.root);return
            win=new_dialog(self.root,'Печать платёжного поручения',620,260)
            frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
            printer=tk.StringVar(value=self.settings.get('printer',default));copies=tk.StringVar(value='1')
            if printer.get() not in names:printer.set(default if default in names else names[0])
            ttk.Label(frame,text='Принтер · A4, одна сторона, 100%').pack(anchor='w')
            ttk.Combobox(frame,textvariable=printer,values=names,state='readonly').pack(fill='x',pady=8)
            ttk.Label(frame,text='Копий').pack(anchor='w');ttk.Spinbox(frame,from_=1,to=99,textvariable=copies,width=6).pack(anchor='w')
            def run():
                try:
                    count=int(copies.get())
                    if not 1<=count<=99:raise ValueError()
                except ValueError:messagebox.showerror('Копии','Введите число от 1 до 99.',parent=win);return
                # Private job copy survives edits/reset and closing the print dialog.
                job=tempfile.TemporaryDirectory(prefix='ContractPrintApp-payment-print-')
                from shutil import copy2
                job_path=Path(job.name)/'payment.pdf';copy2(path,job_path)
                selected=printer.get();self.settings['printer']=selected;self.remember()
                self.busy=True;win.destroy();self.status.set('Платёжное поручение передаётся принтеру…')
                def worker():
                    try:print_pdf(job_path,selected,duplex=False,copies=count);self.events.put(('ok','Платёжное поручение передано в очередь печати.'))
                    except Exception as error:self.events.put(('error',str(error)))
                    finally:job.cleanup()
                threading.Thread(target=worker,daemon=True).start()
            ttk.Button(frame,text='Напечатать',command=run).pack(anchor='e',pady=12)
        except Exception as error:messagebox.showerror('Печать поручения',str(error),parent=self.root)
