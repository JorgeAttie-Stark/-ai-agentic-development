import unittest

from ai_dev_lab.parity import is_even


class TestIsEven(unittest.TestCase):

    def test_returns_true_for_even_number(self):
        self.assertTrue(is_even(4))

    def test_returns_false_for_odd_number(self):
        self.assertFalse(is_even(7))

    def test_returns_true_for_zero(self):
        self.assertTrue(is_even(0))

    def test_handles_negative_numbers(self):
        self.assertTrue(is_even(-2))
        self.assertFalse(is_even(-3))

    def test_rejects_non_integer_values(self):
        for value in [2.5, 4.0, "4", None]:
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    is_even(value)

    def test_rejects_booleans(self):
        for value in [True, False]:
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    is_even(value)
