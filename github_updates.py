"""Anonymous, bounded downloads from this application's public GitHub releases."""
import json
from pathlib import Path
import re
import tempfile
import time
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from updater import MAX_ARCHIVE, InstallLock, digest, version_tuple

REPOSITORY='Admutium/ContractPrintApp'
API='https://api.github.com/repos/'+REPOSITORY+'/releases/latest'
MANIFEST='update-ContractPrintApp.json'
LATEST_MANIFEST='https://github.com/'+REPOSITORY+'/releases/latest/download/'+MANIFEST


def connection_message(error,url):
    reason=getattr(error,'reason',error)
    host=urlparse(url).hostname or 'GitHub'
    if isinstance(reason,ssl.SSLCertVerificationError):
        detail='не пройдена проверка HTTPS-сертификата; проверьте дату Windows и настройки сертификатов / прокси'
    elif isinstance(reason,socket.gaierror):detail='не удалось определить адрес сервера (DNS)'
    elif isinstance(reason,(TimeoutError,socket.timeout)):detail='истекло время ожидания'
    else:detail='сбой соединения ('+type(reason).__name__+')'
    code=getattr(reason,'winerror',None) or getattr(reason,'errno',None)
    if isinstance(code,int):detail+='; код '+str(code)
    return 'Не удалось подключиться к '+host+': '+detail+'. Текущая версия продолжает работать.'


def allowed_url(url):
    p=urlparse(url)
    return (p.scheme=='https' and not p.username and not p.password and p.port in (None,443)
            and (p.hostname in ('api.github.com','github.com')
                 or bool(p.hostname and p.hostname.endswith('.githubusercontent.com'))))


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed_url(newurl):
            raise ValueError('GitHub перенаправил загрузку на неподдерживаемый адрес.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def open_url(url,headers=None):
    if not allowed_url(url):raise ValueError('Недопустимый адрес обновления.')
    request=Request(url,headers={'User-Agent':'ContractPrintApp-Updater',
                                 'Accept':'application/vnd.github+json' if url==API else '*/*',
                                 **(headers or {})})
    return build_opener(GitHubRedirect()).open(request,timeout=20)


def read_json(url,limit,opener):
    try:
        with opener(url) as response:
            raw=response.read(limit+1)
        if len(raw)>limit:raise ValueError('Слишком большой ответ сервера обновлений.')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('Некорректный ответ сервера обновлений.')
        return value
    except HTTPError as e:
        if e.code in (403,429):raise ValueError('GitHub временно ограничил запросы. Повторите проверку позже; вход в аккаунт не требуется.') from e
        raise ValueError('Не удалось получить обновление с GitHub (HTTP '+str(e.code)+').') from e
    except (URLError,TimeoutError,OSError) as e:
        raise ValueError(connection_message(e,url)) from e


def asset_url(asset,tag):
    name=asset.get('name','')
    url=asset.get('browser_download_url','')
    expected='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'+name
    if not name or url!=expected or not allowed_url(url):
        raise ValueError('Некорректный адрес файла в релизе GitHub.')
    return url


def latest_update(current,opener=open_url):
    # Prefer ordinary public release downloads: some networks cannot reach
    # api.github.com even though github.com itself is available.
    try:return latest_update_without_api(current,opener)
    except ValueError as direct_error:
        if not isinstance(direct_error.__cause__,(HTTPError,URLError,TimeoutError,OSError)) and not isinstance(direct_error,json.JSONDecodeError):raise
        try:return latest_update_api(current,opener)
        except ValueError as api_error:
            raise ValueError('Проверка через GitHub и резервный API не удалась. '+str(direct_error)+' '+str(api_error)) from api_error


def latest_update_api(current,opener=open_url):
    release=read_json(API,1024*1024,opener)
    tag=release.get('tag_name','')
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag):raise ValueError('Некорректный номер релиза GitHub.')
    if release.get('draft') or release.get('prerelease'):return None
    if version_tuple(tag[1:])<=version_tuple(current):return None
    assets={a.get('name'):a for a in release.get('assets',[]) if isinstance(a,dict) and a.get('state')=='uploaded'}
    if MANIFEST not in assets:raise ValueError('В новом релизе ещё нет файла обновления. Повторите проверку позже.')
    info=read_json(asset_url(assets[MANIFEST],tag),65536,opener)
    if info.get('product')!='ContractPrintApp' or info.get('version')!=tag[1:]:
        raise ValueError('Обновление не соответствует приложению или версии релиза.')
    name=info.get('archive','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.zip',name) or name not in assets:
        raise ValueError('В релизе не найден ZIP обновления.')
    if not re.fullmatch(r'[a-fA-F0-9]{64}',info.get('sha256','')):
        raise ValueError('В релизе отсутствует контрольная сумма обновления.')
    asset=assets[name];size=asset.get('size')
    if not isinstance(size,int) or not 0<size<=MAX_ARCHIVE:
        raise ValueError('Недопустимый размер обновления.')
    api_digest=asset.get('digest')
    if api_digest and api_digest.lower()!='sha256:'+info['sha256'].lower():
        raise ValueError('Контрольные суммы GitHub и пакета не совпадают.')
    return {**info,'url':asset_url(asset,tag),'size':size}


