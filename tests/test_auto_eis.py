"""Auto-enrichment timing, stale replies and manual edit protection."""
import queue
import tkinter as tk
import unittest
from unittest.mock import patch
from auto_eis import AutoEIS,FIELDS
from eis import Notice

NUMBER='0'*19


class Scheduler:
    def __init__(self):self.jobs={};self.n=0
    def after(self,ms,callback):
        self.n+=1;self.jobs[self.n]=(ms,callback);return self.n
    def after_cancel(self,job):self.jobs.pop(job,None)
    def fire(self,job):self.jobs.pop(job)[1]()


class Card(AutoEIS):
    def __init__(self):
        self.tcl=tk.Tcl();self.root=Scheduler()
        self.v={key:tk.StringVar(self.tcl,value=NUMBER if key=='notice' else 'Ручной ввод' if key=='etp' else '') for key in (*FIELDS,'custom_etp','notice')}
        self.contract=object();self.events=queue.Queue();self.eis_source=tk.StringVar(self.tcl)
        self._notice_snapshot=None;self._restoring=False;self.busy=False;self.captures=0
        self.init_auto_eis()
    def capture_edit(self):self.captures+=1
    def controls(self):pass
    def update_check(self):pass
    def schedule_preview(self):pass
    def reply(self):
        kind,args=self.events.get(timeout=2)
        assert kind=='auto_notice'
        return args
    def fetch(self,result=None,error=None):
        self.schedule_auto_eis()
        with patch('auto_eis.fetch_notice',return_value=result,side_effect=error):
            self.root.fire(self._eis_job)
            return self.reply()


class AutoEISTests(unittest.TestCase):
    def test_delayed_background_apply_without_confirmation(self):
        c=Card();c.v['nmck'].set('50')
        c.schedule_auto_eis()
        self.assertEqual(c.root.jobs[c._eis_job][0],1000)
        with patch('auto_eis.fetch_notice',return_value=Notice(number=NUMBER,values={'nmck':'100','life':'Да'})):
            c.root.fire(c._eis_job);args=c.reply()
        self.assertFalse(c.busy)
        c.finish_auto_notice(*args)
        self.assertEqual(c.v['nmck'].get(),'100');self.assertEqual(c.v['life'].get(),'Да')
        self.assertEqual(c.captures,2)

    def test_edits_after_load_before_request_are_kept(self):
        c=Card();c.schedule_auto_eis();c.v['nmck'].set('25')
        with patch('auto_eis.fetch_notice',return_value=Notice(number=NUMBER,values={'nmck':'100'})):
            c.root.fire(c._eis_job);args=c.reply()
        c.finish_auto_notice(*args)
        self.assertEqual(c.v['nmck'].get(),'25')

    def test_edit_and_revert_while_request_runs_are_kept(self):
        c=Card();args=c.fetch(Notice(number=NUMBER,values={'nmck':'100','etp':'Росэлторг'}))
        c.v['nmck'].set('25');c.v['nmck'].set('')
        c.v['custom_etp'].set('Демонстрационная площадка')
        c.finish_auto_notice(*args)
        self.assertEqual(c.v['nmck'].get(),'')
        self.assertEqual(c.v['etp'].get(),'Ручной ввод')

    def test_reset_or_new_card_discards_old_reply(self):
        c=Card();args=c.fetch(Notice(number=NUMBER,values={'nmck':'100'}))
        c.cancel_auto_eis();c.contract=object();c.schedule_auto_eis()
        c.finish_auto_notice(*args)
        self.assertEqual(c.v['nmck'].get(),'');self.assertIsNone(c._notice_snapshot)

    def test_new_load_cancels_scheduled_request(self):
        c=Card();c.schedule_auto_eis();old=c._eis_job
        c.contract=object();c.schedule_auto_eis()
        self.assertNotIn(old,c.root.jobs)
        self.assertEqual(len(c.root.jobs),1)

    def test_edited_notice_and_mismatched_response_are_not_applied(self):
        c=Card();args=c.fetch(Notice(number=NUMBER,values={'nmck':'100'}))
        c.v['notice'].set('1'*19);c.v['notice'].set(NUMBER)
        c.finish_auto_notice(*args);self.assertIsNone(c._notice_snapshot)
        args=c.fetch(Notice(number='1'*19,values={'nmck':'100'}))
        c.finish_auto_notice(*args);self.assertIsNone(c._notice_snapshot)

    def test_error_and_undefined_values_keep_card_available(self):
        c=Card();c.v['nmck'].set('25')
        args=c.fetch(error=ValueError('offline'));c.finish_auto_notice(*args)
        self.assertEqual(c.v['nmck'].get(),'25');self.assertFalse(c.busy)
        self.assertIn('Повторить',c.eis_source.get())
        args=c.fetch(Notice(number=NUMBER,values={'nmck':None,'ikz':''}));c.finish_auto_notice(*args)
        self.assertEqual(c.v['nmck'].get(),'25')

    def test_auto_reply_does_not_release_printing_busy_state(self):
        from app import Application
        c=Card();args=c.fetch(Notice(number=NUMBER))
        c.poll=lambda:None
        c.busy=True;c.events.put(('auto_notice',args))
        Application.poll(c)
        self.assertTrue(c.busy)
