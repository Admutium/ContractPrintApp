from datetime import datetime
MONTHS=('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
BLANK_DATE='от «____» ____________ 20____ г.'

def date_line(concluded,value):
    if not concluded:return BLANK_DATE
    try:d=datetime.strptime(value.strip(),'%d.%m.%Y')
    except ValueError:raise ValueError('Укажите дату заключения контракта в формате ДД.ММ.ГГГГ.')
    return f'от {d.day} {MONTHS[d.month-1]} {d.year} г.'
