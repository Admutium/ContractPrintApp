"""In-memory card state, automatic preview and reviewed Word import."""
import json, threading
from dataclasses import asdict
from pathlib import Path
from contract_ui import UI_FONT
import tkinter as tk
from tkinter import ttk
from dialogs import messagebox,filedialog,new_dialog,scroll_body
from tkinter.scrolledtext import ScrolledText

class Workflow:
    def card_state(self):
        if self.contract is None:return ''
        return json.dumps({'fields':{k:v.get() for k,v in self.v.items()},
            'manual':self.manual.get(),'increase':self.increased.get(),
            'include_note':self.include_note.get(),'note':self.note.get('1.0','end-1c'),
            'notice_snapshot':asdict(self._notice_snapshot) if getattr(self,'_notice_snapshot',None) else None,
            'items':[asdict(i) for i in self.contract.items]},ensure_ascii=False,sort_keys=True)

    def mark_saved(self):self._saved_state=self.card_state()

    def confirm_replace(self):
        return (not self.contract or self.card_state()==getattr(self,'_saved_state','') or
            messagebox.askyesno('Несохранённые изменения','В текущей карточке есть несохранённые изменения. Загрузить другой контракт и сбросить их?',parent=self.root))

    def note_changed(self,event=None):
        if self.note.edit_modified():
            self.note.edit_modified(False);self.schedule_check()

    def tab_changed(self,event=None):
        self.update_check();self.schedule_preview()

    def schedule_preview(self):
        job=getattr(self,'_auto_job',None)
        if job:self.root.after_cancel(job)
        self._auto_job=None
        if not self.contract or not hasattr(self,'preview'):return
        if self.card_state()==getattr(self,'_preview_state',None):return
        self._auto_job=self.root.after(650,self.auto_preview)

    def auto_preview(self):
        self._auto_job=None
        if self.busy or not self.contract:return
        try:self.refresh(preserve=True)
        except Exception as e:self.page_label.set('Предпросмотр не обновлён: '+str(e))

    def delivery_dialog(self,path=None):
        if not self.need():return
        if not path:path=filedialog.askopenfilename(parent=self.root,title='Документ со сроком поставки',filetypes=[('Word','*.docx *.doc')])
        if not path:return
        self.busy=True;self.update_check();self.status.set('Ищу сроки поставки в '+Path(path).name+'…')
        def worker():
            try:
                from delivery import load_delivery
                self.events.put(('delivery',(load_delivery(path),Path(path).name)))
            except Exception as e:self.events.put(('delivery_error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def review_delivery(self,result,name):
        if not result.main and not result.request:
            messagebox.showinfo('Сроки не найдены','\n'.join(result.warnings)+'\nМожно заполнить оба поля вручную.',parent=self.root);return
        win=new_dialog(self.root,'Сроки поставки · '+name,940,740)
        area,outer=scroll_body(win)
        warnings=list(result.warnings)
        notice=self.v['notice'].get().strip()
        if notice and result.notice_numbers and notice not in result.notice_numbers:
            warnings.insert(0,'Номер извещения в Word отличается от текущей карточки. Проверьте, что выбран правильный документ.')
        ttk.Label(outer,text='Проверьте исходные пункты, при необходимости исправьте текст и отметьте поля для переноса.',wraplength=880).pack(anchor='w',pady=(0,5))
        if warnings:ttk.Label(outer,text='\n'.join(warnings),wraplength=880).pack(anchor='w',pady=(0,6))
        edits=[]
        for kind,title,current in [('main','Основной срок → лицевая сторона',self.v['delivery_mode'].get()!='Пустые поля'),('request','Срок по заявке → оборот',bool(self.v['request_delivery'].get().strip()))]:
            candidates=getattr(result,kind)
            group=ttk.LabelFrame(outer,text=title,padding=8);group.pack(fill='both',expand=True,pady=5)
            if not candidates:
                ttk.Label(group,text='Не найден. Текущее значение останется без изменений.').pack(anchor='w');continue
            enabled=tk.BooleanVar(value=len(candidates)==1 and not current)
            ttk.Checkbutton(group,text='Перенести в карточку'+(' (заменить текущее значение)' if current else ''),variable=enabled).pack(anchor='w')
            labels=['Выберите вариант']+[x.location+' · '+x.value[:100] for x in candidates]
            choice=ttk.Combobox(group,values=labels,state='readonly');choice.pack(fill='x',pady=4)
            value=ScrolledText(group,height=2,wrap='word',font=(UI_FONT,10));value.pack(fill='x')
            source=ScrolledText(group,height=3,wrap='word',font=(UI_FONT,9));source.pack(fill='both',expand=True,pady=(4,0));source.configure(state='disabled')
            def choose(event=None,c=candidates,cb=choice,v=value,s=source):
                index=cb.current()-1;v.delete('1.0','end');s.configure(state='normal');s.delete('1.0','end')
                if index>=0:v.insert('1.0',c[index].value);s.insert('1.0',c[index].location+'\n'+c[index].source)
                s.configure(state='disabled')
            choice.bind('<<ComboboxSelected>>',choose);choice.current(1 if len(candidates)==1 else 0);choose()
            edits.append((kind,enabled,choice,value))
        def apply():
            selected=[]
            for kind,enabled,choice,value in edits:
                if not enabled.get():continue
                text=value.get('1.0','end-1c').strip()
                if choice.current()<1 or not text:
                    messagebox.showinfo('Выберите срок','Выберите исходный вариант и заполните текст для переноса.',parent=win);return
                selected.append((kind,text))
            if not selected:
                messagebox.showinfo('Перенос','Отметьте хотя бы одно поле для переноса.',parent=win);return
            self.capture_edit();self._restoring=True
            for kind,text in selected:
                if kind=='main':self.v['delivery_mode'].set('Своя формулировка');self.v['delivery_text'].set(text)
                else:self.v['request_delivery'].set(text)
            self._restoring=False;self.capture_edit()
            self.status.set('Сроки перенесены из '+name);self.controls();self.schedule_check();win.destroy()
        buttons=ttk.Frame(win,padding=10);buttons.pack(side='bottom',fill='x')
        area.pack_forget();area.pack(fill='both',expand=True)
        ttk.Button(buttons,text='Отмена',command=win.destroy).pack(side='right',padx=6)
        ttk.Button(buttons,text='Перенести выбранное',style='Accent.TButton',command=apply).pack(side='right')
