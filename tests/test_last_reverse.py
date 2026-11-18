import tempfile
import unittest
from pathlib import Path
import fitz
from core import Contract,Item,Options
from pdf_export import generate
from preview import visible_pages,page_description


class LastReverseTests(unittest.TestCase):
    def test_single_and_multi_sheet_pdf_and_thumbnail_order(self):
        for count in (1,8,20):
            with self.subTest(items=count),tempfile.TemporaryDirectory() as tmp:
                c=Contract(number='DEMO',supplier='DEMO',customer='Пример',total=str(count*100),
                    items=[Item(no=str(i+1),name='Демонстрационная позиция',qty='1 шт',price='100',total='100',chars=['Характеристика: пример']*3) for i in range(count)])
                result=generate(c,Options(created_date='01.01.2032'),tmp)
                with fitz.open(result['fronts']) as fronts,fitz.open(result['back']) as back,fitz.open(result['duplex']) as pdf:
                    if count>1:self.assertGreaterEqual(len(fronts),2)
                    self.assertEqual(len(pdf),2*len(fronts))
                    self.assertEqual(len(back),1)
                    for i in range(len(fronts)):
                        self.assertEqual(pdf[2*i].get_text(),fronts[i].get_text())
                        if i<len(fronts)-1:self.assertEqual(pdf[2*i+1].get_text().strip(),'')
                    self.assertEqual(pdf[-1].get_text(),back[0].get_text())
                    self.assertIn('Оборот последнего листа',pdf[-1].get_text())
                    self.assertEqual(visible_pages(len(pdf)),list(range(0,len(pdf),2))+[len(pdf)-1])
                    self.assertIn('Карточка',page_description(len(pdf)-1,len(pdf)))
