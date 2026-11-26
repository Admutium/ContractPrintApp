"""Synthetic execution-security extraction, money and one-page output."""
import tempfile,unittest
from pathlib import Path
from decimal import Decimal
import fitz
from payment_data import MODES,parse_payment_html,parse_bank,calculate,amount_words,validate
from payment_pdf import generate_payment


def row(k,v):return '<tr><td>'+k+'</td><td>'+v+'</td></tr>'
def heading(s):return '<tr><td><p class="caption"><b>'+s+'</b></p></td><td></td></tr>'
def bank(account='0',name='Получатель обеспечения'):
    return 'Получатель: '+name+' | ИНН: '+'0'*10+' | КПП: '+'0'*9+' | Расчётный счет: '+account*20+' | БИК: '+'0'*9+' | Наименование банка: АО Банк Пример | Корреспондентский счет: '+'0'*20

def demo_html(terms='5% от цены заключаемого контракта'):
    return ('<html><meta charset="utf-8"><div><p>2.2. Поставщик</p><table>'+row('Полное наименование','Полное демонстрационное наименование плательщика')+row('ИНН','0'*10)+row('КПП','0'*9)+row('Банковские реквизиты',bank())+'</table></div><table>'+heading('Обеспечение заявки')+row('Платежные реквизиты',bank('1','Получатель заявки'))+heading('Обеспечение исполнения контракта')+row('Размер обеспечения исполнения контракта',terms)+row('Платежные реквизиты',bank('2'))+heading('Обеспечение гарантийных обязательств')+row('Платежные реквизиты',bank('3','Получатель гарантии'))+'</table></html>').encode()


def valid_data():
    data={'number':'1','date':'01.01.2030','amount':'12345.67','purpose':'Обеспечение исполнения контракта DEMO; без НДС.'}
    for party in ('payer','recipient'):
        data.update({party+'_'+k:v for k,v in parse_bank(bank()).items() if k in ('name','inn','kpp','account','bank','bik','bank_account')})
    data['payer_name']='Общество с ограниченной ответственностью «Демонстрационная организация с полным наименованием»'
    return data


