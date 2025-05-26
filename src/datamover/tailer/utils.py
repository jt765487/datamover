def flush_buffer(buffer: bytes) -> tuple[list[str], bytes]:
    """
    Given a bytes buffer, extract all complete lines ending with b'\n'.

    Lines are decoded using UTF-8 with error replacement. Leading/trailing
    whitespace (including CR/LF) is removed from the decoded lines.

    Args:
        buffer: The input byte buffer, potentially containing partial lines.

    Returns:
        A tuple containing:
            - A list of complete, decoded, stripped lines (List[str]).
            - The remaining bytes in the buffer after the last newline (bytes).
    """
    lines: list[str] = []
    current_pos: int = 0

    while True:
        # Find the index of the first newline character from the current position
        newline_index: int = buffer.find(b"\n", current_pos)

        if newline_index < 0:
            # No more newline characters found from current_pos to the end
            break

        # Extract the line including the newline character
        # Slice is from current_pos up to and including the newline
        line_bytes: bytes = buffer[current_pos : newline_index + 1]

        # Decode the line using UTF-8, replacing errors, and strip whitespace/newlines
        # The .strip() handles removal of leading/trailing whitespace, including \r if \r\n was used.
        decoded_line: str = line_bytes.decode("utf-8", errors="replace").strip()
        lines.append(decoded_line)

        # Move current_pos to the character after the newline for the next iteration
        current_pos = newline_index + 1

    # The remaining part of the buffer starts from current_pos
    remaining_buffer: bytes = buffer[current_pos:]
    return lines, remaining_buffer
