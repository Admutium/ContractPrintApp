"""Persistent preview, physical sheets and lazy thumbnails."""
from collections import OrderedDict
from contract_ui import UI_FONT
import tkinter as tk
from tkinter import ttk

def fit_scale(width,height,page_width,page_height,padding=24):
    return max(.05,min(max(1,width-padding)/page_width,max(1,height-padding)/page_height))

def visible_pages(count):return [i for i in range(count) if i<2 or i%2==0]

def page_description(index):
    return 'Карточка контракта' if index==1 else f'Лист {index//2+1}'

class Preview:
    def init_thumbnails(self,parent):
        side=ttk.Frame(parent);side.pack(side='right',fill='y',padx=(6,0))
        self.thumbs=tk.Canvas(side,width=108,highlightthickness=0,bg='#e5e9ef')
        scrollbar=ttk.Scrollbar(side,orient='vertical',command=self.scroll_thumbs)
        self.thumbs.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.thumbs.pack(fill='y',expand=True)
        self.thumb_cache=OrderedDict();self.thumb_images=[];self._thumb_job=None;self.visible=[]
        self.thumbs.bind('<Configure>',lambda e:self.queue_thumbnails())
        self.thumbs.bind('<Button-1>',self.click_thumbnail)
        self.thumbs.bind('<MouseWheel>',self.wheel_thumbnails)
        self.thumbs.bind('<Button-4>',lambda e:self.scroll_thumbs('scroll',-1,'units'))
        self.thumbs.bind('<Button-5>',lambda e:self.scroll_thumbs('scroll',1,'units'))

    def clear_thumbnails(self):
        for attr in ('_thumb_job','_preview_job'):
            job=getattr(self,attr,None)
            if job:self.root.after_cancel(job)
            setattr(self,attr,None)
        self.thumb_cache.clear();self.thumb_images=[];self.visible=[];self.thumbs.delete('all')
        self.thumbs.configure(scrollregion=(0,0,108,1));self.thumbs.yview_moveto(0);self.tkimage=None

    def build_thumbnails(self):
        self.visible=visible_pages(len(self.pdf))
        self.thumbs.configure(scrollregion=(0,0,108,len(self.visible)*156))
        self.thumbs.yview_moveto(0);self.queue_thumbnails()

    def queue_thumbnails(self):
        if self._thumb_job:self.root.after_cancel(self._thumb_job)
        self._thumb_job=self.root.after(40,self.draw_thumbnails)

    def scroll_thumbs(self,*args):self.thumbs.yview(*args);self.queue_thumbnails()

    def wheel_thumbnails(self,event):
        self.scroll_thumbs('scroll',-1 if event.delta>0 else 1,'units');return 'break'

    def click_thumbnail(self,event):
        n=int(self.thumbs.canvasy(event.y)//156)
        if self.pdf and 0<=n<len(self.visible):self.go_page(self.visible[n])

    def draw_thumbnails(self):
        self._thumb_job=None
        if self.pdf is None:return
        import fitz
        from PIL import Image,ImageTk
        canvas=self.thumbs;top=canvas.canvasy(0)
        first=max(0,int(top//156)-1);last=min(len(self.visible),int((top+canvas.winfo_height())//156)+2)
        canvas.delete('all');self.thumb_images=[]
        for slot in range(first,last):
            index=self.visible[slot]
            if index not in self.thumb_cache:
                page=self.pdf[index];scale=88/page.rect.width
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                self.thumb_cache[index]=ImageTk.PhotoImage(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
            picture=self.thumb_cache[index];self.thumb_cache.move_to_end(index);self.thumb_images.append(picture)
            y=slot*156+5
            canvas.create_rectangle(6,y-2,98,y+picture.height()+2,fill='white',outline='#2b6493' if index==self.page else '#b6c0ca',width=2)
            canvas.create_image(8,y,anchor='nw',image=picture)
            label='Карточка' if index==1 else f'Лист {index//2+1}'
            canvas.create_text(52,y+picture.height()+12,text=label,fill='#263747',font=(UI_FONT,9))
        while len(self.thumb_cache)>12:self.thumb_cache.popitem(last=False)

    def preview_resize(self,event=None):
        if self.pdf is None:return
        if self._preview_job:self.root.after_cancel(self._preview_job)
        self._preview_job=self.root.after(90,self.render)

    def fit_preview(self):
        self.fit_enabled=True;self.fit_mode='Весь лист';self.scale_choice.set('Весь лист');self.render()

    def choose_scale(self,event=None):
        value=self.scale_choice.get()
        self.fit_enabled=value in ('Весь лист','По ширине');self.fit_mode=value
        if not self.fit_enabled:
            try:self.zoom=max(.1,min(3,float(value.rstrip('%'))/100))
            except ValueError:return
        self.render()

    def render(self):
        if self._preview_job:self.root.after_cancel(self._preview_job)
        self._preview_job=None
        if self.pdf is None:return
        import fitz
        from PIL import Image,ImageTk
        page=self.pdf[self.page];width=self.pcanvas.winfo_width();height=self.pcanvas.winfo_height()
        if width<30 or height<30:
            self._preview_job=self.root.after(100,self.render);return
        if self.fit_enabled:
            self.zoom=max(.05,(width-24)/page.rect.width) if self.fit_mode=='По ширине' else fit_scale(width,height,page.rect.width,page.rect.height)
        # Bound render memory for very wide windows; manual zoom remains 10–300%.
        self.zoom=min(3,self.zoom)
        pix=page.get_pixmap(matrix=fitz.Matrix(self.zoom,self.zoom),alpha=False)
        self.tkimage=ImageTk.PhotoImage(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
        x=max(12,(width-pix.width)//2);y=max(12,(height-pix.height)//2)
        self.pcanvas.delete('all');self.pcanvas.create_image(x,y,anchor='nw',image=self.tkimage)
        self.pcanvas.configure(scrollregion=(0,0,max(width,pix.width+24),max(height,pix.height+24)))
        sheets=self.outputs['sheets'] if self.outputs else max(1,(len(self.pdf)+1)//2)
        self.page_label.set(f'{page_description(self.page)} · всего листов: {sheets} · {round(self.zoom*100)}%')
        self.queue_thumbnails()

    def go_page(self,index):
        if self.pdf is None:return
        index=max(0,min(len(self.pdf)-1,index))
        self.page=index if index in self.visible else min(self.visible,key=lambda v:abs(v-index))
        self.render();self.pcanvas.yview_moveto(0);self.pcanvas.xview_moveto(0)
        slot=self.visible.index(self.page);top=self.thumbs.canvasy(0);bottom=top+self.thumbs.winfo_height()
        if slot*156<top or (slot+1)*156>bottom:self.thumbs.yview_moveto(slot/max(1,len(self.visible)))
        self.queue_thumbnails()

    def turn(self,step):
        if self.pdf:
            n=self.visible.index(self.page);self.go_page(self.visible[max(0,min(len(self.visible)-1,n+step))])

    def scale(self,step):
        if self.pdf is None:return
        old_x=self.pcanvas.xview();old_y=self.pcanvas.yview()
        self.fit_enabled=False;self.zoom=max(.1,min(3,self.zoom+step));self.scale_choice.set(f'{round(self.zoom*100)}%');self.render()
        if old_x:self.pcanvas.xview_moveto(old_x[0])
        if old_y:self.pcanvas.yview_moveto(old_y[0])

    def preview_wheel(self,event):
        step=1 if getattr(event,'delta',0)>0 or getattr(event,'num',0)==4 else -1
        if event.state & 4:self.scale(.1*step)
        else:self.pcanvas.yview_scroll(-step*3,'units')
        return 'break'

    def toggle_preview(self):
        if str(self.editor) in self.workspace.panes():
            self._editor_width=self.workspace.sashpos(0);self.workspace.forget(self.editor);self.expand_button.configure(text='Вернуть поля')
        else:
            self.workspace.insert(0,self.editor,weight=1);self.root.update_idletasks();self.workspace.sashpos(0,getattr(self,'_editor_width',540));self.expand_button.configure(text='Развернуть')
        self.preview_resize()
