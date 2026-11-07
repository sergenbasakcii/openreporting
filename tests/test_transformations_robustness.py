"""Transformations meet hand-edited or imported panels: bad options give a clear message, text cells never crash math."""

import pytest

from openreporting.frames import table_frame
from openreporting.transformations import TransformationError, apply_transformations


def _table():
    columns = [{"name": "host", "type": "string"}, {"name": "v", "type": "number"}, {"name": "w", "type": "number"}]
    return table_frame("T", columns, [["a", 1, 2], ["b", "n/a", 4], ["c", 3, None]], ref_id="B")


def _series():
    return [
        {"type": "timeseries", "name": "cpu a", "refId": "A", "labels": {"host": "a"}, "points": [[1000, 1.0], [2000, 3.0]], "unit": "percent"},
        {"type": "timeseries", "name": "cpu b", "refId": "A", "labels": {"host": "b"}, "points": [[1000, 5.0]], "unit": "percent"},
    ]


def test_binary_calculation_treats_text_cells_as_empty():
    out = apply_transformations([_table()], [{"id": "calculateField", "options": {"mode": "binary", "binary": {"left": "v", "operator": "+", "right": "w"}}}])
    assert [row[-1] for row in out[0]["rows"]] == [3, None, None]


def test_row_reduction_ignores_text_cells():
    out = apply_transformations([_table()], [{"id": "calculateField", "options": {"mode": "reduceRow", "reduce": {"reducer": "sum"}}}])
    assert [row[-1] for row in out[0]["rows"]] == [3, 4, 3]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"id": "calculateField", "options": {"mode": "binary", "binary": {"left": "host", "operator": "*", "right": "2"}}}, "sayı sütun"),
        ({"id": "calculateField", "options": {"mode": "reduceRow", "reduce": {"reducer": "bogus"}}}, "Bilinmeyen hesaplama"),
        ({"id": "reduceByLabel", "options": {"reducer": "bogus"}}, "Bilinmeyen hesaplama"),
        ({"id": "reduce", "options": {"mode": "reduceFields", "reducers": ["bogus"]}}, "Bilinmeyen hesaplama"),
        ({"id": "limit", "options": {"limitField": "abc"}}, "Satır sınırı"),
        ({"id": "sortBy", "options": {"sort": "nonsense"}}, "Sıralama"),
        ({"id": "reduce", "options": "string options"}, "seçenekleri geçersiz"),
        ({"id": "nonexistent"}, "Bilinmeyen dönüşüm"),
    ],
)
def test_invalid_options_raise_clear_turkish_message(entry, message):
    with pytest.raises(TransformationError, match=message):
        apply_transformations([_table()] + _series(), [entry])


def test_organize_ignores_non_integer_positions():
    entry = {"id": "organize", "options": {"indexByName": {"w": "first", "v": 0}, "renameByName": {"w": "W"}}}
    out = apply_transformations([_table()], [entry])
    assert [c["name"] for c in out[0]["columns"]] == ["v", "host", "W"]
