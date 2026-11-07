from __future__ import annotations

import unittest

from ui_theme import _THEME_CSS


class UiThemeIconRegressionTests(unittest.TestCase):
    def test_expander_icon_font_is_restored_without_changing_other_icon_rules(self):
        self.assertIn(
            '[data-testid="stExpander"] [data-testid="stIconMaterial"]',
            _THEME_CSS,
        )
        self.assertIn('font-family: "Material Symbols Rounded" !important;', _THEME_CSS)
        self.assertIn('button[data-testid="stBaseButton-headerNoPadding"]', _THEME_CSS)
        self.assertIn('[data-testid="stTextInput"] button [data-testid="stIconMaterial"]', _THEME_CSS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
