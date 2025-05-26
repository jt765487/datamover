import argparse


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments for the PCAP Uploader Service.

    Defines arguments for enabling development mode (debug logging) and
    specifying a configuration file path.

    Returns:
        argparse.Namespace: An object holding the parsed command-line arguments
                            as attributes.
    """
    parser = argparse.ArgumentParser(
        prog="PCAP Uploader Service",
        description="Uploads PCAP files created by the Miner.",
    )
    parser.add_argument(
        "--dev", action="store_true", help="Enable debug logging to console"
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.ini",
        help="Path to the INI configuration file",
    )
    return parser.parse_args()
