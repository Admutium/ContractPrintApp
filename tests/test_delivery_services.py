"""Synthetic service terms; no customer documents or identifying details."""
import unittest
from delivery import find_delivery


class ServiceDeliveryTests(unittest.TestCase):
    def test_recurring_service_keeps_frequency_and_deadline(self):
        text='2.3. Срок оказания услуг — один раз в 4 месяца с момента заключения контракта по 15 мая 2032 года.'
        r=find_delivery([text])
        self.assertEqual(len(r.main),1)
        self.assertEqual(r.main[0].value,'Один раз в 4 месяца с момента заключения контракта по 15 мая 2032 года.')
        self.assertEqual(r.main[0].location,'Пункт 2.3')
        self.assertFalse(r.request)

    def test_duplicate_appendix_and_reporting_are_separate(self):
        r=find_delivery([
            '2.3. Срок оказания услуг: один раз в 4 месяца с момента заключения контракта по 15 мая 2032 года.',
            '4.1.Отчётным периодом по контракту является оказание услуг раз в полгода.',
            '5. Сроки оказания услуг: один раз в 4 месяца с момента заключения контракта по 15 мая 2032 г.',
        ])
        self.assertEqual(len(r.main),1)
        self.assertTrue(any('Пункт 4.1' in w and 'отчётности' in w for w in r.warnings))

    def test_payment_warranty_and_contract_validity_do_not_supply_term(self):
        r=find_delivery([
            'Срок действия контракта с даты заключения по 20 декабря 2032 года.',
            'Оплата услуг осуществляется в течение 7 рабочих дней.',
            'Гарантия на оказание услуг предоставляется в течение 30 дней.',
            'Отчётным периодом является оказание услуг раз в полгода.',
            'При выявлении завышения стоимости оказания услуг возврат денег производится в течение 9 дней.',
        ])
        self.assertFalse(r.main)

    def test_complete_term_not_joined_to_next_clause(self):
        r=find_delivery(['2.3. Срок оказания услуг: ежемесячно по 15.05.2032.',
                         '2.4. Место оказания услуг: помещение заказчика.'])
        self.assertEqual(len(r.main),1)
        self.assertNotIn('2.4',r.main[0].value)

    def test_adjacent_service_label_and_period(self):
        r=find_delivery(['Срок оказания услуг:','С 01.02.2032 по 15.05.2032 включительно.'])
        self.assertEqual(r.main[0].value,'С 01.02.2032 по 15.05.2032 включительно')

    def test_existing_goods_and_request_terms(self):
        r=find_delivery([
            'Поставка товара в течение 10 рабочих дней с даты заключения контракта.',
            'Поставка товара в течение 5 рабочих дней с даты получения заявки.',
        ])
        self.assertEqual(len(r.main),1);self.assertEqual(len(r.request),1)
        self.assertIn('10 рабочих дней',r.main[0].value)
        self.assertIn('5 рабочих дней',r.request[0].value)

    def test_invalid_periodic_date_is_not_offered(self):
        r=find_delivery(['Срок оказания услуг: ежемесячно по 31.02.2032.'])
        self.assertFalse(r.main)
        self.assertTrue(any('некорректная дата' in w for w in r.warnings))

    def test_recurring_work_is_not_changed_into_single_deadline(self):
        r=find_delivery(['Срок выполнения работ: ежеквартально с даты подписания контракта по 15.05.2032 включительно.'])
        self.assertEqual(len(r.main),1)
        self.assertIn('Ежеквартально',r.main[0].value)
        self.assertIn('включительно',r.main[0].value)
