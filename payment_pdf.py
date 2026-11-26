"""One-page internal handoff to accounting for contract execution security."""
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import money
from payment_data import amount_words
from pdf_export import A4, ST


def generate_payment(data, path, draft=False):
    path = Path(path)
    title = 'Платёжное поручение на обеспечение исполнения контракта'
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=36, rightMargin=36,
                            topMargin=35, bottomMargin=35,
                            title=title)
    body = ParagraphStyle('AccountingBody', parent=ST['body'], fontSize=10, leading=14)
    label = ParagraphStyle('AccountingLabel', parent=ST['label'], fontSize=9, leading=12)

    def paragraph(value, style=body):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), style)

    def section(title, rows):
        cells = [[paragraph(name, label), paragraph(value)] for name, value in rows if value or name == 'Назначение платежа']
        if not cells:
            return []
        table = Table(cells, colWidths=[158, doc.width-170], hAlign='LEFT')
        table.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,-1),0.4,colors.HexColor('#c3cad1')),
            ('TOPPADDING',(0,0),(-1,-1),6),
            ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ]))
        return [paragraph(title, ST['sub']), Spacer(1,4), table, Spacer(1,14)]

    amount = Decimal(data.get('amount','0') or '0')
    if amount < 0:
        raise ValueError('Сумма не может быть отрицательной.')
    content = [paragraph(title, ST['title']), Spacer(1,10)]
    if draft:
        content.extend([paragraph('ЧЕРНОВИК', ST['sub']), Spacer(1,8)])
    rate = data.get('percent','').replace('.',',')
    if rate:
        rate += ' %'
        if data.get('rate_basis'):
            rate += ' от ' + data['rate_basis']
    content += section('Платёж', [
        ('Контракт',data.get('contract_number')),
        ('Плательщик',data.get('payer_name')),
        ('Размер обеспечения',money(str(amount))+' руб.' if amount else ''),
        ('Процент обеспечения',rate),
        ('Сумма прописью',amount_words(amount) if amount else ''),
        ('Назначение платежа',data.get('purpose')),
    ])
    content += section('Получатель · ЛПУ', [

            ('Полное наименование',data.get('recipient_name')),
            ('ИНН',data.get('recipient_inn')), ('КПП',data.get('recipient_kpp')),
            ('Тип счёта',data.get('account_type')), ('Лицевой счёт',data.get('personal')),
            ('Банковский / казначейский счёт',data.get('recipient_account')),
            ('Банк / ТОФК',data.get('recipient_bank')), ('БИК',data.get('recipient_bik')),
            ('Корреспондентский счёт / ЕКС',data.get('recipient_bank_account')),
            ('Контрагент для п/п',data.get('counterparty')),
            ('КБК',data.get('kbk')), ('ОКТМО',data.get('oktmo')), ('УИН',data.get('uin')),
            ('Статус (101)',data.get('status')), ('Основание (106)',data.get('tax_basis')),
            ('Период (107)',data.get('tax_period')), ('Номер документа (108)',data.get('tax_number')),
            ('Дата документа (109)',data.get('tax_date')), ('Тип платежа (110)',data.get('tax_type')),
    ])
    if any(len(str(value)) > 1800 for value in data.values()):
        raise ValueError('Сократите длинное поле, чтобы документ поместился на одной странице.')
    doc.build([KeepInFrame(doc.width-12, doc.height-12, content, mode='shrink')])
    return path