class PaymentTests(unittest.TestCase):
    def test_execution_requisites_exclude_bid_and_warranty(self):
        data=parse_payment_html(demo_html())
        self.assertEqual(data.recipient['account'],'2'*20)
        self.assertEqual(data.mode,MODES[2]);self.assertEqual(data.percent,'5')
        self.assertIn('Полное демонстрационное',data.payer['name'])
        self.assertEqual(set(data.payer),{'name'})

    def test_contract_uses_customer_and_tabular_sections_45_and_55(self):
        def section(heading_text, rows):
            return '<div><p>'+heading_text+'</p><table>'+''.join(
                '<tr>'+''.join('<td>'+cell+'</td>' for cell in row)+'</tr>' for row in rows
            )+'</table></div>'

        customer=section('2.1. Заказчик', [
            ['Полное наименование','Демонстрационное ЛПУ'], ['ИНН','1'*10], ['КПП','2'*9]
        ])
        terms=section('4.5. Обеспечение исполнения контракта', [
            ['Вид обеспечения','Размер обеспечения исполнения контракта в %','Размер обеспечения исполнения контракта'],
            ['1','2','3'], ['Обеспечение исполнения контракта','5,5','12345,67'],
            ['Обеспечение исполнения гарантийных обязательств','10','2222'],
        ])
        columns=['Наименование организации, ИНН, КПП','Тип счета','Номер лицевого счета',
                 'Номер банковского (казначейского) счета','Реквизиты банка, ТОФК','Наименование контрагента для п/п']
        account=['Демонстрационное ЛПУ','Лицевой счёт в ФК','ДЕМО123',
                 '3'*20,'Банк ПримерБИК: '+'4'*9+', к/с: '+'5'*20,'УФК (ЛПУ)']
        payment=section('5.5. Платежные реквизиты заказчика', [columns,list('123456'),account])
        unrelated=section('5.6. Реквизиты для оплаты', [columns,['Иной получатель',*account[1:3],'9'*20,*account[4:]]])
        source=parse_payment_html(('<meta charset="utf-8">'+customer+terms+payment+unrelated).encode())
        self.assertEqual(source.recipient,{'name':'Демонстрационное ЛПУ','inn':'1'*10,'kpp':'2'*9,
                                          'account':'3'*20,'bank':'Банк Пример','bik':'4'*9,'bank_account':'5'*20})
        self.assertEqual(source.extra,{'personal':'ДЕМО123','counterparty':'УФК (ЛПУ)','account_type':'Лицевой счёт в ФК'})
        self.assertEqual((source.mode,source.percent,source.amount),(MODES[0],'5.5','12345.67'))

    def test_nmck_fixed_ambiguous_and_no_requisites(self):
        self.assertEqual(parse_payment_html(demo_html('5% от НМЦК')).mode,MODES[1])
        self.assertEqual(parse_payment_html(demo_html('123 456,78 рублей')).amount,'123456.78')
        self.assertEqual(parse_payment_html(demo_html('5%')).mode,'')
        self.assertEqual(parse_payment_html(demo_html('5% от НМЦК или 5% от цены контракта')).mode,'')
        data=parse_payment_html(('<html><table>'+heading('Обеспечение заявки')+row('Платежные реквизиты',bank())+'</table></html>').encode())
        self.assertFalse(data.recipient)

    def test_quoted_notice_requisites_and_unknown_labels(self):
        value='"Номер расчётного счёта" '+'0'*20+' "Номер лицевого счёта" '+'0'*9+' "Код поступления" Информация отсутствует "БИК" '+'0'*9+' "Наименование кредитной организации" АО Банк Пример "Номер корреспондентского счета" '+'0'*20
        result=parse_bank(value)
        self.assertEqual(result['bik'],'0'*9);self.assertEqual(result['personal'],'0'*9)
        self.assertEqual(result['bank'],'АО Банк Пример')

    def test_all_four_modes_rounding_and_invalid_base(self):
        self.assertEqual(calculate(MODES[0],notice_amount='123,45'),Decimal('123.45'))
        self.assertEqual(calculate(MODES[1],percent='3',nmck='100.50'),Decimal('3.02'))
        self.assertEqual(calculate(MODES[2],percent='5',contract_total='100'),Decimal('5.00'))
        self.assertEqual(calculate(MODES[3],custom='25.12'),Decimal('25.12'))
        for kwargs in ({'mode':MODES[1],'percent':'101','nmck':'100'}, {'mode':MODES[2],'percent':'5'}, {'mode':MODES[3],'custom':'-1'}):
            with self.assertRaises(ValueError):calculate(**kwargs)

    def test_words_and_validation(self):
        self.assertEqual(amount_words('2001.02'),'Две тысячи один рубль 02 копейки')
        self.assertEqual(amount_words('0'),'Ноль рублей 00 копеек')
        self.assertEqual(validate(valid_data()),[])
        self.assertTrue(validate({}))

    def test_one_page_complete_names_and_draft(self):
        data=valid_data()
        data['subject']='Демонстрационный предмет контракта'
        with tempfile.TemporaryDirectory() as tmp:
            path=generate_payment(data,Path(tmp)/'payment.pdf')
            with fitz.open(path) as doc:
                text=doc[0].get_text()
                self.assertEqual(len(doc),1)
                for token in ('Демонстрационная','организация','наименованием','Платёжное поручение на обеспечение исполнения контракта','Предмет контракта',data['subject'],data['purpose']):
                    self.assertIn(token,' '.join(text.split()))
                for token in ('ЧЕРНОВИК','Подписи','Отметки банка','Поступ. в банк','Списано со сч.','М. П.','Внутренний документ для бухгалтерии'):
                    self.assertNotIn(token,text)
                self.assertTrue(all(doc[0].rect.contains(fitz.Rect(word[:4])) for word in doc[0].get_text('words')))
            data['purpose']=''
            generate_payment(data,path)
            with fitz.open(path) as doc:
                self.assertIn('Назначение платежа',doc[0].get_text())
                self.assertNotIn('без НДС',doc[0].get_text())
            generate_payment(data,path,draft=True)
            with fitz.open(path) as doc:self.assertIn('ЧЕРНОВИК',doc[0].get_text())
            data['payer_name']='Очень длинное название '*100
            with self.assertRaisesRegex(ValueError,'длинное поле'):generate_payment(data,path)
