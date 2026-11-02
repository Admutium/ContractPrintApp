"""Synthetic EIS layouts; never include customer-provided HTML."""
from decimal import Decimal
import unittest
from core import Contract,Item
from eis import parse_notice
from quantity_check import compare

NUMBER='0'*19
CODE='00.00.00.000'


def form(customers,second=None):
    def item(name,rows):
        quantity=''.join('<tr><td>'+customer+'</td><td>'+amount+'</td></tr>' for customer,amount in rows)
        return '<tr><td>'+name+'<br>Идентификатор: DEMO</td><td>'+CODE+'</td><td>Штука</td><td><table>'+quantity+'</table></td></tr>'
    head='<tr><th>Наименование товара, работы, услуги</th><th>Код позиции</th><th>Единица измерения</th><th><table><tr><th>Заказчик</th><th>Количество (объем работы, услуги)</th></tr></table></th></tr>'
    data=item('Демонстрационная услуга',customers)
    if second:data+=item('Другая демонстрационная услуга',second)
    return ('<html><meta charset="utf-8"><h1>Извещение № '+NUMBER+'</h1><table><tr><td>Начальная (максимальная) цена контракта</td><td>100</td></tr></table><table>'+head+data+'</table></html>').encode()


class CustomerQuantityTests(unittest.TestCase):
    def test_single_customer_quantity_and_increase(self):
        n=parse_notice(form([('Пример заказчика','1')]),NUMBER)
        self.assertFalse(n.item_issues)
        self.assertEqual(len(n.items),1)
        self.assertEqual(n.items[0].name,'Демонстрационная услуга')
        c=Contract(notice=NUMBER,items=[Item(name='Демонстрационная услуга',code=CODE,qty='2 шт',price='100')])
        r=compare(c,n)
        self.assertEqual(r.status,'Есть изменения')
        self.assertEqual((r.delta,r.percent),(Decimal(100),Decimal(100)))

    def test_several_customers_are_not_summed(self):
        n=parse_notice(form([('Пример заказчика А','1'),('Пример заказчика Б','2')]),NUMBER)
        self.assertFalse(n.items)
        self.assertTrue(any('нескольким заказчикам' in x for x in n.item_issues))

    def test_different_customers_in_different_positions_are_flagged(self):
        n=parse_notice(form([('Пример заказчика А','1')],[('Пример заказчика Б','2')]),NUMBER)
        self.assertTrue(any('разные заказчики' in x for x in n.item_issues))

    def test_undefined_or_total_row_does_not_supply_quantity(self):
        for rows in ([('Пример заказчика','не определено')],[('Итого','3')]):
            with self.subTest(rows=rows):
                n=parse_notice(form(rows),NUMBER)
                self.assertFalse(n.items);self.assertTrue(n.item_issues)

    def test_notice_mismatch_stays_rejected(self):
        with self.assertRaisesRegex(ValueError,'не совпадает'):
            parse_notice(form([('Пример заказчика','1')]),'1'*19)