def latest_update_without_api(current,opener=open_url):
    info=read_json(LATEST_MANIFEST,65536,opener)
    if info.get('product')!='ContractPrintApp':raise ValueError('Обновление предназначено для другого приложения.')
    version=info.get('version','')
    if version_tuple(version)<=version_tuple(current):return None
    name=info.get('archive','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.zip',name):raise ValueError('Некорректное имя пакета обновления.')
    if not re.fullmatch(r'[a-fA-F0-9]{64}',info.get('sha256','')):raise ValueError('В обновлении отсутствует SHA-256.')
    url='https://github.com/'+REPOSITORY+'/releases/download/v'+version+'/'+name
    size=info.get('size')
    if size is None:
        # Older releases did not put size in the manifest. Probe one byte;
        # never download an unbounded response just to learn the size.
        try:
            with opener(url,{'Range':'bytes=0-0'}) as response:
                if getattr(response,'status',200)==206:
                    m=re.fullmatch(r'bytes 0-0/(\d+)',response.headers.get('Content-Range',''))
                    if m:size=int(m[1])
                else:
                    length=response.headers.get('Content-Length','')
                    if length.isdigit():size=int(length)
        except (HTTPError,URLError,TimeoutError,OSError) as e:
            raise ValueError(connection_message(e,url)) from e
    if not isinstance(size,int) or not 0<size<=MAX_ARCHIVE:raise ValueError('Не удалось определить допустимый размер обновления.')
    return {**info,'url':url,'size':size}


def download_update(info,cache=None,opener=open_url,progress=None):
    """Retain interrupted .part files; verify SHA-256 before returning a path."""
    if info.get('product')!='ContractPrintApp':raise ValueError('Чужое приложение в пакете обновления.')
    checksum=info.get('sha256','').lower()
    if not re.fullmatch(r'[a-f0-9]{64}',checksum):raise ValueError('Некорректная контрольная сумма.')
    size=info.get('size')
    if not isinstance(size,int) or not 0<size<=MAX_ARCHIVE:raise ValueError('Некорректный размер обновления.')
    cache=Path(cache) if cache is not None else Path(tempfile.gettempdir())/'ContractPrintApp-downloads'
    cache.mkdir(parents=True,exist_ok=True)
    target=cache/(checksum+'.zip');partial=cache/(checksum+'.part')
    lock=InstallLock(cache/checksum,exclusive=True)
    try:lock.acquire()
    except OSError as e:raise ValueError('Это обновление уже скачивается другим экземпляром программы. Повторите позже.') from e
    try:
        if target.is_symlink() or partial.is_symlink():raise ValueError('Недопустимая ссылка в папке загрузок.')
        if target.exists():
            if target.stat().st_size==size and digest(target)==checksum:return target
            target.unlink()
        if partial.exists() and partial.stat().st_size>size:partial.unlink()
        offset=partial.stat().st_size if partial.exists() else 0
        if offset<size:
            try:
                with opener(info['url'],{'Range':'bytes='+str(offset)+'-'} if offset else {}) as response:
                    status=getattr(response,'status',200)
                    if status==206:
                        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                        if not match or int(match[1])!=offset or int(match[3])!=size or not offset<=int(match[2])<size:
                            raise ValueError('Сервер вернул некорректный диапазон загрузки.')
                    elif status==200:offset=0
                    else:raise ValueError('Сервер отклонил загрузку обновления.')
                    received=offset;started=time.monotonic()
                    with partial.open('ab' if offset else 'wb') as out:
                        while True:
                            chunk=response.read(1024*1024)
                            if not chunk:break
                            received+=len(chunk)
                            if received>size:
                                raise ValueError('Размер ответа больше заявленного размера обновления.')
                            out.write(chunk)
                            if progress:progress(received,size)
                            if time.monotonic()-started>600:
                                raise TimeoutError('Download time limit')
            except HTTPError as e:
                if e.code==416 and offset and partial.exists():
                    partial.unlink()
                raise ValueError('GitHub прервал загрузку. Повторите проверку обновлений.') from e
            except (URLError,TimeoutError,OSError) as e:
                raise ValueError('Загрузка прервалась. Повторите проверку обновлений — скачивание продолжится с сохранённого места.') from e
        if not partial.exists() or partial.stat().st_size!=size:
            raise ValueError('Обновление скачано не полностью. Повторите проверку для докачки.')
        if digest(partial)!=checksum:
            partial.unlink()
            raise ValueError('Контрольная сумма не совпала. Повторите проверку для новой загрузки.')
        partial.replace(target)
        return target
    finally:lock.close()
