"""Business checks do not depend on request timing or telemetry backends."""
import copy
import unittest
from basket import BasketValidationError, DEFAULT_BASKET, STOCK, evaluate_basket, stock_key


class BasketTests(unittest.TestCase):
    def evaluate(self, lines, per_line=False):
        fetches, reused = [], []
        def fetch(line, scope):
            fetches.append((line['line_id'], stock_key(line), scope))
            return STOCK.get(stock_key(line), 0)
        result = evaluate_basket(lines, per_line, fetch, lambda line, scope: reused.append(line['line_id']))
        return result, fetches, reused

    def test_six_lines_have_identical_business_result_with_one_or_six_lookups(self):
        baseline, fetched, reused = self.evaluate(DEFAULT_BASKET)
        fault, repeated, unused = self.evaluate(DEFAULT_BASKET, True)
        self.assertEqual(baseline, fault)
        self.assertEqual(baseline['outcome'], 'accepted')
        self.assertEqual(baseline['items'][0]['required_quantity'], 6)
        self.assertEqual((len(fetched), len(reused), len(repeated), len(unused)), (1, 5, 6, 0))

    def test_demand_aggregates_before_checking_stock(self):
        lines = [{**line, 'quantity': 4} for line in DEFAULT_BASKET]
        for per_line in (False, True):
            result, _, _ = self.evaluate(lines, per_line)
            self.assertEqual(result['outcome'], 'out_of_stock')
            self.assertEqual(result['items'][0]['required_quantity'], 24)
            self.assertEqual(result['items'][0]['available_quantity'], 20)

    def test_sku_warehouse_and_variant_each_partition_lookup_reuse(self):
        lines = [dict(line_id=f'line-{i}', sku=key[0], warehouse=key[1], variant=key[2], quantity=1)
                 for i, key in enumerate(STOCK)]
        lines += [{**lines[0], 'line_id': 'repeat'}]
        result, fetched, reused = self.evaluate(lines)
        self.assertEqual(len(fetched), 4)
        self.assertEqual(reused, ['repeat'])
        self.assertEqual({stock_key(item): item['available_quantity'] for item in result['items']}, STOCK)
        self.assertEqual(self.evaluate(lines, True)[0], result)

    def test_lookup_reuse_cannot_escape_one_request(self):
        for _ in range(2):
            self.assertEqual(len(self.evaluate(DEFAULT_BASKET)[1]), 1)

    def test_invalid_quantities_and_duplicate_line_ids_fail_before_fetch(self):
        invalid = [[], None, [{**DEFAULT_BASKET[0], 'quantity': 0}],
                   [{**DEFAULT_BASKET[0], 'quantity': True}],
                   [DEFAULT_BASKET[0], DEFAULT_BASKET[0]]]
        for lines in invalid:
            with self.subTest(lines=lines), self.assertRaises(BasketValidationError):
                evaluate_basket(lines, False, lambda *_: self.fail('unexpected lookup'), lambda *_: None)

    def test_failure_stops_after_first_attempt(self):
        for error in (TimeoutError('deadline'), RuntimeError('HTTP 500')):
            attempts = []
            def failed(line, scope):
                attempts.append(line['line_id'])
                raise error
            with self.assertRaises(type(error)):
                evaluate_basket(DEFAULT_BASKET, True, failed, lambda *_: None)
            self.assertEqual(attempts, ['line-1'])

    def test_input_is_unchanged(self):
        original = copy.deepcopy(DEFAULT_BASKET)
        self.evaluate(DEFAULT_BASKET)
        self.assertEqual(DEFAULT_BASKET, original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
