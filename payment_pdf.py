"""One-page A4 payment-order template, field layout 0401060."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from pdf_export import ST  # registers the bundled Cyrillic fonts
from payment_data import amount_words
from decimal import Decimal


def generate_payment(data,path,draft=False):
    path=Path(path);c=Canvas(str(path),pagesize=A4)
    c.setTitle('Платёжное поручение — обеспечение исполнения контракта')
    width,height=A4;left=32;right=width-32
    def line(x1,y1,x2,y2):c.line(x1,height-y1,x2,height-y2)
    def text(x,y,value,size=9,bold=False):
        c.setFont('Bold' if bold else 'Body',size);c.drawString(x,height-y,str(value or ''))
    def box(x,y,w,h,label,value='',bold=False):
        c.setLineWidth(.55);c.rect(x,height-y-h,w,h)
        text(x+5,y+10,label,6.5)
        content=str(value or '—')
        for size in (10,9,8,7,6.5):
            style=ParagraphStyle('payment',fontName='Bold' if bold else 'Body',fontSize=size,leading=size+2)
            p=Paragraph(escape(content).replace('\n','<br/>'),style)
            _,ph=p.wrap(w-10,h-18)
            if ph<=h-18:break
        else:raise ValueError('Поле «'+label+'» слишком длинное для одной страницы. Сократите текст вручную.')
        p.drawOn(c,x+5,height-y-16-ph)
    text(left,32,'Поступ. в банк плат.',7);text(210,32,'Списано со сч. плат.',7)
    line(left,44,180,44);line(210,44,357,44);text(right-50,32,'0401060',9)
    text(left,79,'ПЛАТЁЖНОЕ ПОРУЧЕНИЕ № '+data.get('number',''),13,True)
    text(left,101,'Дата: '+data.get('date',''),10)
    text(310,101,'Вид платежа: '+data.get('payment_type',''),9)
    amount=Decimal(data.get('amount','0') or '0')
    if amount<0:raise ValueError('Сумма не может быть отрицательной.')
    box(left,114,right-left,55,'Сумма прописью',amount_words(amount))
    def party(prefix,y,title):
        box(left,y,190,28,'ИНН',data.get(prefix+'_inn',''))
        box(left+190,y,165,28,'КПП',data.get(prefix+'_kpp',''))
        if prefix=='payer':box(left+355,y,right-left-355,28,'Сумма',f'{amount:.2f}'.replace('.','-'),True)
        else:box(left+355,y,right-left-355,28,'Очередность платежа',data.get('priority','5'))
        box(left,y+28,330,70,title+' · полное наименование',data.get(prefix+'_name',''),True)
        box(left+330,y+28,right-left-330,70,'Сч. №',data.get(prefix+'_account',''))
        box(left,y+98,330,67,'Банк '+('плательщика' if prefix=='payer' else 'получателя'),data.get(prefix+'_bank',''))
        box(left+330,y+98,right-left-330,28,'БИК',data.get(prefix+'_bik',''))
        box(left+330,y+126,right-left-330,39,'Сч. № банка',data.get(prefix+'_bank_account',''))
    party('payer',169,'Плательщик');party('recipient',334,'Получатель')
    labels=[('Вид оп.',data.get('operation','01')),('Срок плат.',data.get('payment_due','')),('Наз. пл.',data.get('payment_code','')),('Код (УИН)',data.get('uin','')),('Рез. поле',data.get('reserve',''))]
    span=(right-left)/len(labels)
    for i,(label,value) in enumerate(labels):box(left+i*span,499,span,30,label,value)
    tax=[('Статус (101)',data.get('status','')),('КБК (104)',data.get('kbk','')),('ОКТМО (105)',data.get('oktmo','')),('Основание (106)',data.get('tax_basis','')),('Период (107)',data.get('tax_period',''))]
    spans=[74,160,103,97,right-left-434];x=left
    for (label,value),w in zip(tax,spans):box(x,529,w,32,label,value);x+=w
    box(left,561,200,30,'Номер документа (108)',data.get('tax_number',''))
    box(left+200,561,200,30,'Дата документа (109)',data.get('tax_date',''))
    box(left+400,561,right-left-400,30,'Тип платежа (110)',data.get('tax_type',''))
    box(left,591,right-left,106,'Назначение платежа',data.get('purpose',''))
    text(left+20,728,'М. П.',9);text(left+180,719,'Подписи',8);text(left+375,719,'Отметки банка',8)
    line(left+120,742,left+320,742);line(left+120,768,left+320,768)
    if draft:
        text(left,801,'ЧЕРНОВИК · Есть незаполненные или некорректные поля',8,True)
    c.showPage();c.save();return path
