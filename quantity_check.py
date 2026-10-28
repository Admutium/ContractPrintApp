"""Conservative, read-only quantity comparison with an EIS notice."""
from dataclasses import dataclass,field
from decimal import Decimal,ROUND_HALF_UP,localcontext
import re
from core import clean,text,normalized_label,decimal

CODE=re.compile(r'(?<!\d)\d{2}\.\d{2}\.\d{2}\.\d{3}(?:-\d{8,9})?(?!\d)')
UNITS={'796':'шт','шт':'шт','штука':'шт','штук':'шт','штуки':'шт',
 '778':'упак','упак':'упак','упаковка':'упак','упаковок':'упак',
 '166':'кг','кг':'кг','килограмм':'кг','163':'г','г':'г','грамм':'г',
 '112':'л','л':'л','литр':'л','113':'мл','мл':'мл','миллилитр':'мл',
 '006':'м','м':'м','метр':'м','839':'компл','компл':'компл','комплект':'компл',
 '715':'пар','пар':'пар','пара':'пар','парa':'пар'}

def unit_key(value):
    s=normalized_label(value).replace('.','').strip()
    s=re.sub(r'\b(?:код\s+по\s+)?океи\b\s*:?', '', s).strip()
    if s in UNITS:return UNITS[s]
    tokens=[t for t in re.split(r'[\s()\[\],/]+',s) if t]
    known={UNITS[t] for t in tokens if t in UNITS}
    # Unknown words/numbers may be a multiplier: never equate 1000 pieces to pieces.
    if tokens and all(t in UNITS for t in tokens) and len(known)==1:return known.pop()
    return s

def quantity(value):
    s=clean(value)
    m=re.fullmatch(r'(\d+(?:[.,]\d+)?|\d{1,3}(?: \d{3})+(?:[.,]\d+)?)\s*(.*?)',s)
    if not m:raise ValueError('Количество не распознано')
    # The second branch needs priority for grouped numbers.
    m=re.fullmatch(r'(\d{1,3}(?: \d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(.*?)',s)
    return decimal(m[1],allow_blank=False),unit_key(m[2])

def codes(value):return set(CODE.findall(value))
def name_key(value):
    s=CODE.sub('',normalized_label(value))
    return clean(re.sub(r'[^\w]+',' ',s)).strip()

def char_map(values):
    out={}
    for s in values:
        if ':' in s:
            a,b=s.split(':',1);out[name_key(a)]=normalized_label(b).rstrip(';')
    return out

@dataclass
class NoticeItem:
    no:str='';name:str='';code:str='';qty:str='';unit:str='';chars:list=field(default_factory=list)

@dataclass
class Difference:
    no:str='';name:str='';before:str='';after:str='';delta:str='';status:str=''

@dataclass
class Comparison:
    status:str='Не удалось сравнить'
    reason:str='Сначала загрузите извещение ЕИС.'
    rows:list=field(default_factory=list)
    delta:object=None
    percent:object=None
    baseline:object=None
    changed:int=0
    number:str=''
    revision:str=''

    def back_note(self):
        if self.status!='Есть изменения':return ''
        line=f'Изменение объёма относительно извещения ЕИС: {self.changed} поз.'
        if self.delta is not None and self.percent is not None:
            def signed(v):return ('+' if v>0 else '−' if v<0 else '')+f'{abs(v):,.2f}'.replace(',',' ').replace('.',',')
            line+=f'\nСтоимость изменения объёма: {signed(self.delta)} руб. ({signed(self.percent)}%).'
            line+='\nРасчёт по ценам единиц загруженного контракта.'
        else:line+='\nПроцент стоимости не определён: '+self.reason
        return line

def _header(value):
    s=normalized_label(value)
    if s.startswith(('наименование объекта','наименование товара','наименование продукции')):return 'name'
    if s.startswith(('количество','объем (количество)','объем закупки')) or s=='объем':return 'qty'
    if 'единиц' in s and 'измерен' in s:return 'unit'
    if ('код' in s and any(x in s for x in ('позици','окпд','ктру','товар','продукц'))) or s in ('окпд2','ктру'):return 'code'
    if s in ('№ п/п','№','n п/п','п/п','номер позиции'):return 'no'
    return ''

