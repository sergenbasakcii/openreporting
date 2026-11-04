"""Images used by reports: the report / smart dashboard logo and image elements."""

import logging

from . import logos

# Same logger name as before the split, so existing log filters keep matching.
log = logging.getLogger("openreporting.reporting.service")


def report_logo(settings, config):
    """PNG bytes of the report's customer logo, or None."""
    if not config.get("logo_id"):
        return None
    try:
        return logos.path(settings, config["logo_id"]).read_bytes()
    except logos.LogoError:
        # A missing logo is cosmetic: the report is still complete and may be delivered.
        log.warning("Report %s: logo %s unavailable, rendering without it", config.get("name"), config["logo_id"])
        return None


def _image_bytes(settings, logo_id):
    try:
        return logos.path(settings, logo_id).read_bytes()
    except logos.LogoError:
        return None


def panel_images(settings, dashboard):
    """Uploaded images referenced by image panels, keyed by logo id (missing ones are skipped)."""
    ids = {p.get("options", {}).get("logo_id") for p in dashboard.get("panels") or [] if p.get("type") == "image"}
    found = {i: _image_bytes(settings, i) for i in ids if isinstance(i, str)}
    return {i: data for i, data in found.items() if data}


def smart_logo(settings, dashboard):
    """Header/cover logo chosen in the smart dashboard editor (used when the report sets none)."""
    logo_id = (dashboard.get("smart") or {}).get("logo_id")
    return _image_bytes(settings, logo_id) if logo_id else None
