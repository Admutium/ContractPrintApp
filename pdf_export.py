"""A4 document layout; explicit physical front/back ordering."""
from pathlib import Path
from xml.sax.saxutils import escape
import os, tempfile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Flowable
import fitz
from contract_dates import date_line
from core import END_LABEL, SMP_LABEL, LIFE_LABEL, money, reduction, vat_amount, vat_summary

ROOT=Path(__file__).resolve().parent
for name,file in [('Body','DejaVuSans.ttf'),('Bold','DejaVuSans-Bold.ttf')]:
    if name not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont(name,str(ROOT/'assets/fonts'/file)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')
W,H=A4; M=40; CW=W-2*M; INK=colors.HexColor('#202830'); LINE=colors.HexColor('#b4bbc2'); GREY=colors.HexColor('#eef0f2')
ST={
 'body':ParagraphStyle('body',fontName='Body',fontSize=9,leading=12,textColor=INK),
 'small':ParagraphStyle('small',fontName='Body',fontSize=8,leading=10.5,textColor=INK),
 'label':ParagraphStyle('label',fontName='Bold',fontSize=8,leading=10.5,textColor=INK),
 'name':ParagraphStyle('name',fontName='Bold',fontSize=9.3,leading=12.3,textColor=INK),
 'title':ParagraphStyle('title',fontName='Bold',fontSize=16,leading=20,textColor=INK),
 'sub':ParagraphStyle('sub',fontName='Bold',fontSize=11,leading=15,textColor=INK),
}
def p(s='',style='body'): return Paragraph(escape(str(s or '')).replace('\n','<br/>'),ST[style])
def amount(s):
    try:return money(s)
    except ValueError:return str(s or '')

def table(rows,widths,commands=(),**kwargs):
    t=Table(rows,colWidths=widths,hAlign='LEFT',**kwargs)
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('GRID',(0,0),(-1,-1),.4,LINE)]+list(commands)))
    return t

class Checkbox(Flowable):
    def __init__(self,value): super().__init__(); self.value=value; self.width=14;self.height=14
    def draw(self):
        c=self.canv;c.setStrokeColor(INK);c.setLineWidth(.8);c.rect(1,1,11,11)
        if self.value=='Да':
            path=c.beginPath();path.moveTo(3,6);path.lineTo(6,3);path.lineTo(11,11);c.drawPath(path)
        elif self.value=='Нет': c.line(3,3,10,10);c.line(3,10,10,3)

def footer(c,back=False):
    def draw(canvas,doc):
        canvas.saveState();canvas.setFillColor(INK);canvas.setFont('Body',7)
        label=f'{c.supplier}  |  Контракт № {c.number}'
        limit=W-2*M-115
        if pdfmetrics.stringWidth(label,'Body',7)>limit:
            while label and pdfmetrics.stringWidth(label+'…','Body',7)>limit:label=label[:-1]
            label+='…'
        canvas.drawString(M,22,label)
        if back:canvas.drawRightString(W-M,22,'Оборот первого листа')
        canvas.restoreState()
    return draw

def supplier_title(value,width=40):
    size=min(16,16*(width-.5)/max(1,pdfmetrics.stringWidth(str(value),'Bold',16)))
    style=ParagraphStyle('supplier',parent=ST['title'],fontSize=size,leading=20,splitLongWords=False)
    return Paragraph(escape(str(value)),style)

def contract_heading(c,o):
    number='Контракт № '+c.number;date=date_line(o.concluded,o.conclusion_date)
    if pdfmetrics.stringWidth(number+' '+date,'Bold',11)<=CW-12:
        return [p(number+' '+date,'sub')]
    return [p(number,'sub'),Spacer(1,4),p(date,'sub')]

def first_header(c,o):
    return [table([[supplier_title(c.supplier),p(c.customer,'title')]],[52,CW-52], [('BACKGROUND',(0,0),(-1,-1),GREY)]),Spacer(1,10),
      *contract_heading(c,o),Spacer(1,5),p(c.subject),Spacer(1,8),
      table([[p('СРОК ПОСТАВКИ','label')],[p(o.delivery or '____________________________________________________________\n____________________________________________________________','sub')]],[CW],[('BACKGROUND',(0,0),(-1,-1),GREY),('LINEBELOW',(0,0),(-1,0),0,GREY)]),
      Spacer(1,10),spec_heading(c),Spacer(1,6)]

def spec_heading(c):
    style=ParagraphStyle('total',parent=ST['sub'],alignment=2,fontSize=10)
    label=('Максимальная цена: ' if c.unknown else 'Итого: ')+amount(c.total)+' руб.'
    t=Table([[p('Спецификация','sub'),p('')]],colWidths=[160,CW-160],hAlign='LEFT')
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    return t

