"""Curated UI themes. The visual tokens live in static/app/themes.css; ids must match static/app/themes.js
(tests/test_themes.mjs checks all three agree)."""

THEME_IDS = ("aurora", "porcelain", "graphite", "dune", "contrast")
SYSTEM = "system"
DEFAULT_PREFERENCE = SYSTEM
# Values stored before the theme system (schema < 8 era): kept readable forever.
LEGACY = {"dark": "aurora", "light": "porcelain"}


def normalise(value):
    """Return a valid preference for a stored or submitted value; None when the value is not a theme."""
    value = LEGACY.get(value, value)
    return value if value == SYSTEM or value in THEME_IDS else None
