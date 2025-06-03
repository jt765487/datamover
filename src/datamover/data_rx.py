#!/usr/bin/env python3
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO)

class PcapHandler(BaseHTTPRequestHandler):
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

        logging.info("Received Content-Type: %s", content_type)
        logging.info("Received file '%s' (%d bytes)", file_name, data_length)

        # Respond with 200 OK and body "OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):
        # Route internal HTTP server logs through logging module
        logging.info("%s - - [%s] %s",
                     self.client_address[0],
                     self.log_date_time_string(),
                     fmt % args)

def main():
    """
    Entrypoint for the console script “data_rx”.
    """
    server = HTTPServer(("0.0.0.0", 8989), PcapHandler)
    logging.info("Starting HTTP server on 0.0.0.0:8989")
    server.serve_forever()
