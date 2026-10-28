"""Read-only EIS enrichment. Network requests are explicit and bounded."""
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
import re, time
from core import clean, text, normalized_label, decimal

MAX_BYTES=20*1024*1024
@dataclass
class Notice:
    number: str=''
    values: dict=field(default_factory=dict)
    warnings: list=field(default_factory=list)
    source: str=''
    revision: str=''
    items: list=field(default_factory=list)
    item_issues: list=field(default_factory=list)

def notice_url(number):
    number=clean(number)
    if not re.fullmatch(r'\d{19}',number):raise ValueError('Номер извещения должен содержать ровно 19 цифр. Проверьте поле «Номер извещения».')
    return 'https://zakupki.gov.ru/epz/order/notice/printForm/view.html?'+urlencode({'regNumber':number})

def yes_no(value):
    value=normalized_label(value)
    if value in ('✓','✔','☑','true'):return 'Да'
    if value in ('✗','✘','☒','false'):return 'Нет'
    if value in ('да','установлено','установлен','предусмотрено'):return 'Да'
    if value in ('нет','не установлено','не установлен','не предусмотрено','отсутствует','не установлены'):return 'Нет'
    return None

def read_amount(value):
    match=re.fullmatch(r'\s*([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:РОССИЙСКИЙ РУБЛЬ|руб\.?|RUB|₽)?\s*',value,re.I)
    if not match:return None
    try:return str(decimal(match.group(1),allow_blank=False))
    except ValueError:return None

