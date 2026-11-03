from openreporting.reporting.extended_pdf import histogram, quantile, numeric
from io import BytesIO
from types import SimpleNamespace

import pytest
from reportlab.pdfgen.canvas import Canvas
from openreporting.frames import table_frame
from openreporting.reporting.extended_pdf import draw


def test_histogram_counts_all_finite_samples_including_upper_edge():
    edges, counts = histogram([0, 1, 2, 3, 4, None, float("nan")], 2)
    assert edges == [0, 2, 4]
    assert counts == [2, 3]


def test_histogram_constant_values_remain_in_one_bin():
    _, counts = histogram([7, 7, 7], 10)
    assert counts == [3] + [0] * 9


def test_quartiles_interpolate_without_inventing_missing_samples():
    assert quantile([1, 3, 5, 7], 0.25) == 2.5
    assert quantile([1, 3, 5, 7], 0.5) == 4
    assert not numeric(None)
    assert not numeric(True)


@pytest.mark.parametrize("kind", ["histogram", "scatter", "bubble", "boxplot", "candlestick"])
def test_real_vector_commands_are_emitted_for_valid_table(kind):
    class Recorder(Canvas):
        marks = 0

        def rect(self, *args, **kwargs):
            self.marks += 1
            return super().rect(*args, **kwargs)

        def circle(self, *args, **kwargs):
            self.marks += 1
            return super().circle(*args, **kwargs)

    output = BytesIO()
    canvas = Recorder(output)
    messages = []
    pdf = SimpleNamespace(c=canvas, text=lambda x, y, value, *a, **kw: messages.append(str(value)))
    frame = table_frame(
        "Test",
        [{"name": "label", "type": "string"}, *[{"name": name, "type": "number"} for name in ("open", "close", "low", "high")]],
        [["A", 10, 12, 8, 15], ["B", 12, 9, 7, 16]],
    )
    assert draw(pdf, {"type": kind}, [frame], 20, 20, 500, 250)
    assert canvas.marks > 0
    assert not any("gerekir" in text or "Veri yok" in text for text in messages)
    canvas.save()
    assert output.getvalue().startswith(b"%PDF")
