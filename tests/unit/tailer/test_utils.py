import pytest
from datamover.tailer.utils import flush_buffer

# -- flush_buffer tests --


def test_flush_buffer_empty_input():
    # Empty input should return no lines and empty buffer
    lines, buf = flush_buffer(b"")
    assert lines == []
    assert buf == b""


@pytest.mark.parametrize(
    "data,expected_lines,expected_buf",
    [
        (b"partial data", [], b"partial data"),
        (b"one line\n", ["one line"], b""),  # strip() removes trailing whitespace
        (
            b"first\nsecond\nthird\n",
            ["first", "second", "third"],
            b"",
        ),  # strip() handles this
        (b"alpha\nbeta\nincomplete", ["alpha", "beta"], b"incomplete"),
        (
            b"line1\r\nline2\r\npartial",
            ["line1", "line2"],
            b"partial",
        ),  # strip() handles \r\n
        (
            b"A\nB\r\nC\nD incomplete",
            ["A", "B", "C"],
            b"D incomplete",
        ),  # strip() handles mixed
    ],
)
def test_flush_buffer_various(data, expected_lines, expected_buf):
    lines, buf = flush_buffer(data)
    assert lines == expected_lines
    assert buf == expected_buf


def test_flush_buffer_empty_lines_and_partial():
    # Two empty lines, then 'partial' as a complete line
    data = b"\n\npartial\n"
    lines, buf = flush_buffer(data)
    # strip() on an empty line results in ""
    assert lines == ["", "", "partial"]
    assert buf == b""


def test_flush_buffer_empty_trailing_newline():
    # Single newline only
    data = b"\n"
    lines, buf = flush_buffer(data)
    # strip() on "" results in ""
    assert lines == [""]
    assert buf == b""


def test_flush_buffer_invalid_utf8():
    # 0xff is invalid UTF-8; should be replaced
    data = b"\xff\nline2\npartial"
    lines, buf = flush_buffer(data)
    # The invalid byte decodes to the replacement character '�'
    assert lines[0] == "�"
    assert lines[1] == "line2"
    assert buf == b"partial"
