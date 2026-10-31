from io import BytesIO
from types import SimpleNamespace

import pytest
from reportlab.pdfgen.canvas import Canvas

from openreporting.frames import table_frame
from openreporting.reporting.categorical_pdf import draw, proportional_widths, waterfall_steps


def test_signed_waterfall_crosses_zero_without_replacing_values():
    assert waterfall_steps([10,-20,4]) == [(0,10),(10,-10),(-10,-6)]


def test_treemap_area_is_proportional_and_preserves_zero():
    widths = proportional_widths([0,1,3],100)
    assert widths == [0,25,75]
    assert sum(widths) == 100


@pytest.mark.parametrize("kind", ["waterfall","funnel","treemap","rosepie","sunburst","parallel"])
def test_real_vector_paths_with_actual_table_values(kind):
    class Recorder(Canvas):
        marks = 0
        def rect(self,*args,**kwargs):
            self.marks += 1
            return super().rect(*args,**kwargs)
        def drawPath(self,*args,**kwargs):
            self.marks += 1
            return super().drawPath(*args,**kwargs)
        def wedge(self,*args,**kwargs):
            self.marks += 1
            return super().wedge(*args,**kwargs)
    output = BytesIO()
    canvas = Recorder(output)
    messages = []
    pdf = SimpleNamespace(c=canvas,text=lambda x,y,value,*a,**kw: messages.append(str(value)))
    frame = table_frame("Test",[{"name":"name","type":"string"},{"name":"a","type":"number"},{"name":"b","type":"number"}],[["A",2,4],["B",3,6]])
    assert draw(pdf,{"type":kind},[frame],20,20,500,250)
    assert canvas.marks > 0
    assert not any("gerekir" in message or "Veri yok" in message for message in messages)
    canvas.save()
    assert output.getvalue().startswith(b"%PDF")


def test_negative_funnel_is_explained_instead_of_discarded():
    canvas = Canvas(BytesIO())
    messages = []
    pdf = SimpleNamespace(c=canvas,text=lambda x,y,value,*a,**kw: messages.append(str(value)))
    frame = table_frame("Test",[{"name":"value","type":"number"}], [[-2]])
    assert draw(pdf,{"type":"funnel"},[frame],20,20,500,250)
    assert any("negatif" in message for message in messages)
