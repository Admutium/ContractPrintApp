"""Execution-security payment data; never mix bid and warranty bank details."""
from dataclasses import dataclass,field
from decimal import Decimal,ROUND_HALF_UP
import re
from core import clean,normalized_label,decimal,extract_inn,table_fields

MODES=('Из контракта / извещения','% от НМЦК','% от цены контракта','Своя сумма')
PARTY_FIELDS=('name','inn','kpp','account','bank','bik','bank_account')

@dataclass
class PaymentSource:
    payer:dict=field(default_factory=dict)
    recipient:dict=field(default_factory=dict)
    mode:str=''
    percent:str=''
    amount:str=''
    terms:str=''
    purpose:str=''
    extra:dict=field(default_factory=dict)
    warnings:list=field(default_factory=list)
    source:str=''


def unique(values):
    values=list(dict.fromkeys(clean(v) for v in values if clean(v) and normalized_label(v) not in ('информация отсутствует','не указано','-')))
    return values[0] if len(values)==1 else ''


def parse_bank(value):
    """Structured labels or quoted print-form labels; no unlabelled digit guessing."""
    labels={
        'name':r'получатель(?:\s+платежа)?|наименование получателя',
        'inn':r'инн(?:\s+получателя)?','kpp':r'кпп(?:\s+получателя)?',
        'account':r'номер банковского счета|номер расчетного счета|расчетный счет|казначейский счет|р\s*/\s*с|счет получателя',
        'bank_account':r'номер корреспондентского счета|корреспондентский счет|единый казначейский счет|екс|к\s*/\s*с|счет банка получателя',
        'bank':r'наименование кредитной организации|наименование банка|банк получателя|банк',
        'bik':r'бик(?:\s+банка)?',
        'ignored':r'код поступления',
        'personal':r'номер лицевого счета|лицевой счет|л\s*/\s*с',
        'kbk':r'кбк|код бюджетной классификации','oktmo':r'октмо',
        'purpose':r'назначение платежа','uin':r'уин|уникальный идентификатор начисления',
    }
    # Long alternatives precede short labels, so "банк получателя" stays one field.
    patterns=sorted(((p,k) for k,p in labels.items()),key=lambda x:len(x[0]),reverse=True)
    token='|'.join('(?P<'+k+'>'+p+')'+(r'(?=\s*["»:=])' if k in ('name','bank','purpose') else r'(?![\w])') for p,k in patterns)
    normalized=clean(value).replace('ё','е').replace('Ё','Е')
    matches=list(re.finditer(r'(?<![\w])(?:'+token+r')["»\s:№=]*',normalized,re.I))
    found={}
    for i,m in enumerate(matches):
        key=m.lastgroup
        if key=='ignored':continue
        val=normalized[m.end():matches[i+1].start() if i+1<len(matches) else len(normalized)].strip(' ;,|"«»')
        if key in ('inn','kpp','bik','account','bank_account','kbk','oktmo','uin','personal'):
            val=re.sub(r'\s','',val).strip(' ;,|"«»')
            lengths={'inn':(10,12),'kpp':(9,),'bik':(9,),'account':(20,),'bank_account':(20,),'kbk':(20,),'oktmo':(8,11),'uin':(1,20,25)}
            if key=='personal':
                if not re.fullmatch(r'[\w-]{1,40}',val):continue
            elif not val.isdigit() or len(val) not in lengths[key]:continue
        found.setdefault(key,[]).append(val)
    return {k:v for k,values in found.items() if (v:=unique(values))}


