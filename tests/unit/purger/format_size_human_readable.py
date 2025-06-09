def format_size_human_readable(size_bytes: int) -> str:
    """Converts a size in bytes to a human-readable string (KB, MB, GB, etc.)."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    for unit in ["KB", "MB", "GB", "TB"]:
        size_bytes /= 1024
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.2f} PB"