def parse_notice(raw, expected='', source='', trusted_number=''):
    from lxml import html
    if len(raw)>MAX_BYTES:raise ValueError('Извещение больше 20 МБ.')
    try:
        try:decoded=raw.decode('utf-8-sig')
        except UnicodeDecodeError:decoded=raw
        root=html.fromstring(decoded,parser=html.HTMLParser(no_network=True))
    except Exception as e:raise ValueError('Не удалось прочитать HTML извещения.') from e
    for e in root.xpath('//script|//style'):e.drop_tree()
    body=text(root)
    rows=[]
    for row in root.xpath('//tr[not(.//tr)]'):
        cells=row.xpath('./td|./th')
        if cells:
            value=clean(' '.join(text(c) for c in cells[1:]))
            if not value:
                marks=[]
                for cell in cells:
                    marks.extend(cell.xpath('.//@alt|.//@aria-label|.//@title'))
                    for check in cell.xpath('.//input[@type="checkbox"]'):
                        marks.append('Да' if 'checked' in check.attrib else 'Нет')
                value=' '.join(m for m in marks if yes_no(m))
                if not value and any(c.xpath('.//img|.//svg') for c in cells[1:]):value='Нераспознанная графическая отметка'
            rows.append((normalized_label(text(cells[0])),value))
    # Also support field blocks used by public common-info pages.
    for label in root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," section__title ")]'):
        siblings=label.xpath('following-sibling::*[1]')
        if siblings:rows.append((normalized_label(text(label)),text(siblings[0])))
    # Some print forms render the affirmative condition as a standalone paragraph,
    # rather than a label followed by a Yes cell. Only the full field statement qualifies.
    for node in root.xpath('//p[not(ancestor::td)]|//div[not(*) and not(ancestor::td)]'):
        key=normalized_label(text(node))
        if key.startswith('предметом контракта является поставка товара') and len(key)<350 and not any(k==key for k,v in rows):
            sibling=node.xpath('following-sibling::*[1]')
            value=text(sibling[0]) if sibling and yes_no(text(sibling[0])) else ''
            rows.append((key,value))
    nums=set()
    for key,value in rows:
        if key.startswith(('номер извещения','реестровый номер извещения')):
            nums.update(re.findall(r'(?<!\d)\d{19}(?!\d)',value))
    for match in re.finditer(r'(?:извещени[ея]|закупк[аи])[^\d]{0,180}?(?:№|номер)?\s*(\d{19})(?!\d)',body,re.I):nums.add(match.group(1))
    for href in root.xpath('//link[@rel="canonical"]/@href|//meta[@property="og:url"]/@content'):
        nums.update(n for n in parse_qs(urlparse(href).query).get('regNumber',[]) if re.fullmatch(r'\d{19}',n))
    if len(nums)>1:raise ValueError('В файле несколько номеров извещений. Выберите печатную форму одной закупки.')
    number=next(iter(nums),'')
    if number and expected and number!=expected:raise ValueError(f'Извещение № {number} не совпадает с контрактом № извещения {expected}. Данные не применены.')
    # A successful fetch from the exact canonical print URL can bind a form without a visible number.
    if not number and trusted_number==expected and trusted_number:number=trusted_number
    if not number:raise ValueError('Номер извещения в HTML не найден. Нужна полная печатная форма извещения с номером закупки.')
    result=Notice(number=number,source=source)
    ikzs=[]
    amounts={'nmck':[], 'initial_units':[], 'maximum':[]};flags={'smp':[],'life':[]};platforms=[]
    seen_flags=set()
    for key,value in rows:
        if key=='способ определения поставщика (подрядчика, исполнителя)' and value:result.values['procurement_method']=value
        if key in ('идентификационный код закупки','идентификационный код закупки (икз)','икз'):
            ikz=re.sub(r'\s+','',value)
            if re.fullmatch(r'\d{36}',ikz):ikzs.append(ikz)
        compact=re.sub(r'\s+','',key)
        bucket=None
        if re.fullmatch(r'начальная\s*\(максимальная\)\s*цена контракта(?:[, ]*\(?руб\.?\)?)?',key):bucket='nmck'
        elif key in ('начальная сумма цен единиц товара, работы, услуги','начальная сумма цен единиц товаров, работ, услуг','начальная сумма цен единиц'):bucket='initial_units'
        elif key in ('максимальное значение цены контракта','максимальное значение цены контрактов'):bucket='maximum'
        if bucket:
            amount=read_amount(value)
            if amount is not None:amounts[bucket].append(amount)
        if 'жизнеобеспечени' in key and re.search(r'(?:ч\.?|част(?:ь|и|ью))\s*9\b',key) and re.search(r'(?:ст\.?|стать(?:и|я|ей|е))\s*37\b',key):
            seen_flags.add('life')
            flag=yes_no(value)
            if not value and key.startswith('предметом контракта является поставка товара') and '?' not in key:
                flag='Да'
                result.warnings.append('Жизнеобеспечение: найдена утвердительная строка условия ч. 9 ст. 37 без отдельного значения — «Да». Сверьте с извещением.')
            if flag:flags['life'].append(flag)
        if key in ('преимущества','преимущества участникам закупки') or ('преимущество' in key and re.search(r'30\b',key)):
            combined=key+' '+value.lower()
            exact=re.search(r'(?:ч\.?|част(?:ь|и|ью))\s*3\s*(?:ст\.?|стать(?:и|я|ей|е))\s*30\b',combined)
            if exact:
                seen_flags.add('smp')
                if re.search(r'не определен|неизвестн|нет данных',value.lower()):continue
                flags['smp'].append('Нет' if yes_no(value)=='Нет' or re.search(r'не (?:установлен[оы]?|предусмотрен[оы]?)',value.lower()) else 'Да')
            elif yes_no(value)=='Нет':flags['smp'].append('Нет')
        if key.startswith('наименование электронной площадки'):
            v=value.lower()
            for needle,platform in [('росэлторг','Росэлторг'),('фабрикант','Фабрикант'),('сбербанк','СбербанкАСТ'),('р т с','РТС-Тэндер'),('ртс','РТС-Тэндер')]:
                if needle in v:platforms.append(platform);break
        if key in ('дата размещения извещения','дата и время размещения извещения','дата размещения текущей редакции извещения','номер редакции извещения'):
            result.revision+='; '+key+': '+value
    if len(set(ikzs))==1:result.values['ikz']=ikzs[0]
    elif len(set(ikzs))>1:result.warnings.append('В извещении несколько ИКЗ — укажите код своего контракта вручную.')
    for key,values in amounts.items():
        unique=set(values)
        if len(unique)==1:result.values[key]=unique.pop()
        elif len(unique)>1:result.warnings.append('Различаются суммы '+key+': возможна совместная закупка. Значение не перенесено.')
    for key,values in flags.items():
        unique=set(values)
        if len(unique)==1:result.values[key]=unique.pop()
        elif len(unique)>1:result.warnings.append('Противоречивые значения '+key+'. Проверьте извещение.')
    if len(set(platforms))==1:result.values['etp']=platforms[0]
    if not result.values:raise ValueError('Поля извещения не распознаны. Возможно, вместо печатной формы получена страница ошибки или проверки доступа.')
    normalized=normalized_label(body)
    complete=(b'</html>' in raw.lower() and
        all(re.search(pattern,normalized) for pattern in
            (r'общая информация',r'(?:объект закупки|описание объекта закупки)',r'(?:требования к участникам|преимущества участникам|преимущества и требования)')))
    for key,label in [('life','Жизнеобеспечение'),('smp','СМП / СОНКО')]:
        if key in result.values:continue
        if complete and key not in seen_flags and not flags[key]:
            result.values[key]='Нет'
            result.warnings.append(label+': в полной форме условие не найдено → «Нет».')
        else:result.warnings.append(label+': не определено. Проверьте исходное извещение; значение не заменено.')
    from quantity_check import parse_items
    result.items,result.item_issues=parse_items(root)
    if b'</html>' not in raw.lower():result.item_issues.append('HTML извещения может быть обрезан: полная форма не подтверждена.')
    if re.search(r'(?:невозможно определить количество|количество не определено)[^-–—:]{0,100}[-–—:]\s*да\b',body,re.I):
        result.item_issues.append('В извещении количество не определено.')
    for key,value in rows:
        if ('совместн' in key and yes_no(value)=='Да') or key.startswith('количество заказчиков') and value.strip() not in ('','1'):
            result.item_issues.append('Совместная закупка: количество требует сверки по своему заказчику.')
    result.revision=result.revision.lstrip('; ') or 'Редакция не распознана — сверьте актуальность извещения.'
    return result