def parse_security_rows(rows,source=''):
    result=PaymentSource(source=source);amounts=[];percentages=[];terms=[];banks=[]
    scope=''
    for label,value,is_heading in rows:
        key=normalized_label(label)
        execution=bool(re.search(r'обеспечени\w* исполнени\w* контракт',key))
        other=bool(re.search(r'обеспечени\w* (?:заявк|гарантийн)',key))
        if is_heading:
            scope='execution' if execution else 'other' if other else ''
        elif execution:scope='execution'
        elif other:scope='other'
        if scope!='execution':continue
        if re.search(r'размер|сумма',key) and not re.search(r'счет|счёт',key):
            terms.append(value)
            percentages.extend(p.replace(',','.') for p in re.findall(r'(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:%|процент\w*)',value,re.I))
            # Only a pure amount with optional currency qualifies as a fixed sum.
            if re.fullmatch(r'[\d\s\u00a0]+(?:[.,]\d+)?\s*(?:руб(?:лей|ля|ль|\.)?|₽|российский рубль)?',clean(value),re.I):
                try:amounts.append(str(decimal(re.sub(r'[^\d\s,.]','',value),allow_blank=False)))
                except ValueError:pass
        elif re.search(r'порядок|требовани|услови',key):terms.append(value)
        if re.search(r'реквизит|получател|(?:^|\s)(?:инн|кпп|бик|кбк|октмо)|счет|счёт|банк',key):
            banks.append(label+': '+value if not re.search(r'реквизит',key) else value)
    result.terms=' '.join(dict.fromkeys(terms))
    bank=parse_bank(' | '.join(banks))
    result.recipient={k:bank[k] for k in PARTY_FIELDS if bank.get(k)}
    result.extra={k:bank[k] for k in ('kbk','oktmo','uin','personal') if bank.get(k)}
    result.purpose=bank.get('purpose','')
    result.percent=unique(percentages);result.amount=unique(amounts)
    text=normalized_label(result.terms)
    nmck=bool(re.search(r'нмцк|начальн\w*\s*\(?максимальн',text))
    contract=bool(re.search(r'(?:от|из|в размере[^.]{0,35})\s*(?:\d+(?:[.,]\d+)?\s*%\s*от\s*)?(?:цен[ыа]|сумм[ыа]|стоимост[ьи])\s*(?:заключаемого\s*|заключенного\s*|заключения\s*)?контракта',text))
    if result.percent and nmck!=contract:result.mode=MODES[1] if nmck else MODES[2]
    elif result.amount and not result.percent:result.mode=MODES[0]
    if terms and not result.mode:result.warnings.append('Основание расчёта обеспечения не определено однозначно. Выберите вариант вручную.')
    if re.search(r'антидемпинг|стать[еьи]\s*37|ст\.?\s*37|в полтора|1[,.]5',text):
        result.warnings.append('Есть условия увеличения обеспечения. Проверьте применимость статьи 37; повышение автоматически не применяется.')
    if not result.recipient:result.warnings.append('Реквизиты для обеспечения исполнения не найдены. Заполните получателя вручную.')
    return result


def contract_section(root, number):
    for heading in root.xpath('//p|//h2|//h3|//h4'):
        if re.match(r'^'+re.escape(number)+r'(?:[.\s]|$)', clean(heading.text_content())):
            return heading.getparent()
    return None


def section_records(section):
    if section is None:
        return []
    records = []
    headers = []
    for row in section.xpath('.//tr[not(.//tr)]'):
        cells = [clean(cell.text_content()) for cell in row.xpath('./td|./th')]
        if not cells:
            continue
        if normalized_label(cells[0]).startswith(('наименование организации', 'вид обеспечения')):
            headers = [normalized_label(cell) for cell in cells]
        elif headers and len(cells) == len(headers) and not all(v.isdigit() for v in cells):
            records.append(dict(zip(headers, cells)))
    return records


