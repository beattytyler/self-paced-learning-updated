"""Unit tests for token cost calculation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.user_service import UserService


class TestTokenCost(unittest.TestCase):
    def setUp(self):
        self.user_service = UserService()

    def test_minimum_token_cost(self):
        self.assertEqual(self.user_service.calculate_token_cost("a"), 1)

    def test_rounding_rules(self):
        self.assertEqual(self.user_service.calculate_token_cost("a" * 249), 1)
        self.assertEqual(self.user_service.calculate_token_cost("a" * 250), 1)
        self.assertEqual(self.user_service.calculate_token_cost("a" * 375), 2)
        self.assertEqual(self.user_service.calculate_token_cost("a" * 499), 2)
        self.assertEqual(self.user_service.calculate_token_cost("a" * 500), 2)
        self.assertEqual(self.user_service.calculate_token_cost("a" * 625), 3)


if __name__ == "__main__":
    unittest.main()
