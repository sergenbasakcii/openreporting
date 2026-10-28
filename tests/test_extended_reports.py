"""Every new plugin survives storage and all three export formats."""
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import load_workbook

from openreporting.dashboards import EXTRA_PANEL_TYPES, normalize
from openreporting.frames import ts_frame
from openreporting.reporting.collect import Collected, Section, PanelResult
from openreporting.reporting.pdf import Pdf, render_pdf
from openreporting.reporting.excel import render_xlsx, render_csv


def test_new_visualizations_are_preserved_and_exportable(monkeypatch):
    kinds = sorted(EXTRA_PANEL_TYPES)
    assert len(kinds) == 20
    model = normalize({"title":"Extended panels", "panels":[
        {"id":i,"title":kind,"type":kind,"gridPos":{"x":0,"y":i*8,"w":24,"h":8}} for i,kind in enumerate(kinds,1)]})
    assert [p["type"] for p in model["panels"]] == kinds
    end = datetime.now(timezone.utc)
    points = [[int((end-timedelta(minutes=i)).timestamp()*1000), float(i)] for i in range(10,0,-1)]
    results = [PanelResult(p,p["title"],[ts_frame("Test", points)]) for p in model["panels"]]
    collected = Collected(model,{},[Section("Test",{},results)],end-timedelta(hours=1),end,"UTC")
    text = []
    original = Pdf.text
    def capture(self,x,y,value,*args,**kwargs):
        text.append(str(value))
        return original(self,x,y,value,*args,**kwargs)
    monkeypatch.setattr(Pdf,"text",capture)
    config = {"layout":"flow","cover":False,"toc":False}
    pdf = render_pdf(config, collected, "Extended report")
    assert pdf.startswith(b"%PDF")
    assert not any("Çizim hatası" in value for value in text)
    assert any("tablo görünümü" in value for value in text)
    book = load_workbook(BytesIO(render_xlsx(config, collected, "Extended report")))
    assert len(book.sheetnames) == 21
    csv_text = render_csv(config, collected, "Extended report").decode("utf-8-sig")
    for kind in kinds:
        assert kind in csv_text