def load_notice(path,expected):
    return parse_notice(Path(path).read_bytes(),expected,source=str(path))

class EISRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        p=urlparse(newurl)
        if p.scheme!='https' or p.hostname not in ('zakupki.gov.ru','www.zakupki.gov.ru'):
            raise ValueError('ЕИС перенаправила запрос на другой адрес. Откройте извещение в браузере.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch_notice(number):
    url=notice_url(number);start=time.monotonic()
    try:
        with build_opener(EISRedirect()).open(Request(url,headers={'User-Agent':'ContractPrintApp/1.11.1','Accept':'text/html'}),timeout=15) as response:
            content_type=response.headers.get_content_type()
            if content_type not in ('text/html','application/xhtml+xml'):raise ValueError('ЕИС вернула документ другого типа. Загрузите HTML извещения вручную.')
            chunks=[];length=0
            while True:
                if time.monotonic()-start>30:raise ValueError('ЕИС не ответила вовремя. Попробуйте позже или загрузите HTML извещения.')
                chunk=response.read(65536)
                if not chunk:break
                chunks.append(chunk);length+=len(chunk)
                if length>MAX_BYTES:raise ValueError('Ответ ЕИС больше 20 МБ.')
            final_url=response.geturl()
            final_number=parse_qs(urlparse(final_url).query).get('regNumber',[''])[0]
            return parse_notice(b''.join(chunks),number,source=final_url,trusted_number=final_number)
    except HTTPError as e:raise ValueError(f'ЕИС недоступна (HTTP {e.code}). Откройте извещение в браузере и загрузите сохранённый HTML.') from e
    except (URLError,TimeoutError,OSError) as e:raise ValueError('Не удалось подключиться к ЕИС. Проверьте интернет или загрузите сохранённый HTML извещения.') from e
