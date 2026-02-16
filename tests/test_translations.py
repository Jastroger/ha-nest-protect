"""Test translation files are valid and properly formatted."""

import json
from pathlib import Path

import pytest

TRANSLATION_FILES = [
    "custom_components/nest_protect/strings.json",
    "custom_components/nest_protect/translations/en.json",
    "custom_components/nest_protect/translations/de.json",
    "custom_components/nest_protect/translations/fr.json",
    "custom_components/nest_protect/translations/nl.json",
    "custom_components/nest_protect/translations/pt-BR.json",
]


@pytest.mark.parametrize("filepath", TRANSLATION_FILES)
def test_translation_files_are_valid_json(filepath):
    """Test that all translation files are valid JSON."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict)
    assert "config" in data


@pytest.mark.parametrize("filepath", TRANSLATION_FILES)
def test_wizard_login_javascript_braces_escaped(filepath):
    """Test that JavaScript code in wizard_login has properly escaped braces for ICU MessageFormat.

    Home Assistant uses ICU MessageFormat for translations, which interprets curly braces
    as placeholders. JavaScript code embedded in translations must escape braces by wrapping
    them in single quotes (e.g., '{' becomes ''{'' and '}' becomes ''}').

    This prevents translation errors like INVALID_TAG and MALFORMED_ARGUMENT.
    """
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    # Check if wizard_login step exists
    if "wizard_login" not in data.get("config", {}).get("step", {}):
        pytest.skip(f"No wizard_login step in {filepath}")

    wizard = data["config"]["step"]["wizard_login"]
    desc = wizard.get("description", "")

    # If there's JavaScript code, verify braces are escaped
    if "(async()=>" in desc:
        # The JavaScript should have escaped braces for ICU MessageFormat
        assert "async()=>'{'try'{'" in desc, (
            f"{filepath}: JavaScript braces must be escaped for ICU MessageFormat. "
            "Use '{{' instead of {{ and '}}' instead of }}"
        )

        # Verify no unescaped braces in the async function
        # (This is a simplified check - in reality, braces in strings are OK)
        assert "async()=>{try{" not in desc, (
            f"{filepath}: Found unescaped braces in JavaScript code. "
            "This will cause ICU MessageFormat errors."
        )


def test_wizard_description_renders_valid_javascript():
    """Test that the wizard description, when rendered by ICU MessageFormat, produces valid JavaScript.

    This test is now optional - if JavaScript is present, it should be valid.
    If not present, the test passes (as we recommend Network Header or Playwright wizard instead).
    """
    # Use English as reference
    with open("custom_components/nest_protect/strings.json", encoding="utf-8") as f:
        data = json.load(f)

    desc = data["config"]["step"]["wizard_login"]["description"]

    # Simulate ICU MessageFormat rendering: remove escape quotes
    rendered = desc.replace("'{'", "{").replace("'}'", "}")

    # Extract JavaScript code
    import re

    js_match = re.search(r"\(async\(\).*?\)\(\);", rendered, re.DOTALL)

    # JavaScript is now optional - if not present, test passes
    if not js_match:
        return

    js_code = js_match.group(0)

    # Basic validation: should start and end correctly
    assert js_code.startswith("(async()=>{"), "JavaScript should start with (async()=>{"
    assert js_code.endswith("})();"), "JavaScript should end with })();"
    assert "try{" in js_code, "JavaScript should have try block"
    assert "catch(" in js_code, "JavaScript should have catch block"
