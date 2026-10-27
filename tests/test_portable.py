import os

import pytest

from openreporting.portable import exclusive_local_lock, unicode_font_path


def test_worker_lock_refuses_second_owner_and_releases(tmp_path):
    path = tmp_path / "worker.lock"
    with exclusive_local_lock(path):
        assert path.exists()
        with pytest.raises(RuntimeError, match="already active"):
            with exclusive_local_lock(path):
                pass
    with exclusive_local_lock(path):
        pass


def test_worker_lock_releases_on_body_exception(tmp_path):
    path = tmp_path / "worker.lock"
    with pytest.raises(ValueError):
        with exclusive_local_lock(path):
            raise ValueError("intended failure")
    with exclusive_local_lock(path):
        pass


def test_font_override_fails_closed_when_not_ttf(tmp_path, monkeypatch):
    wrong = tmp_path / "font.txt"
    wrong.write_text("not a TTF", encoding="utf-8")
    monkeypatch.setenv("OPENREPORTING_PDF_FONT_FILE", str(wrong))
    with pytest.raises(RuntimeError, match="existing .ttf"):
        unicode_font_path()


def test_local_unicode_pdf_is_not_helvetica_fallback(monkeypatch):
    monkeypatch.delenv("OPENREPORTING_PDF_FONT_FILE", raising=False)
    # Windows has Arial/Segoe UI; Linux normally has DejaVu Sans. Do not
    # consider a missing font a successful fallback on either system.
    path = unicode_font_path()
    assert os.path.isfile(path)
    from io import BytesIO
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(TTFont("PortableCheck", path))
    out = BytesIO()
    page = canvas.Canvas(out)
    page.setFont("PortableCheck", 12)
    page.drawString(40, 800, "Ağ Performansı — Türkiye · Örnek %97")
    page.save()
    assert out.getvalue().startswith(b"%PDF-")