def _grid(table):
    pending={}
    rows=table.xpath('./tr|./thead/tr|./tbody/tr|./tfoot/tr')
    # Real EIS exports also contain cells directly inside thead (no tr).
    heads=table.xpath('./thead[td or th]')
    rows=heads+rows
    for row in rows:
        cells={};next_pending={}
        for col,(cell,left) in pending.items():
            cells[col]=cell
            if left>1:next_pending[col]=(cell,left-1)
        col=0
        for cell in row.xpath('./td|./th'):
            while col in cells:col+=1
            span=min(40,max(1,int(cell.get('colspan','1'))));down=min(10000,max(1,int(cell.get('rowspan','1'))))
            for c in range(col,col+span):
                cells[c]=cell
                if down>1:next_pending[c]=(cell,down-1)
            col+=span
        pending=next_pending
        yield [cells.get(i) for i in range(max(cells,default=-1)+1)]

def parse_items(root):
    """Header-based EIS object tables; reject partial/ambiguous quantity structures."""
    items=[];issues=[];tables_found=0
    for table in root.xpath('//table'):
        mapping={};seen=set();current=None
        try:rows=list(_grid(table))
        except (ValueError,TypeError):continue
        if len(rows)>10000:issues.append('Слишком большая таблица объекта закупки.');continue
        for cells in rows:
            values=[text(c) if c is not None else '' for c in cells]
            header={_header(v):i for i,v in enumerate(values) if _header(v)}
            # EIS prints the code as a second "Наименование ..." column in
            # some forms. Prefer the actual product heading, not a later code
            # heading or the encompassing description of the whole section.
            names=[i for i,v in enumerate(values) if _header(v)=='name' and not CODE.search(v)]
            if names:header['name']=names[0]
            if 'name' in header and 'qty' in header:
                if not mapping:tables_found+=1
                mapping=header;continue
            if not mapping:continue
            if not any(values):continue
            nonempty=[v for v in values if v]
            if nonempty and all(re.fullmatch(r'\d{1,2}',v) for v in nonempty) and len(set(nonempty))>2:continue
            if nonempty and normalized_label(nonempty[0]).startswith(('итого','всего')):continue
            if max(mapping.values())>=len(cells):
                if current and any('характеристик' in normalized_label(v) for v in values):continue
                if current and len(nonempty)>=2 and not any(CODE.search(v) for v in nonempty):
                    current.chars.append(nonempty[0]+': '+' '.join(nonempty[1:]));continue
                if nonempty:issues.append('Есть строки объекта закупки, которые не удалось разобрать целиком.')
                continue
            namecell=cells[mapping['name']];qtycell=cells[mapping['qty']]
            if namecell is None or qtycell is None:issues.append('Пустые ячейки в структуре таблицы.');continue
            # Spanning characteristic/footer rows do not constitute a product.
            if namecell is qtycell:
                if current:
                    blocks=namecell.xpath('./div|./p')
                    values=[text(block) for block in blocks] if blocks else [text(namecell)]
                    current.chars.extend(value for value in values if ':' in value)
                continue
            key=(namecell,qtycell)
            if key in seen:continue
            seen.add(key)
            # Registration certificates and trade marks are nested blocks in
            # the contract, not part of the EIS product name.
            name=clean(' '.join(namecell.xpath('./text()'))) or values[mapping['name']]
            q=values[mapping['qty']]
            if not name and not q:continue
            if qtycell.xpath('.//table'):
                issues.append('Количество разбито по заказчикам или вложенным таблицам.');continue
            try:
                amount,embedded=quantity(q)
                unit=values[mapping['unit']] if 'unit' in mapping else embedded
                if not name or not unit:raise ValueError()
                if embedded and unit_key(unit)!=embedded:raise ValueError()
            except ValueError:
                issues.append('Не распознано количество или единица: '+name[:90]);continue
            code=values[mapping['code']] if 'code' in mapping else ' '.join(CODE.findall(name))
            current=NoticeItem(values[mapping['no']] if 'no' in mapping else str(len(items)+1),name,code,str(amount),unit)
            items.append(current)
    if not tables_found:issues.append('Таблица количеств в извещении не распознана.')
    if not items and not issues:issues.append('В извещении нет определённых количеств.')
    return items,list(dict.fromkeys(issues))

