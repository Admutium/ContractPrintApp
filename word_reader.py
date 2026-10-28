"""Local DOCX / Word 97-2003 text reader. Does not run macros or Office.

Binary text: MS-DOC 2.4.1 Retrieving Text, FibRgFcLcb97, FcCompressed.
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/01d5d8c4-cf9c-4ef9-80fd-439e763cfe01
"""
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import re, struct

LIMIT=20*1024*1024

def field_results(text):
    out=[];stack=[]
    for c in text:
        if c=='\x13':stack.append(False)
        elif c=='\x14' and stack:stack[-1]=True
        elif c=='\x15' and stack:stack.pop()
        elif all(stack):out.append(c)
    return ''.join(out)

def binary_text(word,table):
    def number(data,offset,size=2):
        if offset<0 or offset+size>len(data):raise ValueError('Повреждена структура DOC.')
        return int.from_bytes(data[offset:offset+size],'little')
    if number(word,0)!=0xA5EC or number(word,2)<0xC1:
        raise ValueError('Поддерживается DOC Word 97–2003. Сохраните документ как DOCX.')
    if number(word,10)&0x8100:raise ValueError('DOC защищён паролем. Нужна копия без пароля.')
    pos=32;csw=number(word,pos);pos+=2+2*csw
    cslw=number(word,pos);pos+=2
    if cslw<4:raise ValueError('Не найден основной текст DOC.')
    count=number(word,pos+12,4)
    if count>LIMIT:raise ValueError('Слишком большой текст DOC.')
    pos+=4*cslw;pair_count=number(word,pos);pos+=2
    if pair_count<=33:raise ValueError('DOC не содержит таблицу текста. Сохраните как DOCX.')
    fc=number(word,pos+33*8,4);length=number(word,pos+33*8+4,4)
    if not length or fc+length>len(table):raise ValueError('Повреждена таблица текста DOC.')
    clx=table[fc:fc+length];offset=0
    while offset<len(clx) and clx[offset]==1:offset+=3+number(clx,offset+1)
    if offset>=len(clx) or clx[offset]!=2:raise ValueError('Не удалось прочитать текст DOC.')
    size=number(clx,offset+1,4);plc=clx[offset+5:offset+5+size]
    if len(plc)!=size or size<4 or (size-4)%12:raise ValueError('Повреждены фрагменты DOC.')
    n=(size-4)//12;cps=[number(plc,i*4,4) for i in range(n+1)]
    if cps[0]!=0 or any(a>b for a,b in zip(cps,cps[1:])) or cps[-1]<count:
        raise ValueError('Неверный порядок фрагментов DOC.')
    parts=[]
    for i in range(n):
        start,end=cps[i],min(cps[i+1],count)
        if start>=count:break
        f=number(plc,4*(n+1)+8*i+2,4);compressed=bool(f&0x40000000);f&=0x3fffffff
        at=f//2 if compressed else f;size=(end-start)*(1 if compressed else 2)
        if at+size>len(word):raise ValueError('Обнаружен обрезанный текст DOC.')
        data=word[at:at+size]
        if compressed:
            # MS-DOC 2.9.73: Latin-1 plus the listed Windows punctuation mappings.
            chars=[]
            for b in data:
                if b in (0x82,0x83,0x84,0x85,0x86,0x87,0x88,0x89,0x8a,0x8b,0x8c,0x91,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,0x9a,0x9b,0x9c,0x9f):chars.append(bytes([b]).decode('cp1252'))
                else:chars.append(chr(b))
            parts.append(''.join(chars))
        else:parts.append(data.decode('utf-16-le'))
    return field_results(''.join(parts))

def read_doc(path):
    import olefile
    try:
        with olefile.OleFileIO(str(path)) as ole:
            if not ole.exists('WordDocument'):raise ValueError('Это не текстовый документ Word DOC.')
            if ole.get_size('WordDocument')>LIMIT:raise ValueError('Слишком большой поток DOC.')
            word=ole.openstream('WordDocument').read()
            if len(word)<12:raise ValueError('DOC повреждён.')
            flags=int.from_bytes(word[10:12],'little')
            if flags&0x8100:raise ValueError('DOC защищён паролем. Нужна копия без пароля.')
            name='1Table' if flags&0x200 else '0Table'
            if not ole.exists(name) or ole.get_size(name)>LIMIT:raise ValueError('Нет таблицы текста DOC.')
            return binary_text(word,ole.openstream(name).read())
    except (OSError,struct.error,UnicodeError) as e:raise ValueError('Не удалось прочитать DOC. Сохраните его как DOCX.') from e

def read_docx(path):
    from lxml import etree
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    try:
        with ZipFile(path) as archive:
            info=archive.getinfo('word/document.xml')
            if info.file_size>LIMIT:raise ValueError('Текст DOCX больше 20 МБ.')
            root=etree.fromstring(archive.read(info),etree.XMLParser(resolve_entities=False,no_network=True))
        # Include tables and text boxes in document order, exclude tracked deletions.
        paragraphs=[]
        for p in root.xpath('//w:body//w:p[not(ancestor::w:del)]',namespaces=ns):
            pieces=[]
            for e in p.xpath('.//w:t|.//w:tab|.//w:br',namespaces=ns):
                if e.xpath('ancestor::w:del',namespaces=ns):continue
                if e.xpath('ancestor::w:p[1]',namespaces=ns)[0]!=p:continue
                pieces.append(e.text or '' if e.tag.endswith('}t') else ' ')
            paragraphs.append(''.join(pieces))
        return '\n'.join(paragraphs)
    except (BadZipFile,KeyError,etree.XMLSyntaxError) as e:raise ValueError('DOCX повреждён или имеет другой формат.') from e

def read_word(path):
    path=Path(path)
    if path.stat().st_size>LIMIT:raise ValueError('Файл больше 20 МБ.')
    suffix=path.suffix.lower()
    if suffix=='.docx':text=read_docx(path)
    elif suffix=='.doc':text=read_doc(path)
    else:raise ValueError('Выберите документ DOC или DOCX.')
    text=re.sub(r'[\r\x07\x0b\x0c]','\n',text)
    text=re.sub(r'[\x00-\x08\x0e-\x1f]','',text)
    paragraphs=[re.sub(r'\s+',' ',s).strip() for s in text.splitlines()]
    paragraphs=[s for s in paragraphs if s]
    if not paragraphs:raise ValueError('В документе нет доступного текста. Возможно, это скан.')
    return paragraphs
