"""Small release checks using synthetic values only."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import fitz
import app_paths
from core import FIRMS, Contract, Item, Options, parse
from features import Features, VERSION
from pdf_export import generate
from updater import read_update


def demo_html():
    inn='0'*10
    rows=''.join('<td>'+v+'</td>' for v in ('1','Демонстрационная позиция','Товар','','1 шт','100','Без НДС','','100'))
    return f'''<html><meta charset="utf-8"><table>
    <tr><td>Номер контракта</td><td>DEMO</td></tr></table>
    <div class="block"><p class="block_title">2.2. Поставщик</p><table>
    <tr><td>ИНН</td><td>{inn}</td></tr><tr><td>Полное наименование</td><td>Демонстрационная организация</td></tr>
    </table></div><div class="sub-block"><p class="sub-block_title">3.1. Объект закупки</p>
    <table><tr>{rows}</tr></table></div></html>'''.encode()


class AppVariantTests(unittest.TestCase):
    def test_icon_assets(self):
        from PIL import Image
        from branding import ASSETS
        with Image.open(ASSETS/'ContractPrintApp.ico') as icon:
            self.assertTrue({(16,16),(32,32),(48,48),(256,256)} <= icon.ico.sizes())
        with Image.open(ASSETS/'ContractPrintApp.png') as icon:
            self.assertEqual(icon.mode,'RGBA')
            self.assertEqual(icon.getpixel((0,0))[3],0)

    def test_empty_directory_and_version(self):
        self.assertEqual(FIRMS,{})
        self.assertEqual(VERSION,'1.11.1')
        app=SimpleNamespace(settings={})
        Features.init_features(app)
        self.assertEqual(app.firms,{})

    def test_only_user_directory_enables_recognition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.html';path.write_bytes(demo_html())
            self.assertEqual(parse(path).supplier,'')
            self.assertEqual(parse(path,{'0'*10:('DEMO','Демонстрационная организация')}).supplier,'DEMO')

    def test_local_directory_survives_reload_and_can_be_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            value={'firm_directory':[{'inn':'0'*10,'code':'DEMO','name':'Демонстрационная организация'}]}
            path.write_text(json.dumps(value),encoding='utf-8')
            app=SimpleNamespace(settings=json.loads(path.read_text(encoding='utf-8')))
            Features.init_features(app)
            self.assertEqual(app.firms['0'*10][0],'DEMO')
            app.settings={'firm_directory':[]};Features.init_features(app)
            self.assertEqual(app.firms,{})

    def test_settings_stay_beside_app_executable(self):
        with patch.object(app_paths.sys,'frozen',True,create=True),patch.object(app_paths.sys,'executable',str(Path.cwd()/'demo-App'/'ContractPrintApp.exe')):
            self.assertEqual(app_paths.settings_path(),Path.cwd()/'demo-App'/'user-data'/'settings.json')

    def test_other_product_update_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'update-ContractPrintApp.json'
            path.write_text(json.dumps({'product':'OtherApplication','version':'9.0.0'}))
            with self.assertRaisesRegex(ValueError,'другого приложения'):
                read_update(tmp,VERSION)

    def test_demo_pdf_generated(self):
        c=Contract(number='DEMO',supplier='DEMO',customer='Пример',total='100',
                   items=[Item(no='1',name='Демонстрационная позиция',qty='1 шт',price='100',total='100')])
        with tempfile.TemporaryDirectory() as tmp:
            output=generate(c,Options(),tmp)
            with fitz.open(output['duplex']) as pdf:
                self.assertEqual(len(pdf),2)
                self.assertIn('DEMO',pdf[0].get_text())
