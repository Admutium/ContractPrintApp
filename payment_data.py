"""Execution-security payment data; never mix bid and warranty bank details."""
from dataclasses import dataclass,field,asdict
from decimal import Decimal,ROUND_HALF_UP
import re
from core import clean,normalized_label,decimal

MODES=('Из извещения','% от НМЦК','% от цены контракта','Своя сумма')
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
        result.payer=parse_bank(' | '.join(k+': '+v for k,v in fields.items()))
        name=fields.get('полное наименование') or fields.get('фио физического лица')
        if name:result.payer['name']=name
        break
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
    for side,title in (('payer','плательщика'),('recipient','получателя')):
        for key,label in (('name','полное наименование'),('inn','ИНН'),('account','счёт'),('bank','банк'),('bik','БИК'),('bank_account','корреспондентский / единый казначейский счёт')):
            value=data.get(side+'_'+key,'').strip()
            if not value:problems.append('Не заполнено: '+label+' '+title)
            elif key in ('inn','account','bik','bank_account'):
                valid={'inn':(10,12),'account':(20,),'bik':(9,),'bank_account':(20,)}[key]
                if not value.isdigit() or len(value) not in valid:problems.append('Неверный формат: '+label+' '+title)
        kpp=data.get(side+'_kpp','')
        if len(data.get(side+'_inn',''))==10 and not kpp:problems.append('Не заполнен КПП '+title)
        if kpp and not re.fullmatch(r'\d{9}',kpp):problems.append('КПП '+title+' должен содержать 9 цифр')
    if not data.get('purpose','').strip():problems.append('Не заполнено назначение платежа')
    try:
        if Decimal(data.get('amount','0'))<=0:problems.append('Сумма обеспечения должна быть больше нуля')
    except Exception:problems.append('Не определена сумма обеспечения')
    from datetime import datetime
    try:datetime.strptime(data.get('date',''),'%d.%m.%Y')
    except ValueError:problems.append('Дата поручения должна быть в формате ДД.ММ.ГГГГ')
    if not re.fullmatch(r'\d{1,6}',data.get('number','')):problems.append('Номер поручения: от 1 до 6 цифр')
    for key,lengths in (('kbk',(20,)),('oktmo',(8,11)),('uin',(1,20,25))):
        v=data.get(key,'')
        if v and (not v.isdigit() or len(v) not in lengths):problems.append('Неверный формат поля '+key.upper())
    return problems
