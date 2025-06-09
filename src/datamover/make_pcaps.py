#!/usr/bin/env python3
import argparse
import os
import logging
import sys
from datetime import datetime


def create_pcap_files(instance_prefix, num_files, target_directory, file_size_bytes):
    """
    Creates N .pcap files named <instance>-<YYYYMMDD-HHMMSS>-<seq>.pcap,
    each containing a specified number of null bytes.
    Reports progress every 1 GB (1 000 000 000 bytes) written in total.

    Args:
        instance_prefix (str): Three-letter instance prefix (e.g., "AAA").
        num_files (int): The number of files to create.
        target_directory (str): The directory where files will be created.
        file_size_bytes (int): The desired size of each file in bytes.
    """
    # Check if the target directory exists and is actually a directory
    if not os.path.isdir(target_directory):
        logging.error(
            f"Error: Target directory '{target_directory}' does not exist or is not a directory."
        )
        sys.exit(1)

    # Validate file_size_bytes to ensure it's non-negative
    if file_size_bytes < 0:
        logging.error(f"Error: File size '{file_size_bytes}' cannot be negative.")
        sys.exit(1)

    logging.info(f"Target directory '{target_directory}' verified.")
    logging.info(f"Each PCAP file will be {file_size_bytes} bytes.")

    # Use a single timestamp for all files
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Pre-build one chunk of null bytes of size `file_size_bytes`
    pcap_data = b"\x00" * file_size_bytes

    total_bytes_written = 0
    GB = 1_000_000_000
    next_report_threshold = GB
    report_count = 1

    for i in range(1, num_files + 1):
        sequence = f"{i:06d}"
        filename = f"{instance_prefix}-{timestamp}-{sequence}.pcap"
        full_path = os.path.join(target_directory, filename)

        # Create the file and write the specified bytes to it
        try:
            with open(full_path, "wb") as f:
                f.write(pcap_data)
            logging.debug(f"Created file: '{full_path}' with {file_size_bytes} bytes.")
        except IOError as e:
            logging.error(f"Error creating file '{full_path}': {e}")
            sys.exit(1)

        # Update cumulative bytes written
        total_bytes_written += file_size_bytes

        # Report every 1 GB written
        while total_bytes_written >= next_report_threshold:
            logging.info(f"Progress: written {report_count} GB so far.")
            report_count += 1
            next_report_threshold = GB * report_count

    logging.info(
        f"Successfully created {num_files} files in '{target_directory}' "
        f"with prefix '{instance_prefix}-{timestamp}-<seq>.pcap', each {file_size_bytes} bytes."
    )


def main():
    """
    Entrypoint for the console script "make_pcaps".
    Parses command-line arguments and initiates the file creation process.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description=(
            "Create N .pcap files named <instance>-<YYYYMMDD-HHMMSS>-<seq>.pcap, "
            "each containing a specified number of bytes. "
            "Reports progress every 1 GB."
        )
    )
    parser.add_argument(
        "-i",
        "--instance",
        required=True,
        help="Three-letter instance prefix (e.g., AAA)",
    )
    parser.add_argument(
        "-n", "--number", type=int, required=True, help="How many files to create"
    )
    parser.add_argument(
        "-d", "--directory", required=True, help="Target directory (must already exist)"
    )
    parser.add_argument(
        "-s",
        "--size",
        type=int,
        default=100,
        help="Size of each .pcap file in bytes (default: 100)",
    )

    args = parser.parse_args()

    create_pcap_files(
        instance_prefix=args.instance,
        num_files=args.number,
        target_directory=args.directory,
        file_size_bytes=args.size,
    )


if __name__ == "__main__":
    main()
