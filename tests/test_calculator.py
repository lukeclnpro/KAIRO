import unittest

from local_ia.tools.calculator import calculate, use


class CalculatorTest(unittest.TestCase):
    def test_arithmetic_precedence_and_parentheses(self):
        self.assertEqual(calculate("2 + 3 * (4 - 1)"), 11)

    def test_power_decimal_comma_and_calculator_symbols(self):
        self.assertEqual(calculate("2^3 + 1,5 × 2"), 11.0)

    def test_math_functions_and_constants(self):
        self.assertAlmostEqual(calculate("sqrt(81) + sin(pi / 2)"), 10)

    def test_result_is_returned_as_tool_payload(self):
        self.assertEqual(use("144 / 12"), {"expression": "144 / 12", "result": 12.0})

    def test_rejects_arbitrary_python(self):
        for expression in ("__import__('os').system('echo unsafe')", "open('secret.txt')", "2 < 3"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                calculate(expression)

    def test_rejects_zero_division_and_excessive_exponents(self):
        for expression in ("5 / 0", "2 ** 5000"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                calculate(expression)


if __name__ == "__main__":
    unittest.main()