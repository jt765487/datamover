import pytest

from datamover.tailer.parse_csv_line import (
    parse_log_line,
    ParsedLine,
    LineParsingFormatError,
    LineParsingTimestampError,
    LineParsingPathError,
    LineParsingHashError,
    SHA256_HEX_LENGTH,
)

# helper constants
VALID_HASH = "a" * SHA256_HEX_LENGTH
MIXED_HASH = ("AbCd" * 16)[:SHA256_HEX_LENGTH]
NONHEX_HASH = "g" + "a" * (SHA256_HEX_LENGTH - 1)
SHORT_HASH = "a" * (SHA256_HEX_LENGTH - 1)
LONG_HASH = "a" * (SHA256_HEX_LENGTH + 1)


class TestParsedLineDataclass:
    def test_fields_and_immutability(self):
        p = ParsedLine(123, "/foo", VALID_HASH)
        assert p.timestamp == 123
        assert p.filepath == "/foo"
        assert p.sha256_hash == VALID_HASH
        with pytest.raises(AttributeError):
            p.timestamp = 5
        with pytest.raises(AttributeError):
            p.filepath = "/bar"
        with pytest.raises(AttributeError):
            p.sha256_hash = "x" * SHA256_HEX_LENGTH


class TestExceptionFormatting:
    @pytest.mark.parametrize(
        "exc_cls,msg,line,val,has_val",
        [
            (LineParsingFormatError, "fmt bad", "L", None, False),
            (LineParsingTimestampError, "ts bad", "L2", "v", True),
            (LineParsingPathError, "p bad", "L3", "", True),
            (LineParsingHashError, "h bad", "L4", "hv", True),
        ],
    )
    def test_exception_str_and_attrs(self, exc_cls, msg, line, val, has_val):
        if val is None:
            e = exc_cls(msg, line)
        else:
            e = exc_cls(msg, line, val)  # format and timestamp/h/hash all take (m,l,v)
        s = str(e)
        assert msg in s
        assert f"[Line: '{line}']" in s
        if has_val:
            assert f"[Value: '{val}']" in s
            assert e.value == val
        else:
            assert "[Value:" not in s
            assert e.value is None
        assert e.line == (line if line is not None else "None")


class TestParseLogLineHappyPaths:
    @pytest.mark.parametrize(
        "line,ts,fp,hs",
        [
            (f"0,/x,{VALID_HASH}", 0, "/x", VALID_HASH),
            (f"  42 , /some/path , {VALID_HASH}  ", 42, "/some/path", VALID_HASH),
            (f"123,relative/path,{VALID_HASH}", 123, "relative/path", VALID_HASH),
            (f"1,/unicøde/路径,{VALID_HASH}", 1, "/unicøde/路径", VALID_HASH),
            (f"999,/m,{MIXED_HASH}", 999, "/m", MIXED_HASH),
            (
                f"{10**18},/big/{MIXED_HASH[:4]},{MIXED_HASH}",
                10**18,
                "/big/" + MIXED_HASH[:4],
                MIXED_HASH,
            ),
            (f"5,/space in name ,{VALID_HASH}", 5, "/space in name", VALID_HASH),
            (f"7,/trailing/newline,{VALID_HASH}\n", 7, "/trailing/newline", VALID_HASH),
            (f"8,/tabs\tin\tpath,{VALID_HASH}", 8, "/tabs\tin\tpath", VALID_HASH),
        ],
    )
    def test_valid_lines(self, line, ts, fp, hs):
        parsed = parse_log_line(line)
        assert isinstance(parsed, ParsedLine)
        assert parsed.timestamp == ts
        assert parsed.filepath == fp
        assert parsed.sha256_hash == hs


class TestParseLogLineFormatErrors:
    @pytest.mark.parametrize(
        "line, count",
        [
            (None, None),
            ("", 0),
            ("   \t  ", 0),
            ("nocommas", 0),
            ("one,comma", 1),
            ("a,b,c,d", 3),
        ],
    )
    def test_bad_comma_counts(self, line, count):
        with pytest.raises(LineParsingFormatError) as ei:
            parse_log_line(line)
        msg = str(ei.value)

        if line is None:
            # None input
            assert "Input line cannot be None" in msg
            assert ei.value.line == "None"
        elif not (line and line.strip()):
            # empty or whitespace-only
            assert "Line is empty or whitespace only" in msg
            assert ei.value.line == line
        else:
            # non-empty but wrong number of commas
            assert "must contain exactly two commas" in msg
            assert f"(found {count})" in msg
            assert ei.value.line == line
        # FormatError never sets .value
        assert ei.value.value is None


class TestParseLogLineTimestampErrors:
    @pytest.mark.parametrize("ts_str", ["abc", "1.2", ""])
    def test_non_integer_timestamp(self, ts_str):
        line = f"{ts_str},/p,{VALID_HASH}"
        with pytest.raises(LineParsingTimestampError) as ei:
            parse_log_line(line)
        assert "not a valid integer" in str(ei.value)
        assert ei.value.value == ts_str

    def test_negative_timestamp(self):
        line = f"-5,/p,{VALID_HASH}"
        with pytest.raises(LineParsingTimestampError) as ei:
            parse_log_line(line)
        assert "cannot be negative" in str(ei.value)
        assert ei.value.value == "-5"


class TestParseLogLinePathErrors:
    @pytest.mark.parametrize("fp_str", ["", "   "])
    def test_empty_filepath(self, fp_str):
        line = f"10,{fp_str},{VALID_HASH}"
        with pytest.raises(LineParsingPathError) as ei:
            parse_log_line(line)
        assert "cannot be empty" in str(ei.value)
        assert ei.value.value == fp_str.strip()


class TestParseLogLineHashErrors:
    @pytest.mark.parametrize(
        "hs, msg_sub",
        [
            (SHORT_HASH, "incorrect length"),
            (LONG_HASH, "incorrect length"),
            (NONHEX_HASH, "invalid non-hex"),
        ],
    )
    def test_bad_hash(self, hs, msg_sub):
        line = f"20,/p,{hs}"
        with pytest.raises(LineParsingHashError) as ei:
            parse_log_line(line)
        m = str(ei.value)
        assert msg_sub in m
        assert ei.value.value == hs

    def test_empty_hash_field(self):
        line = "30,/p,"
        with pytest.raises(LineParsingHashError) as ei:
            parse_log_line(line)
        assert "incorrect length" in str(ei.value)
        assert ei.value.value == ""
