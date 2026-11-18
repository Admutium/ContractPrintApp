"""Background EIS enrichment, bound to a loaded card and its field edits."""
import threading
from eis import notice_url,fetch_notice

FIELDS=('procurement_method','nmck','smp','life','etp','ikz')


class AutoEIS:
    def init_auto_eis(self):
        self._eis_job=None;self._eis_ticket=None;self._eis_baseline=None
        self._applying_eis=False
        self._eis_edits={key:0 for key in (*FIELDS,'custom_etp','notice')}
        for key in self._eis_edits:
            self.v[key].trace_add('write',lambda *args,k=key:self.eis_field_edited(k))

    def eis_field_edited(self,key):
        if not self._applying_eis:
            self._eis_edits[key]+=1
            if key=='notice' and (self._eis_job or self._eis_ticket is not None):
                self.cancel_auto_eis(clear_baseline=False)
                self.eis_source.set('Номер извещения изменён. Повторить загрузку — «Получить из ЕИС».')

    def cancel_auto_eis(self,clear_baseline=True):
        if self._eis_job:
            self.root.after_cancel(self._eis_job);self._eis_job=None
        self._eis_ticket=None
        if clear_baseline:self._eis_baseline=None

    def schedule_auto_eis(self):
        self.cancel_auto_eis()
        self._eis_baseline=dict(self._eis_edits)
        self._eis_job=self.root.after(1000,self.start_eis_request)

    def start_eis_request(self):
        if self._eis_job:
            self.root.after_cancel(self._eis_job);self._eis_job=None
        if self.contract is None:return
        number=self.v['notice'].get().strip()
        try:notice_url(number)
        except ValueError:
            self.eis_source.set('ЕИС: укажите корректный номер извещения и нажмите «Получить из ЕИС».');return
        if self._eis_ticket is not None:return
        if self._eis_baseline is None:self._eis_baseline=dict(self._eis_edits)
        ticket={'contract':self.contract,'number':number,'edits':dict(self._eis_baseline),
                'notice_edit':self._eis_edits['notice']}
        self._eis_ticket=ticket
        self.eis_source.set('Получаем данные ЕИС… Можно продолжать работу с карточкой.')
        def worker():
            try:self.events.put(('auto_notice',(ticket,fetch_notice(number),None)))
            except Exception as error:self.events.put(('auto_notice',(ticket,None,str(error))))
        threading.Thread(target=worker,daemon=True).start()

    def finish_auto_notice(self,ticket,result,error):
        if ticket is not self._eis_ticket:return
        self._eis_ticket=None
        if (self.contract is not ticket['contract'] or self.v['notice'].get().strip()!=ticket['number']
                or self._eis_edits['notice']!=ticket['notice_edit']):return
        if error:
            self.eis_source.set('ЕИС: '+error+' Повторить — «Получить из ЕИС».')
            return
        if result is None or result.number!=ticket['number']:
            self.eis_source.set('ЕИС: номер ответа не совпал с текущим извещением. Данные не перенесены.');return
        self.capture_edit();self._applying_eis=True;self._restoring=True
        changed=[]
        try:
            for key in FIELDS:
                value=result.values.get(key)
                if value is None or not str(value).strip():continue
                if self._eis_edits[key]!=ticket['edits'][key]:continue
                if key=='etp' and self._eis_edits['custom_etp']!=ticket['edits']['custom_etp']:continue
                if self.v[key].get()!=value:self.v[key].set(value);changed.append(key)
            self._notice_snapshot=result;self._quantity_key=None
        finally:self._restoring=False;self._applying_eis=False
        self.capture_edit()
        self.eis_info='Извещение № '+result.number+'; '+result.revision
        self.eis_source.set(self.eis_info+' · ЕИС применена автоматически, изменено полей: '+str(len(changed)))
        self.controls();self.update_check();self.schedule_preview()
