"""Conservative delivery candidates, explicit review before applying any value."""
from dataclasses import dataclass,field
from datetime import datetime
import re

MONTHS={m:i+1 for i,m in enumerate(('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'))}
DATE=r'(?:\d{1,2}[./]\d{1,2}[./]\d{4}|[«"\s]*\d{1,2}[»"\s]*\s*(?:'+ '|'.join(MONTHS)+r')\s+\d{4})'
NUM=r'(?:\d{1,4}(?:\s*\([^)]{1,40}\))?|одного|двух|трех|трёх|четырех|четырёх|пяти|шести|семи|восьми|девяти|десяти|пятнадцати|двадцати|тридцати|сорока|шестидесяти|девяноста)'
DURATION=re.compile(r'(?:в\s+течение|не\s+позднее(?:\s+чем)?|не\s+более|сроком|срок[^.;]{0,12})\s*(?:в\s+)?('+NUM+r')\s*(рабоч\w*|календарн\w*)?\s*(?:дней|дня|день|суток|сутки)\b',re.I)
ANCHOR=r'(?:с|s)\s+(?:момента|даты|дня)\s+(?:заключения|подписания)\s+(?:настоящего\s+)?конт[ра]*кта'
ANCHOR_RE=re.compile(ANCHOR,re.I)
EXCLUDE=re.compile(r'сообщить|приостанов|приемк|приёмк|оплат|замен[ауые]|недопостав|недостат|некачествен|уведомлен|подтвержден|подтверждён|возражени|гаранти|срок годности|остаточн|обеспечени|согласоват|информиров|устранени',re.I)

@dataclass
class Candidate:
    kind:str
    value:str
    source:str
    location:str

@dataclass
class DeliveryResult:
    main:list[Candidate]=field(default_factory=list)
    request:list[Candidate]=field(default_factory=list)
    warnings:list[str]=field(default_factory=list)
    notice_numbers:list[str]=field(default_factory=list)

def date_value(value):
    s=re.sub(r'[«»"]','',value).strip().lower()
    if re.fullmatch(r'\d{1,2}[./]\d{1,2}[./]\d{4}',s):
        day,month,year=map(int,re.split('[./]',s))
    else:
        m=re.fullmatch(r'(\d{1,2})\s*('+'|'.join(MONTHS)+r')\s+(\d{4})',s)
        if not m:raise ValueError('Дата не распознана.')
        day,month,year=int(m[1]),MONTHS[m[2]],int(m[3])
    return datetime(year,month,day).strftime('%d.%m.%Y')

def location(text,index):
    m=re.match(r'^\s*(\d+(?:\.\d+)+)\.?\s',text)
    return 'Пункт '+m[1] if m else 'Абзац '+str(index+1)

def sentences(text):
    # Do not split dates, point numbers, decimals or abbreviations such as «г.».
    return re.split(r'(?<=[.!?;])\s+(?=[А-ЯЁ])',text)

def find_delivery(paragraphs):
    result=DeliveryResult();section='';last_loc='';seen=set()
    # A notice number is corroborating evidence only, never inferred from a contract suffix.
    for p in paragraphs:
        if re.search(r'извещени|аукцион',p,re.I):
            result.notice_numbers.extend(re.findall(r'(?<!\d)\d{19}(?!\d)',p))
    result.notice_numbers=list(dict.fromkeys(result.notice_numbers))
    def add(kind,value,p,loc):
        key=(kind,value)
        if key not in seen:
            seen.add(key);getattr(result,kind).append(Candidate(kind,value,p,loc))
    for i,p in enumerate(paragraphs):
        if len(p)>20000:continue
        if re.match(r'^\d+\.\s+\D',p) and len(p)<140:section=p
        loc=location(p,i)
        if loc.startswith('Пункт'):last_loc=loc
        elif last_loc:loc=last_loc+' / следующий абзац'
        # Adjacent table cells: a short delivery label followed by its value.
        context=p
        if i and len(paragraphs[i-1])<100 and re.search(r'(?:срок|период).*постав',paragraphs[i-1],re.I):context=paragraphs[i-1]+' '+p
        for sentence in sentences(context):
            s=sentence.lower().replace('ё','е')
            delivery=bool(re.search(r'поставк[аиуы]|поставить|поставляется|поставляются|доставк[аиу]|отгрузк[аиу]',s))
            if not delivery:
                delivery=bool(re.search('постав',section,re.I) and re.match(r'^\s*(?:\d+\.\d+\.?\s*)?(?:срок|период|с\s+\d)',s))
            if not delivery or EXCLUDE.search(s):continue
            # Period / deadline. Preserve «до» versus «по» and inclusive wording.
            m=re.search(r'\bс\s+('+DATE+r')\s*(?:года|г\.)?\s*по\s+('+DATE+r')',s,re.I)
            try:
                if m:
                    a,b=date_value(m[1]),date_value(m[2])
                    if datetime.strptime(a,'%d.%m.%Y')>datetime.strptime(b,'%d.%m.%Y'):
                        result.warnings.append(loc+': дата начала позже даты окончания. Проверьте исходный текст.')
                    else:add('main',f'С {a} по {b}'+(' включительно' if 'включительно' in s[m.end():m.end()+35] else ''),p,loc)
                else:
                    end=re.search(r'\b(по|до)\s+('+DATE+r')',s,re.I)
                    if end:
                        anchor=ANCHOR_RE.search(s)
                        prefix=anchor[0][0].upper()+anchor[0][1:]+' ' if anchor else ''
                        value=prefix+end[1]+' '+date_value(end[2])
                        if 'включительно' in s[end.end():end.end()+35]:value+=' включительно'
                        add('main',value[0].upper()+value[1:],p,loc)
            except ValueError:result.warnings.append(loc+': некорректная дата. Укажите срок вручную.')
            for duration in DURATION.finditer(s):
                tail=s[duration.end():]
                # Only a direct temporal link to receiving an application qualifies.
                request=re.match(r'\s*(?:со?\s+(?:момента|даты|дня)\s+)(?:поступления|получения|направления|подачи)\s+(?:заказчиком\s+)?заявки(?:\s+(?:поставщиком|от заказчика))?',tail)
                anchor=ANCHOR_RE.match(tail.strip())
                interval=duration[0][0].upper()+duration[0][1:]
                if request:add('request',interval+' '+request[0].strip(),p,loc)
                elif anchor:add('main',interval+' '+anchor[0],p,loc)
                elif re.search('заявк',s) and not re.search('заявк',tail):
                    # «по заявке … в течение N дней»: preserve sentence, do not invent an anchor.
                    add('request',sentence.strip(),p,loc)
                elif not re.search('заявк',s):add('main',sentence.strip(),p,loc)
    if not result.main:result.warnings.append('Основной срок поставки не найден. Текущее поле останется без изменений.')
    if not result.request:result.warnings.append('Срок поставки по заявке не найден. Текущее поле останется без изменений.')
    if len(result.main)>1 or len(result.request)>1:result.warnings.append('Найдено несколько вариантов. Выберите подходящий по исходным пунктам.')
    return result

def load_delivery(path):
    from word_reader import read_word
    return find_delivery(read_word(path))
