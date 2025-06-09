#!/usr/bin/env python3

import logging
import threading
import sys
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configure logging with a timestamp for better tracking
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class PcapHandler(BaseHTTPRequestHandler):
    # Class-level variables for shared state across all handler instances
    _total_files_received = 0
    # A deque to store timestamps of received files for the 'last minute' calculation
    _last_minute_timestamps = deque()
    # A lock to protect access to the shared counters and timestamp deque
    _lock = threading.Lock()

    def do_POST(self):
        if self.path != "/pcap":
            self.send_error(404, "Not Found")
            return

        # Extract filename and content-type (or defaults)
        file_name = self.headers.get("x-filename", "unknown")
        content_type = self.headers.get("Content-Type", "unknown")

        # Read exactly Content-Length bytes (if any)
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length) if length > 0 else b""
        data_length = len(data)

        # Acquire the lock to safely update shared counters
        with PcapHandler._lock:
            PcapHandler._total_files_received += 1
            current_time = datetime.now()
            PcapHandler._last_minute_timestamps.append(current_time)

            # Prune timestamps older than 1 minute
            one_minute_ago = current_time - timedelta(minutes=1)
            while (
                PcapHandler._last_minute_timestamps
                and PcapHandler._last_minute_timestamps[0] < one_minute_ago
            ):
                PcapHandler._last_minute_timestamps.popleft()

            files_in_last_minute = len(PcapHandler._last_minute_timestamps)
            total_files = PcapHandler._total_files_received

        logging.info("Received Content-Type: %s", content_type)
        logging.info(
            "Received file '%s' (%d bytes). Metrics: Files last minute: %d, Total files: %d",
            file_name,
            data_length,
            files_in_last_minute,
            total_files,
        )

        # Respond with 200 OK and body "OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):
        # Route internal HTTP server logs through logging module
        logging.info(
            "%s - - [%s] %s",
            self.client_address[0],
            self.log_date_time_string(),
            fmt % args,
        )


def main():
    """
    Entrypoint for the console script “data_rx”.
    Starts an HTTP server to receive PCAP files via POST requests.
    """
    server = HTTPServer(("0.0.0.0", 8989), PcapHandler)
    logging.info("Starting HTTP server on 0.0.0.0:8989")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server received KeyboardInterrupt. Shutting down...")
        server.shutdown()  # Shuts down the server gracefully
        sys.exit(0)  # Exit cleanly


if __name__ == "__main__":
    main()