def item_table(i):
    head=[p(s,'label') for s in ['№','Наименование','Количество /\nед. изм.','Цена, руб.','Сумма, руб.']]
    main=[p(i.no),p(i.name,'name'),p(i.qty),p(amount(i.price)),p(amount(i.total) or '—')]
    rate=i.vat.strip()
    vat_label=('НДС: не указан' if not rate else rate if rate.lower().startswith(('ндс','без ндс')) else 'НДС '+rate)
    details=[p(vat_label+' · Страна: '+(i.country.strip() or 'не указана'),'label'),Spacer(1,4)]
    if i.extra: details += [p(i.extra,'small'),Spacer(1,4)]
    if i.chars:
        details += [p('Характеристики','label'),Spacer(1,3)]
        for s in i.chars: details += [p(s,'small'),Spacer(1,2)]
    included_vat=vat_amount(i.total,i.vat)
    vat_line=('НДС '+i.vat+': '+money(str(included_vat))+' руб.' if included_vat is not None else
              'НДС: '+(i.vat or 'не указан') + (' (нет суммы строки)' if not i.total else ''))
    details += [Spacer(1,3),p(' · '.join(x for x in [('Сумма НДС: '+money(str(included_vat))+' руб.') if included_vat is not None else '',i.kind] if x),'small')]
    if i.code: details += [p('Код позиции: '+i.code,'small')]
    t=table([head,main,[details,'','','','']],[28,CW-28-76*3,76,76,76], [('BACKGROUND',(0,0),(-1,0),GREY),('SPAN',(0,2),(-1,2))],repeatRows=1,splitByRow=1,splitInRow=1)
    # Keep a normal product together; let unusually long descriptions flow.
    if t.wrap(CW,H)[1]<H-2*M-20:
        return KeepTogether([t,Spacer(1,9)])
    # A single-column continuation table avoids ReportLab's merged-cell width
    # regression when an unusually large product is split inside a row.
    inner=table([head,main],[28,CW-12-28-76*3,76,76,76],
                [('BACKGROUND',(0,0),(-1,0),GREY)])
    continuation=[[p(f'Позиция {i.no} · {i.name}','name')],[inner]]
    continuation.extend([[flow] for flow in details if not isinstance(flow,Spacer)])
    return table(continuation,[CW],[('BACKGROUND',(0,0),(-1,0),GREY)],
                 repeatRows=1,splitByRow=1,splitInRow=1)

def reverse(c,o):
    rows=[]
    def add(label,value):rows.append([p(label,'label'),p(value or '________________________________')])
    add('Номер контракта',c.number);add('Номер извещения',c.notice);add('Идентификационный код закупки (ИКЗ)',c.ikz)
    add('Электронная торговая площадка',o.platform)
    if c.procurement_method:add('Способ закупки',c.procurement_method)
    add('НМЦК, руб.',amount(o.nmck))
    add('Максимальное значение цены контракта, руб.' if c.unknown else 'Цена контракта, руб.',amount(c.total))
    basis=' (введено вручную)' if o.manual_reduction else ' (по НМЦК и цене контракта)' if c.unknown and o.reduction_basis=='nmck' else ''
    if o.price_increased and not o.manual_reduction:
        add('Цена до увеличения, руб.',amount(o.original_price));basis=' (до увеличения)'
    add('Снижение, %'+basis,reduction(c,o))
    if o.reduction_basis=='units' or (o.reduction_basis=='auto' and c.unknown):
        add('Начальная сумма цен единиц, руб.',amount(o.initial_units));add('Итоговая сумма цен единиц, руб.',amount(o.final_units))
    rows.extend([[p(SMP_LABEL,'label'),Checkbox(o.smp)],[p(LIFE_LABEL,'label'),Checkbox(o.life)]])
    if o.quantity_note:add('Сверка объёма с извещением ЕИС',o.quantity_note)
    add('Заказчик',c.customer_full or c.customer)
    add('Контактное лицо',c.contact);add('Телефон / электронная почта','\n'.join(x for x in [c.phone,c.email] if x))
    add('Место поставки',c.address)
    if o.request_delivery:add('Срок поставки по заявке',o.request_delivery)
    add(END_LABEL,c.end)
    add('Дата создания экземпляра',o.created_date or __import__('datetime').date.today().strftime('%d.%m.%Y'))
    if o.note:add('Примечание',o.note)
    t=table(rows,[205,CW-205], [('BACKGROUND',(0,0),(0,-1),GREY)])
    if t.wrap(CW,H)[1]>H-2*M-45:
        raise ValueError('Информация оборота не помещается на один лист. Сократите примечание или отредактируйте слишком длинные поля.')
    return [p('Карточка контракта','title'),Spacer(1,12),t]

