"""Profile comparison handles span layout whitespace without hiding lost content."""
import unittest
from check_share import identity_matches


class IdentityTests(unittest.TestCase):
    def test_exact_dom_text_matches_even_when_inner_text_omits_span_spaces(self):
        expected='合成演示 · 晴日慢慢'
        self.assertTrue(identity_matches('合成演示 · 晴日慢慢',expected))
        self.assertFalse(identity_matches('合成演示·晴日慢慢',expected))

    def test_name_characters_and_punctuation_are_preserved(self):
        expected='合成演示 · 晴日慢慢'
        for changed in ('合成演示 · 晴日慢', '合成演示 • 晴日慢慢', '合成演示 · 晴天慢慢'):
            self.assertFalse(identity_matches(changed,expected))


if __name__ == '__main__':
    unittest.main()
