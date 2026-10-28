import unittest
from core import vat_amount,vat_summary,Item
from decimal import Decimal
class VatTests(unittest.TestCase):
    def test_vat_included(self):
        self.assertEqual(vat_amount('110','10%'),Decimal('10.00'))
        self.assertEqual(vat_amount('122','22%'),Decimal('22.00'))
    def test_without_vat(self):
        self.assertIsNone(vat_amount('100','Без НДС'))
        self.assertIsNone(vat_amount('','10%'))
    def test_total(self):
        self.assertEqual(vat_summary([Item(total='110',vat='10%'),Item(total='122',vat='22%')]),(Decimal('32.00'),2))
if __name__=='__main__':unittest.main()
