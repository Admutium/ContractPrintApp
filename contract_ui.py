"""Small editing conveniences; history lives only for the current loaded card."""
import json,re,sys
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from core import Item

UI_FONT='Segoe UI' if sys.platform=='win32' else 'DejaVu Sans'

class Editing:
    def restore_divider(self):
        if len(self.workspace.panes())!=2:return
        width=self.workspace.winfo_width()
        if width<100:
            self.root.after(100,self.restore_divider);return
        wanted=self.settings.get('divider',min(550,width//2))
        if not isinstance(wanted,int):wanted=550
        self.workspace.sashpos(0,max(460,min(wanted,max(460,width-400))))

    def pair_fields(self,first,second,day_type=False):
        bar=ttk.Frame(self.form);bar.grid(row=self.row,columnspan=2,sticky='ew',pady=4)
        for col,(key,label) in enumerate((first,second)):
            group=ttk.Frame(bar);group.grid(row=0,column=col,sticky='ew',padx=(0,8));bar.columnconfigure(col,weight=1)
            ttk.Label(group,text=label).pack(anchor='w')
            var=self.v[key]=tk.StringVar(value='календарных' if key=='day_type' else '')
            w=(ttk.Combobox(group,textvariable=var,values=('календарных','рабочих'),state='readonly',width=15)
               if key=='day_type' else ttk.Entry(group,textvariable=var,width=15))
            w.pack(fill='x',pady=(3,0));self.entries[key]=w;self.field_widgets[key]=(group,);self.field_tab[key]=self.form
        self.row+=1

    def active_dates(self):
        mode=self.v['delivery_mode'].get()
        return ['created_date']+(['conclusion_date'] if self.v['concluded'].get()=='Да' else [])+(['date_from','date_to'] if mode=='Период дат' else ['deadline'] if mode=='От подписания до даты' else [])

    def normalize_dates(self,event=None):
        for key in self.active_dates():
            value=self.v[key].get().strip()
            if re.fullmatch(r'\d{8}',value):
                try:parsed=datetime.strptime(value,'%d%m%Y')
                except ValueError:continue
                self.v[key].set(parsed.strftime('%d.%m.%Y'))
        self.schedule_check()

    def reset_history(self):
        self._history=[self.card_state()] if self.contract else []
        self.note.edit_reset()

    def capture_edit(self):
        if getattr(self,'_restoring',False) or not self.contract:return
        state=self.card_state()
        if not self._history or state!=self._history[-1]:
            self._history.append(state);self._history=self._history[-80:]

    def undo_card(self,event=None):
        if event and event.widget.winfo_toplevel()!=self.root:return
        if self.busy:return 'break'
        self.capture_edit()
        if len(self._history)<2:return 'break'
        self._history.pop();state=json.loads(self._history[-1]);self._restoring=True
        try:
            for key,value in state['fields'].items():self.v[key].set(value)
            self.manual.set(state['manual']);self.increased.set(state['increase']);self.include_note.set(state['include_note'])
            self.note.delete('1.0','end');self.note.insert('1.0',state['note']);self.note.edit_reset();self.note.edit_modified(False)
            self.contract.items=[Item(**item) for item in state['items']]
            from eis import Notice
            from quantity_check import NoticeItem
            notice=state.get('notice_snapshot')
            self._notice_snapshot=Notice(**{**notice,'items':[NoticeItem(**i) for i in notice.get('items',[])]}) if notice else None
            self._quantity_key=None
            self.populate();self.controls();self.update_name();self.update_check()
        finally:self._restoring=False
        self.schedule_preview();self.status.set('Последнее изменение отменено.');return 'break'

    def wheel_forms(self,event):
        if event.state & 4:return
        w=event.widget
        while w is not None:
            if w in self.form_canvases.values():
                step=1 if getattr(event,'delta',0)>0 or getattr(event,'num',0)==4 else -1
                w.yview_scroll(-step*3,'units');return 'break'
            w=getattr(w,'master',None)

    def install_editing(self):
        for key in ('date_from','date_to','deadline','created_date','conclusion_date'):self.entries[key].bind('<FocusOut>',self.normalize_dates)
        self.root.bind('<Control-z>',self.undo_card);self.root.bind('<Control-Z>',self.undo_card)
        def save(event):
            if event.widget.winfo_toplevel()==self.root:self.save();return 'break'
        def print_card(event):
            if event.widget.winfo_toplevel()==self.root:self.print_dialog();return 'break'
        for key in ('<Control-s>','<Control-S>'):self.root.bind(key,save)
        for key in ('<Control-p>','<Control-P>'):self.root.bind(key,print_card)
        for key in ('<MouseWheel>','<Button-4>','<Button-5>'):self.root.bind_all(key,self.wheel_forms,add='+')
