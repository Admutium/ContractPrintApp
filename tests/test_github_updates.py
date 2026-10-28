import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from github_updates import API, REPOSITORY, MANIFEST, latest_update, download_update, allowed_url


class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None):
        super().__init__(data);self.status=status;self.headers=headers or {}


class GitHubUpdateTests(unittest.TestCase):
    def info(self,data=b'demo payload'):
        return {'product':'ContractPrintApp','version':'1.12.0','archive':'App-update.zip',
                'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),
                'url':'https://github.com/'+REPOSITORY+'/releases/download/v1.12.0/App-update.zip'}

    def test_public_release_metadata_and_digest(self):
        info=self.info();base='https://github.com/'+REPOSITORY+'/releases/download/v1.12.0/'
        release={'tag_name':'v1.12.0','assets':[
            {'name':MANIFEST,'state':'uploaded','browser_download_url':base+MANIFEST},
            {'name':info['archive'],'state':'uploaded','browser_download_url':info['url'],
             'size':info['size'],'digest':'sha256:'+info['sha256']}]}
        calls=[]
        def opener(url):
            calls.append(url)
            return Response(json.dumps(release if url==API else info).encode())
        self.assertEqual(latest_update('1.11.1',opener)['sha256'],info['sha256'])
        self.assertEqual(len(calls),2)
        calls.clear();self.assertIsNone(latest_update('1.12.0',opener));self.assertEqual(calls,[API])
        release['assets'][1]['digest']='sha256:'+'0'*64
        with self.assertRaisesRegex(ValueError,'суммы'):latest_update('1.11.1',opener)

    def test_resume_partial_download(self):
        data=b'demonstration payload';info=self.info(data)
        with tempfile.TemporaryDirectory() as tmp:
            partial=Path(tmp)/(info['sha256']+'.part');partial.write_bytes(data[:5])
            def opener(url,headers):
                self.assertEqual(headers,{'Range':'bytes=5-'})
                return Response(data[5:],206,{'Content-Range':f'bytes 5-{len(data)-1}/{len(data)}'})
            result=download_update(info,tmp,opener)
            self.assertEqual(result.read_bytes(),data);self.assertFalse(partial.exists())

    def test_server_ignoring_range_restarts_download(self):
        data=b'demo payload';info=self.info(data)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/(info['sha256']+'.part')).write_bytes(b'old')
            result=download_update(info,tmp,lambda url,headers:Response(data))
            self.assertEqual(result.read_bytes(),data)

    def test_interrupted_download_is_retained_for_resume(self):
        data=b'demo payload';info=self.info(data)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'не полностью'):
                download_update(info,tmp,lambda url,headers:Response(data[:4]))
            self.assertEqual((Path(tmp)/(info['sha256']+'.part')).read_bytes(),data[:4])
            with self.assertRaisesRegex(ValueError,'сумма'):
                download_update(info,tmp,lambda url,headers:Response(b'X'*len(data)))
            self.assertFalse((Path(tmp)/(info['sha256']+'.part')).exists())

    def test_redirect_allowlist(self):
        self.assertTrue(allowed_url('https://release-assets.githubusercontent.com/file'))
        for url in ('http://github.com/file','https://github.com.evil.invalid/a','https://user:pass@github.com/a','file:///tmp/a'):
            self.assertFalse(allowed_url(url))
