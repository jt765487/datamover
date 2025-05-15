from dataclasses import dataclass
from typing import Optional, FrozenSet


class LineParsingError(ValueError):
    """Base class for errors encountered during log line parsing."""

    def __init__(self, message: str, line: str, value: Optional[str] = None):
        full_message: str = f"{message} [Line: '{line}']"
        if value is not None:
            full_message += f" [Value: '{value}']"
        super().__init__(full_message)
        self.line: str = line
        self.value: Optional[str] = value


class LineParsingFormatError(LineParsingError):
    """Error when line doesn't match expected comma-separated format."""

    def __init__(self, message: str, line: str):
        super().__init__(message, line)


class LineParsingTimestampError(LineParsingError):
    """Error related to timestamp validation."""

    def __init__(self, message: str, line: str, value: str):
        super().__init__(message, line, value)


class LineParsingPathError(LineParsingError):
    """Error related to path string validation (e.g., empty)."""

    # Message updated to reflect simpler validation scope within this function
    def __init__(self, message: str, line: str, value: Optional[str] = None):
        super().__init__(message, line, value)


class LineParsingHashError(LineParsingError):
    """Error related to hash validation."""

    def __init__(self, message: str, line: str, value: str):
        super().__init__(message, line, value)


# --- Dataclass  ---
@dataclass(frozen=True, slots=True)
class ParsedLine:
    """Represents a successfully parsed log line with immutable fields."""

    timestamp: int
    filepath: str
    sha256_hash: str


# --- Constants  ---
SHA256_HEX_LENGTH: int = 64
VALID_HEX_CHARS: FrozenSet[str] = frozenset("0123456789abcdefABCDEF")


def parse_log_line(line: Optional[str]) -> ParsedLine:
    """
    Parses/validates 'timestamp,filepath,sha256' format from a string line.

    Ensures the line contains exactly two commas, handles surrounding whitespace,
    and validates timestamp (int >= 0), filepath string (non-empty),
    and hash (64 hex chars).

    NOTE: Validation that the filepath string represents an *absolute* path
    must be performed by the caller using an appropriate FS abstraction method.

    Args:
        line: The raw input string line.

    Returns:
        A ParsedLine object (with filepath as str) if valid.

    Raises:
        LineParsingFormatError: If the line is None, empty/whitespace, or
                                does not contain exactly two comma separators.
        LineParsingTimestampError: If the timestamp part is not a valid non-negative integer.
        LineParsingPathError: If the filepath string is empty.
        LineParsingHashError: If the hash string has incorrect length or contains
                              non-hexadecimal characters.
    """
    if line is None:
        raise LineParsingFormatError(
            "Input line cannot be None", "None"
        )  # Pass "None" string for consistency

    stripped_line: str = line.strip()
    if not stripped_line:
        raise LineParsingFormatError("Line is empty or whitespace only", line)

    # --- Format Validation (Exactly 2 commas) ---
    comma_count: int = stripped_line.count(",")
    if comma_count != 2:
        raise LineParsingFormatError(
            f"Line must contain exactly two commas (found {comma_count})", line
        )

    # --- Splitting ---
    # Using Tuple unpacking for clarity after split/rsplit
    parts: list[str] = stripped_line.split(",", 1)
    timestamp_str_unstripped: str = parts[0]
    rest_of_line: str = parts[1]

    parts = rest_of_line.rsplit(",", 1)
    filepath_str_unstripped: str = parts[0]
    hash_str_unstripped: str = parts[1]

    # Strip whitespace from the separated parts
    timestamp_str: str = timestamp_str_unstripped.strip()
    filepath_str: str = filepath_str_unstripped.strip()
    hash_str: str = hash_str_unstripped.strip()

    # --- Field Validation ---

    # 1. Validate Timestamp
    timestamp: int
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise LineParsingTimestampError(
            "Timestamp is not a valid integer", line, timestamp_str
        ) from None

    if timestamp < 0:
        raise LineParsingTimestampError(
            "Timestamp cannot be negative", line, timestamp_str
        )

    # 2. Validate File Path String (basic non-empty check only)
    if not filepath_str:
        # Pass the (empty) filepath_str as the value
        raise LineParsingPathError(
            "File path string cannot be empty", line, value=filepath_str
        )
    # Absolute path validation is deferred to the caller using FS abstraction

    # 3. Validate SHA256 Hash
    if len(hash_str) != SHA256_HEX_LENGTH:
        raise LineParsingHashError(
            f"SHA256 hash has incorrect length ({len(hash_str)} != {SHA256_HEX_LENGTH})",
            line,
            hash_str,
        )
    # Use set difference for potentially slightly faster check on average? Or stick with all()
    # if not set(hash_str).issubset(VALID_HEX_CHARS):
    if not all(
        c in VALID_HEX_CHARS for c in hash_str
    ):  # Keep all() as it's perfectly clear
        raise LineParsingHashError(
            "SHA256 hash contains invalid non-hex characters", line, hash_str
        )

    # --- Success ---
    # Return the ParsedLine object with filepath as a string.
    return ParsedLine(timestamp=timestamp, filepath=filepath_str, sha256_hash=hash_str)
