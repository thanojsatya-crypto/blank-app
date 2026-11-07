# Glossary expander icon follow-up

The overlapping icon-name text was a **real UI rendering defect**, not an artifact introduced by the saved screenshots. In the untouched app, the Streamlit glossary expander's icon span contains the `keyboard_arrow_right` ligature, while the page-wide typography selector in `ui_theme.py` assigns the ordinary interface font to Streamlit-generated elements. That overrides the Material Symbols font, so the ligature is displayed as literal text beside “Plain-language glossary.” The live baseline reproduced the same overlap as the reviewed captures.

This follow-up adds a narrowly scoped CSS rule for Material Symbols inside Streamlit expanders. The existing sidebar-control rule, glossary content, page behavior, protocol/API/message logic, and other reviewed files remain unchanged. The modification is in `ui_theme.py`; `tests/test_ui_theme.py` guards the expander font rule and the existing sidebar-specific rule.

Fresh Chromium captures at 1280 × 624 verify the corrected collapsed glossary in BB84, AOS, and OS-CSPRNG modes. An additional capture shows the expanded glossary. Browser verification confirmed the Material Symbols font is loaded and both the right-pointing collapsed chevron and down-pointing expanded chevron render correctly.

Verification in this copy: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` — **123 tests passed**. No protocol, API contract, message behavior, key-generation behavior, or firmware files were changed.

The reviewed source folder and reviewed ZIP are preserved unchanged; this is a separate follow-up copy and archive.