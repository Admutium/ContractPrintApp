"""Read-only EIS comparison panel, no manual override of comparison results."""
import copy
from dataclasses import asdict
import tkinter as tk
from tkinter import ttk
from quantity_check import compare
from contract_ui import UI_FONT
from dialogs import new_dialog

class QuantityPanel:
    def init_quantity_panel(self,parent):
        self._notice_snapshot=None;self._quantity_key=None
        self.quantity_title=tk.StringVar(value='Не удалось сравнить')
        ttk.Label(parent,textvariable=self.quantity_title,font=(UI_FONT,11,'bold')).pack(anchor='w',pady=(5,6))
        self.quantity_detail=tk.Text(parent,height=5,wrap='word',font=(UI_FONT,10),relief='flat',state='disabled')
        self.quantity_detail.pack(fill='x',pady=(0,8))
        area=ttk.Frame(parent);area.pack(fill='both',expand=True)
        cols=('no','name','before','after','delta','status')
        self.quantity_table=ttk.Treeview(area,columns=cols,show='headings',height=7)
        for key,label,width in zip(cols,('№','Позиция','ЕИС','Контракт','Изм.','Результат'),(30,110,80,90,55,115)):
            self.quantity_table.heading(key,text=label);self.quantity_table.column(key,width=width,stretch=False)
        vs=ttk.Scrollbar(area,command=self.quantity_table.yview);hs=ttk.Scrollbar(area,orient='horizontal',command=self.quantity_table.xview)
        self.quantity_table.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        vs.pack(side='right',fill='y');hs.pack(side='bottom',fill='x');self.quantity_table.pack(fill='both',expand=True)
        self.quantity_table.tag_configure('change',background='#fff2d2');self.quantity_table.tag_configure('unknown',background='#fff0ef')
        self.quantity_table.bind('<Double-1>',self.quantity_row_detail)
        ttk.Label(parent,text='Двойной щелчок — все сведения о строке.',wraplength=420).pack(anchor='w',pady=6)

    def quantity_result(self):
        from quantity_check import Comparison
        if self.contract is None:return Comparison(reason='Сначала загрузите контракт, затем извещение ЕИС.')
        c=copy.copy(self.contract);c.notice=self.v['notice'].get().strip()
        return compare(c,self._notice_snapshot)

    def update_quantity_panel(self):
        if not hasattr(self,'quantity_table'):return
        key=(id(self._notice_snapshot),self.v['notice'].get(),repr(self.contract.items) if self.contract else '',self.contract.unknown if self.contract else None)
        if key==self._quantity_key:return
        self._quantity_key=key;r=self.quantity_result();self.quantity_title.set(r.status)
        detail=r.reason
        if r.status=='Есть изменения':detail=r.back_note()
        if self._notice_snapshot:detail+='\nИзвещение № '+self._notice_snapshot.number+'\n'+self._notice_snapshot.revision
        self.quantity_detail.configure(state='normal');self.quantity_detail.delete('1.0','end');self.quantity_detail.insert('1.0',detail);self.quantity_detail.configure(state='disabled')
        self.quantity_table.delete(*self.quantity_table.get_children())
        self.quantity_rows={}
        for row in r.rows:
            tag='change' if row.status in ('Увеличение','Уменьшение') else 'unknown' if row.status!='Совпадает' else ''
            from quantity_check import quantity
            values=list(asdict(row).values())
            for n in (2,3):
                try:
                    amount,unit=quantity(values[n]);values[n]=format(amount,'f').replace('.',',')+' '+unit
                except ValueError:pass
            iid=self.quantity_table.insert('','end',values=values,tags=(tag,));self.quantity_rows[iid]=row

    def quantity_row_detail(self,event=None):
        sel=self.quantity_table.selection()
        if not sel:return
        vals=tuple(asdict(self.quantity_rows[sel[0]]).values());win=new_dialog(self.root,'Сверка количества',700,370)
        box=tk.Text(win,wrap='word',padx=14,pady=14,font=(UI_FONT,11));scroll=ttk.Scrollbar(win,command=box.yview);box.configure(yscrollcommand=scroll.set)
        close=ttk.Button(win,text='Закрыть',command=win.destroy);close.pack(side='bottom',pady=8)
        scroll.pack(side='right',fill='y');box.pack(fill='both',expand=True)
        box.insert('1.0','\n\n'.join(k+': '+v for k,v in zip(('№','Наименование','В ЕИС','В контракте','Разница','Результат'),vals)));box.configure(state='disabled')