def apply_contract_sections(root, result):
    customer = table_fields(contract_section(root, '2.1'))
    if customer.get('полное наименование'):
        result.recipient['name'] = customer['полное наименование']
    if inn := extract_inn(customer):
        result.recipient['inn'] = inn
    if kpp := next((v for k,v in customer.items() if k.startswith('кпп') and re.fullmatch(r'\d{9}',v)), ''):
        result.recipient['kpp'] = kpp

    accounts = section_records(contract_section(root, '5.5'))
    if accounts:
        for key in ('account','bank','bik','bank_account'):
            result.recipient.pop(key,None)
        for key in ('personal','counterparty','account_type'):
            result.extra.pop(key,None)
        if len(accounts) == 1:
            row = accounts[0]
            bank = row.get('реквизиты банка, тофк','')
            details = parse_bank(re.sub(r'(?i)бик\s*:', ' | БИК: ', bank))
            # The bank name precedes BIK in the print form, sometimes without whitespace.
            bank_name = re.split(r'бик\s*[:№]', bank, maxsplit=1, flags=re.I)[0].strip(' ,;')
            account = row.get('номер банковского (казначейского) счета','')
            for key,value in {'account':account,'bank':bank_name,'bik':details.get('bik'),
                              'bank_account':details.get('bank_account')}.items():
                if value:
                    result.recipient[key] = value
            identity = next(iter(row.values()),'')
            ids = re.search(r'(?<!\d)(\d{10}|\d{12})\s*[/,]\s*(\d{9})(?!\d)', identity)
            if not ids:
                ids = re.search(r'ИНН\s*:?\s*(\d{10}|\d{12})\D{0,15}КПП\s*:?\s*(\d{9})',identity,re.I)
            if ids and not result.recipient.get('inn'):
                result.recipient['inn'] = ids[1]
            if ids and ids[1] == result.recipient.get('inn'):
                result.recipient.setdefault('kpp',ids[2])
            for key,label in {'personal':'номер лицевого счета','counterparty':'наименование контрагента для п/п',
                              'account_type':'тип счета'}.items():
                if value := unique([row.get(label,'')]):
                    result.extra[key] = value
        else:
            result.warnings.append('В пункте 5.5 несколько счетов. Укажите нужный счёт по контракту.')

    for row in section_records(contract_section(root, '4.5')):
        if normalized_label(row['вид обеспечения']) != 'обеспечение исполнения контракта':
            continue
        for key,value in row.items():
            if not key.startswith('размер обеспечения') or not value:
                continue
            try:
                number = decimal(re.sub(r'\s*(?:%|руб\.?|₽)$','',value,flags=re.I))
            except ValueError:
                continue
            if number is not None:
                if '%' in key:
                    result.percent = str(number)
                else:
                    result.amount = str(number)
        result.terms = row.get('порядок предоставления, требования к обеспечению','') or result.terms
        if result.amount:
            result.mode = MODES[0]
        elif result.percent:
            result.mode = parse_security_rows([
                ('Обеспечение исполнения контракта','',True),
                ('Размер обеспечения',result.percent+'%',False),
                ('Порядок',result.terms,False)
            ]).mode
            if not result.mode:
                result.warnings.append('Укажите базу расчёта процента из пункта 4.5.')
        break
    if result.recipient:
        result.warnings = [w for w in result.warnings if not w.startswith('Реквизиты для обеспечения')]
    return result


def parse_payment_html(raw,source='HTML'):
    from lxml import html
    if len(raw)>20*1024*1024:raise ValueError('HTML больше 20 МБ.')
    try:decoded=raw.decode('utf-8-sig')
    except UnicodeDecodeError:decoded=raw
    root=html.fromstring(decoded,parser=html.HTMLParser(no_network=True))
    for e in root.xpath('//script|//style'):e.drop_tree()
    rows=[]
    for row in root.xpath('//tr[not(.//tr)]|//p[not(ancestor::tr)]|//h2[not(ancestor::tr)]|//h3[not(ancestor::tr)]|//h4[not(ancestor::tr)]'):
        if row.tag!='tr':
            label=clean(row.text_content())
            if len(label)<180 and re.search(r'обеспечени|^\d+\.',normalized_label(label)):rows.append((label,'',True))
            continue
        cells=row.xpath('./td|./th')
        if not cells:continue
        label=clean(cells[0].text_content());value=clean(' '.join(c.text_content() for c in cells[1:]))
        heading=bool(cells[0].xpath('.//*[contains(@class,"caption")]|.//b|.//strong')) and not value
        rows.append((label,value,heading or len(cells)==1))
    result=parse_security_rows(rows,source)
    # Contract supplier subsection; bank details for payer only inside this subsection.
    for node in root.xpath('//p|//h2|//h3|//h4'):
        label=normalized_label(node.text_content())
        if not (label.startswith('2.2.') and re.search(r'поставщик|подрядчик|исполнитель',label)):continue
        parent=node.getparent();fields={}
        for row in parent.xpath('.//tr[not(.//tr)]'):
            cells=row.xpath('./td|./th')
            if len(cells)>1:fields[normalized_label(cells[0].text_content())]=clean(' '.join(c.text_content() for c in cells[1:]))
        result.payer={}
        name=fields.get('полное наименование') or fields.get('фио физического лица')
        if name:result.payer['name']=name
        break
    if contract_section(root,'2.1') is not None or contract_section(root,'5.5') is not None:
        apply_contract_sections(root,result)
    return result