def _compatible(a,b):
    ac,bc=codes(a.code),codes(b.code)
    ak={v for v in ac if '-' in v};bk={v for v in bc if '-' in v}
    if ak and bk and not ak&bk:return False
    if ac and bc and not {v.split('-')[0] for v in ac}&{v.split('-')[0] for v in bc}:return False
    # A full KTRU identifier can identify renamed products, but an OKPD2
    # category alone cannot. Ambiguous duplicates are rejected by compare().
    if name_key(a.name)!=name_key(b.name) and not (ak and bk and ak&bk):return False
    try:_,unit=quantity(a.qty)
    except ValueError:return False
    if not unit or unit!=unit_key(b.unit):return False
    am,bm=char_map(a.chars),char_map(b.chars)
    if any(am[k]!=bm[k] for k in am.keys()&bm.keys()):return False
    return True

def compare(contract,notice):
    r=Comparison(number=contract.notice)
    if notice is None:return r
    r.revision=notice.revision
    if notice.number!=contract.notice:r.reason='Номер извещения изменён. Загрузите ЕИС повторно.';return r
    if contract.unknown:r.reason='В контракте количество не определено.';return r
    rows=getattr(notice,'items',[])
    problems=list(getattr(notice,'item_issues',[]))
    if not rows:r.reason='; '.join(problems) or 'Количество в извещении не найдено.';return r
    if not contract.items:r.reason='Спецификация контракта пуста.';return r
    candidates={i:[j for j,b in enumerate(rows) if _compatible(a,b)] for i,a in enumerate(contract.items)}
    reverse={j:[i for i,options in candidates.items() if j in options] for j in range(len(rows))}
    paired={i:opts[0] for i,opts in candidates.items() if len(opts)==1 and len(reverse[opts[0]])==1}
    matched=set(paired.values());base=Decimal(0);new=Decimal(0);priced=True
    def fmt(v):return format(v,'f').replace('.',',')
    for i,a in enumerate(contract.items):
        if i not in paired:
            r.rows.append(Difference(a.no,a.name,'—',a.qty,'—','Не сопоставлено'));continue
        b=rows[paired[i]]
        try:old=decimal(b.qty,allow_blank=False);current,unit=quantity(a.qty)
        except ValueError:
            problems.append('Неверное количество: '+a.name);continue
        diff=current-old
        r.rows.append(Difference(a.no,a.name,fmt(old)+' '+b.unit,a.qty,('+' if diff>0 else '')+fmt(diff),'Увеличение' if diff>0 else 'Уменьшение' if diff<0 else 'Совпадает'))
        r.changed+=int(diff!=0)
        try:
            price=decimal(a.price,allow_blank=False)
            with localcontext() as ctx:
                ctx.prec=60;base+=old*price;new+=current*price
        except ValueError:priced=False
    for j,b in enumerate(rows):
        if j not in matched:r.rows.append(Difference('ЕИС '+b.no,b.name,b.qty+' '+b.unit,'—','—','Нет однозначной пары'))
    if len(paired)!=len(contract.items) or len(matched)!=len(rows):problems.append('Не все позиции однозначно сопоставлены; общий процент не рассчитывается.')
    if problems:r.reason='; '.join(dict.fromkeys(problems));return r
    r.status='Есть изменения' if r.changed else 'Совпадает'
    r.reason='Все позиции сопоставлены. Количества '+('различаются.' if r.changed else 'совпадают.')
    if priced and base>0:
        with localcontext() as ctx:
            ctx.prec=60;r.baseline=base;r.delta=new-base;r.percent=(new-base)*100/base
    elif r.changed:r.reason='Нет корректной цены единицы или исходный объём имеет нулевую стоимость.'
    return r
