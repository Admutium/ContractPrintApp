"""ContractPrintApp: safe local HTML extraction and decimal business rules."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re

FIRMS = {}
ETPS = ('Ручной ввод', 'Росэлторг', 'Фабрикант', 'СбербанкАСТ', 'РТС-Тэндер')
DEFAULT_FOLDER = str(Path.home() / 'Documents')
END_LABEL = 'Дата окончания исполнения контракта (срок исполнения контракта)'
SMP_LABEL = 'Закупка только для СМП и СОНКО · ч. 3 ст. 30 Закона № 44-ФЗ'
LIFE_LABEL = 'Товары для нормального жизнеобеспечения граждан · ч. 9 ст. 37 Закона № 44-ФЗ'

@dataclass
class Item:
    no: str=''; name: str=''; extra: str=''; kind: str=''; code: str=''
    qty: str=''; price: str=''; vat: str=''; country: str=''; total: str=''
    chars: list[str]=field(default_factory=list)

@dataclass
class Contract:
    procurement_method: str=''
    ikz: str=''; customer_inn: str=''; number: str=''; notice: str=''; supplier: str=''; supplier_full: str=''; inn: str=''
    customer: str=''; customer_full: str=''; subject: str=''; contact: str=''
    phone: str=''; email: str=''; address: str=''; end: str=''; total: str=''
    unknown: bool=False
    items: list[Item]=field(default_factory=list)
    warnings: list[str]=field(default_factory=list)

@dataclass
class Options:
    platform: str=''; delivery: str=''; nmck: str=''; initial_units: str=''; final_units: str=''
    request_delivery: str=''
    concluded: bool=False
    conclusion_date: str=''
    quantity_note: str=''
    price_increased: bool=False
    original_price: str=''
    reduction_basis: str='auto'
    manual_reduction: bool=False; reduction: str=''; smp: str=''; life: str=''; note: str=''; created_date: str=''

def clean(s): return re.sub(r'\s+', ' ', str(s or '')).strip()
def text(e): return clean(' '.join(e.itertext()))

def decimal(value, label='Число', allow_blank=True):
    s=clean(value).replace(' ', '').replace(',', '.')
    if not s and allow_blank: return None
    if not re.fullmatch(r'\d+(?:\.\d+)?', s): raise ValueError(f'{label}: введите неотрицательное число.')
    try: d=Decimal(s)
    except InvalidOperation: raise ValueError(f'{label}: неверное число.')
    if not d.is_finite() or d > Decimal('1e18'): raise ValueError(f'{label}: слишком большое число.')
    return d

def money(value):
    d=decimal(value)
    if d is None: return ''
    places=max(2, -d.as_tuple().exponent)
    return f'{d:,.{places}f}'.replace(',', ' ').replace('.', ',')

def vat_amount(total, rate):
    """VAT included in gross row amount. None means an exempt, blank or unknown rate."""
    raw=clean(rate).lower().replace(' ', '').replace(',', '.')
    if not raw or 'безндс' in raw or 'необлага' in raw or raw in ('-', '—'):
        return None
    match=re.fullmatch(r'(?:ндс)?(\d+(?:\.\d+)?)%',raw)
    if not match:return None
    r=Decimal(match.group(1));amount=decimal(total,'Сумма позиции')
    if r<0 or r>100 or amount is None:return None
    return (amount*r/(Decimal('100')+r)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)

def vat_summary(items):
    amounts=[vat_amount(i.total,i.vat) for i in items]
    return sum((x for x in amounts if x is not None),Decimal('0.00')),sum(x is not None for x in amounts)

def reduction(c, o):
    if o.manual_reduction:
        d=decimal(o.reduction, 'Снижение, %')
        if d is not None and d>100: raise ValueError('Снижение не может быть больше 100%.')
    else:
        units=o.reduction_basis=='units' or (o.reduction_basis=='auto' and c.unknown)
        if o.price_increased and units:
            raise ValueError('При увеличении и расчёте по ценам единиц укажите снижение вручную.')
        a=decimal(o.initial_units if units else o.nmck, 'Начальная сумма цен единиц' if units else 'НМЦК')
        b=decimal(o.final_units if units else o.original_price if o.price_increased else c.total, 'Итоговая сумма цен единиц' if units else 'Цена контракта')
        if a is None or b is None: return ''
        if a<=0: raise ValueError('База расчёта снижения должна быть больше нуля.')
        if b>a: raise ValueError('Итоговая цена выше начальной. При увеличении позиций включите ручной ввод снижения.')
        d=(a-b)*100/a
    return '' if d is None else str(d.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)).replace('.', ',')

def customer_short(s):
    s=clean(s)
    q=re.search(r'[«"]([^»"]+)[»"]',s)
    return clean(q.group(1)) if q else re.sub(r'^(?:ГБУЗ?|ГАУЗ?|ГКУЗ?)\s+(?:РО\s+)?', '', s, flags=re.I)

def safe_part(s): return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '',clean(s)).strip(' .')
def suggested_name(c):
    digits=re.sub(r'\D','',c.notice)
    return '_'.join(safe_part(s) for s in (c.supplier or 'Фирма',customer_short(c.customer) or 'Заказчик',digits[-5:] or 'Без_извещения'))+'.pdf'

def filename(s):
    s=s.strip()
    if not s.lower().endswith('.pdf'): s+='.pdf'
    if not s[:-4] or re.search(r'[<>:"/\\|?*\x00-\x1f]',s) or len(s)>180 or s.rstrip(' .')!=s or s[:-4].endswith((' ','.')):
        raise ValueError('Недопустимое имя PDF. Уберите / \\ : * ? " < > | и конечные точки или пробелы.')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',s,re.I): raise ValueError('Это имя зарезервировано Windows.')
    return s

def normalized_label(value):
    return clean(value).lower().replace('ё','е').strip(' :№')

def table_fields(node):
    out={}
    if node is not None:
        for row in node.xpath('.//tr[not(.//tr)]'):
            cells=row.xpath('./td|./th')
            if len(cells)>=2:
                # Later rows can describe a representative, not the organization.
                out.setdefault(normalized_label(text(cells[0])),clean(' '.join(text(c) for c in cells[1:])))
    return out

def extract_inn(fields):
    # Read only the identified party's fields. Never take the customer's INN.
    ranked=sorted(fields.items(),key=lambda kv:0 if kv[0] in ('инн юридического лица','инн организации','инн поставщика') else 1 if kv[0] in ('инн','инн / кпп','инн/кпп','идентификационный номер налогоплательщика') else 2)
    for key,value in ranked:
        if any(w in key for w in ('представител','руководител','подписант')):continue
        if re.match(r'^(?:инн(?:\b|/)|идентификационный номер налогоплательщика)',key):
            # Split before KPP, rather than concatenating INN and KPP digits.
            part=re.split(r'[/;]|кпп',value,flags=re.I)[0]
            compact=re.sub(r'\s+','',part)
            if re.fullmatch(r'\d{10}|\d{12}',compact):return compact
            match=re.search(r'(?<!\d)(\d{12}|\d{10})(?!\d)',part)
            if match:return match.group(1)
    return ''

def specification_issues(c):
    problems=[]
    for item in c.items:
        prefix=f'Позиция {item.no}: '
        if not item.name:problems.append(prefix+'нет наименования')
        if not item.qty:problems.append(prefix+'нет количества / единицы измерения')
        elif not re.search(r'[A-Za-zА-Яа-яЁё]',item.qty):problems.append(prefix+'проверьте единицу измерения')
        try:
            price=decimal(item.price,'Цена');total=decimal(item.total,'Сумма')
            if price is None:problems.append(prefix+'нет цены')
            if not c.unknown:
                if total is None:problems.append(prefix+'нет суммы')
                qty=re.match(r'^([0-9]+(?:[ .,\u00a0][0-9]+)*)',item.qty)
                if qty and price is not None and total is not None:
                    amount=decimal(qty.group(1))*price
                    if abs(amount.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)-total)>Decimal('.01'):
                        problems.append(prefix+'количество × цена не совпадает с суммой')
        except ValueError:problems.append(prefix+'неверный формат цены или суммы')
    return problems

def parse(path, firms=None):
    from lxml import html
    firms=FIRMS if firms is None else firms
    raw=Path(path).read_bytes()
    if len(raw)>20*1024*1024: raise ValueError('HTML больше 20 МБ. Выберите печатную форму одного контракта.')
    # lxml never executes scripts and network access is disabled.
    try:decoded=raw.decode('utf-8-sig')
    except UnicodeDecodeError:decoded=raw
    root=html.fromstring(decoded,parser=html.HTMLParser(no_network=True))
    def block(prefix):
        for e in root.xpath('//p|//h2|//h3|//h4|//div[not(div) and not(table)]'):
            if text(e).startswith(prefix): return e.getparent()
        return None
    def fields(node):
        # Preserve canonical names for existing field mappings; accept case and ё/е.
        class Fields(dict):
            def get(self,key,default=''):
                return super().get(normalized_label(key),default)
        return Fields(table_fields(node))
    allf=fields(root); customer=fields(block('2.1.')); supplier=fields(block('2.2.'))
    price=fields(block('5.2.')); spec=block('3.1.')
    if spec is None: raise ValueError('Раздел 3.1 «Объект закупки» не найден. Нужна печатная форма электронного контракта HTML.')
    c=Contract(procurement_method=allf.get('Способ определения поставщика (подрядчика, исполнителя)',''),number=allf.get('Номер контракта',''), notice=allf.get('Номер извещения об осуществлении закупки (приглашения)',''),
      ikz=clean(allf.get('Идентификационный код закупки',allf.get('Идентификационный код закупки (ИКЗ)'))).replace(' ',''), inn=extract_inn(supplier), customer_inn=extract_inn(customer), supplier_full=supplier.get('Полное наименование',supplier.get('ФИО физического лица','')),
      customer=customer_short(customer.get('Сокращенное наименование') or customer.get('Полное наименование','')),
      customer_full=customer.get('Полное наименование',''), subject=allf.get('Предмет контракта',''),
      contact=customer.get('Ответственное должностное лицо заказчика',''),phone=customer.get('Номер контактного телефона',''),email=customer.get('Адрес электронной почты',''),
      end=allf.get(END_LABEL,''), total=price.get('Цена контракта',price.get('Максимальное значение цены контракта','')),
      unknown=bool(re.search(r'Невозможно определить количество[^-–—:]{0,120}[-–—:]\s*Да\b', text(spec),re.I)))
    if c.inn in firms:c.supplier=firms[c.inn][0]
    else:
        c.warnings.append('Поставщик не найден в справочнике. ИНН: '+(c.inn or 'не распознан')+'. Выберите фирму или исправьте справочник.')
    address=block('4.3.')
    if address is not None:
        # Preserve every delivery row, not only the first destination.
        rows=[]
        for row in address.xpath('.//tbody/tr'):
            cells=row.xpath('./td')
            if cells: rows.append(' · '.join(text(e) for e in cells if text(e)))
        c.address='\n'.join(rows)
    current=None
    for row in spec.xpath('.//table//tr'):
        cells=row.xpath('./td')
        if not cells: continue
        vals=[text(e) for e in cells]
        if len(cells)==9 and re.fullmatch(r'\d+',vals[0]):
            # Column-number guide row is 1..9, not an item.
            if vals==list(map(str,range(1,10))): continue
            direct=clean(' '.join(cells[1].xpath('./text()')))
            extra='\n'.join(text(e) for e in cells[1] if text(e))
            current=Item(vals[0],direct or vals[1],extra if direct else '',*vals[2:])
            c.items.append(current)
        elif len(cells)==1 and current:
            if vals[0]=='Характеристики объекта закупки': continue
            chunks=[text(e) for e in cells[0].xpath('./div') if text(e)]
            if not chunks: chunks=[vals[0]] if vals[0] else []
            current.chars.extend(chunks)
        elif len(cells)==2 and vals[0].startswith('Итого'): pass
        elif vals==list(map(str,range(1,len(vals)+1))): pass
        elif cells and re.fullmatch(r'\d+', vals[0] or ''):
            raise ValueError('Неизвестная структура строки спецификации. Формирование остановлено, чтобы не потерять позиции.')
    if not c.number or not c.items: raise ValueError('Не удалось прочитать номер контракта или позиции спецификации.')
    if len({i.no for i in c.items})!=len(c.items): raise ValueError('В спецификации повторяются номера позиций. Проверьте исходный HTML.')
    for key,label in [('notice','Номер извещения'),('address','Место поставки'),('end',END_LABEL),('total','Цена контракта')]:
        if not getattr(c,key): c.warnings.append(label+': не найдено, заполните вручную.')
    if not c.unknown:
        totals=[decimal(i.total) for i in c.items]
        if all(v is not None for v in totals) and decimal(c.total) is not None and abs(sum(totals)-decimal(c.total))>Decimal('0.01'):
            c.warnings.append('Сумма строк спецификации не совпадает с ценой контракта. Проверьте исходный файл.')
    return c