def calculate(mode,percent='',notice_amount='',contract_total='',nmck='',custom=''):
    if mode not in MODES:raise ValueError('Выберите способ определения размера обеспечения.')
    if mode in MODES[1:3]:
        pct=decimal(percent,'Процент обеспечения',False)
        if pct>100:raise ValueError('Процент обеспечения не может превышать 100%.')
        base=decimal(nmck if mode==MODES[1] else contract_total,'НМЦК' if mode==MODES[1] else 'Цена контракта',False)
        value=base*pct/100
    else:value=decimal(notice_amount if mode==MODES[0] else custom,'Сумма обеспечения',False)
    return value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def amount_words(value):
    value=Decimal(value).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    whole=int(value);kopeks=int((value-whole)*100)
    if whole>=10**15:raise ValueError('Сумма слишком велика для платёжного поручения.')
    ones=('','один','два','три','четыре','пять','шесть','семь','восемь','девять')
    teens=('десять','одиннадцать','двенадцать','тринадцать','четырнадцать','пятнадцать','шестнадцать','семнадцать','восемнадцать','девятнадцать')
    tens=('','','двадцать','тридцать','сорок','пятьдесят','шестьдесят','семьдесят','восемьдесят','девяносто')
    hundreds=('','сто','двести','триста','четыреста','пятьсот','шестьсот','семьсот','восемьсот','девятьсот')
    def form(n,forms):return forms[2] if 11<=n%100<=14 else forms[0] if n%10==1 else forms[1] if 2<=n%10<=4 else forms[2]
    parts=[]
    for group,forms in ((4,('триллион','триллиона','триллионов')),(3,('миллиард','миллиарда','миллиардов')),(2,('миллион','миллиона','миллионов')),(1,('тысяча','тысячи','тысяч')),(0,('','',''))):
        n=whole//1000**group%1000
        if not n:continue
        parts.append(hundreds[n//100]);tail=n%100
        if tail<10:parts.append(('','одна','две',*ones[3:])[tail] if group==1 else ones[tail])
        elif tail<20:parts.append(teens[tail-10])
        else:parts.extend((tens[tail//10],('','одна','две',*ones[3:])[tail%10] if group==1 else ones[tail%10]))
        if group:parts.append(form(n,forms))
    text=' '.join(x for x in parts if x) or 'ноль'
    return (text+' '+form(whole,('рубль','рубля','рублей'))+f' {kopeks:02d} '+form(kopeks,('копейка','копейки','копеек'))).capitalize()


def validate(data):
    problems=[]
    for key,label in (('payer_name','полное название плательщика'),
                      ('recipient_name','полное название ЛПУ'),
                      ('recipient_inn','ИНН ЛПУ')):
        if not data.get(key,'').strip():
            problems.append('Не заполнено: '+label)
    for key,label,lengths in (
        ('recipient_inn','ИНН ЛПУ',(10,12)), ('recipient_kpp','КПП ЛПУ',(9,)),
        ('recipient_account','банковский / казначейский счёт',(20,)),
        ('recipient_bik','БИК',(9,)), ('recipient_bank_account','корреспондентский счёт / ЕКС',(20,))
    ):
        value=data.get(key,'')
        if value and (not value.isdigit() or len(value) not in lengths):
            problems.append('Неверный формат: '+label)
    try:
        if Decimal(data.get('amount','0'))<=0:
            problems.append('Укажите сумму обеспечения больше нуля')
    except ArithmeticError:
        problems.append('Не определена сумма обеспечения')
    for key,lengths in (('kbk',(20,)),('oktmo',(8,11)),('uin',(1,20,25))):
        v=data.get(key,'')
        if v and (not v.isdigit() or len(v) not in lengths):problems.append('Неверный формат поля '+key.upper())
    return problems