def generate(c,o,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    paths={k:directory/(k+'.pdf') for k in ('fronts','back','duplex')}
    reduction(c,o) # Validate before writing.
    story=first_header(c,o)
    if c.unknown:story += [p('Количество определяется заявками. Ниже указаны цены единиц; итоговые суммы строк не установлены.','small'),Spacer(1,6)]
    for i in c.items:story.append(item_table(i))
    def doc(path):return SimpleDocTemplate(str(path),pagesize=A4,leftMargin=M,rightMargin=M,topMargin=M,bottomMargin=M,title='Карточка контракта '+c.number,author='ContractPrintApp',allowSplitting=1)
    doc(paths['fronts']).build(story,onFirstPage=footer(c),onLaterPages=footer(c))
    doc(paths['back']).build(reverse(c,o),onFirstPage=footer(c,True),onLaterPages=footer(c,True))
    # Post-layout finishing cannot push a total or rule onto another sheet.
    base=fitz.open(paths['fronts'])
    sheets=len(base)
    regular=str(ROOT/'assets/fonts/CPLabels.ttf');bold=str(ROOT/'assets/fonts/CPLabels-Bold.ttf')
    font=fitz.Font(fontfile=bold)
    label=('Максимальная цена: ' if c.unknown else 'Итого: ')+amount(c.total)+' руб.'
    def right_text(page,value,y,left=M+6,right=W-M+6,size=10):
        page.insert_font(fontname='CPBold',fontfile=bold)
        size=min(size,(right-left)/max(1,font.text_length(value,fontsize=1)))
        page.insert_text((right-font.text_length(value,fontsize=size),y),value,fontname='CPBold',fontsize=size,color=(0,0,0))
    for i,page in enumerate(base):
        page.insert_font(fontname='CPBody',fontfile=regular)
        value=f'Лист {i+1} из {sheets}'
        f=fitz.Font(fontfile=regular)
        page.insert_text((W-M-f.text_length(value,fontsize=7),H-22),value,fontname='CPBody',fontsize=7)
    if sheets>1:
        heading=base[0].search_for('Спецификация')[0]
        right_text(base[0],label,heading.y0+11,left=M+166)
    last=base[-1]
    # Table borders are the true bottom, including padding below the final text.
    borders=[d['rect'].y1 for d in last.get_drawings() if d['rect'].y1<H-M+1]
    end=max(borders,default=M)
    rule_y=min(end+3,H-M)
    last.draw_line((M+6,rule_y),(W-M+6,rule_y),color=(0,0,0),width=1.8)
    total_y=rule_y+13
    # One-sheet cards use the space above the footer for their sole total.
    show_end=total_y<=(H-29 if sheets==1 else H-M-3)
    if sheets==1 and not show_end:
        raise ValueError('Не хватает места для итога на единственном листе. Сократите длинное поле заголовка.')
    if show_end:right_text(last,label,total_y)
    finished=directory/'fronts-finished.pdf';base.subset_fonts();base.save(finished,garbage=4,deflate=True);base.close();os.replace(finished,paths['fronts'])
    with fitz.open(paths['fronts']) as fronts,fitz.open(paths['back']) as back,fitz.open() as writer:
        if len(back)!=1:raise ValueError('Оборот не поместился на один лист.')
        for n in range(len(fronts)):
            writer.insert_pdf(fronts,from_page=n,to_page=n)
            if n==0:writer.insert_pdf(back)
            elif n<len(fronts)-1:writer.new_page(width=W,height=H)
        pages=len(writer);writer.save(paths['duplex'],garbage=4,deflate=True)
    return {**paths,'sheets':sheets,'pages':pages,'end_total':show_end}

def atomic_copy(source,destination):
    destination=Path(destination)
    if not destination.parent.is_dir(): raise ValueError('Папка сохранения недоступна. Выберите существующую папку.')
    fd,tmp=tempfile.mkstemp(prefix='.contractprintapp-',suffix='.tmp',dir=destination.parent)
    try:
        data=Path(source).read_bytes()
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        try:
            os.replace(tmp,destination)
        except PermissionError as e:
            raise PermissionError('Не удалось заменить PDF. Закройте этот файл в программе просмотра на всех компьютерах, отключите панель предпросмотра Проводника (Alt+P) и повторите сохранение. Также проверьте право изменения файла в папке сохранения.') from e
        if destination.read_bytes()!=data:
            raise OSError('Проверка сохранённого PDF не пройдена: содержимое файла отличается. Проверьте сетевую папку и повторите сохранение.')
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
