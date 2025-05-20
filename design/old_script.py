import logging.handlers
import os
import subprocess
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

#### Python Script to asynchronously upload .pcaps once file is mined and transfer via CURL POST to a remote host - Mark Haley 14/10/24 ####

# Set the path to the log file and the remote host URL
# NOTE: The script refers to this as a "log file" but it's a CSV containing pcap paths.
# Renaming for clarity in comments, but keeping original variable name for consistency with the script's intent.
CSV_FILE_PATH = '/opt/SHA256-HASH.csv' # Was log_file_path
REMOTE_HOST_URL = 'http://31.120.166.214:8989/pcap'

# Set up syslog logging
logger = logging.getLogger('pcapUploader')
logger.setLevel(logging.INFO)
# Ensure this path is correct for your system if not running as root or in a container
# For systemd services, journald might be preferred, but syslog is explicitly used here.
syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
syslog_handler.setFormatter(formatter)
logger.addHandler(syslog_handler)

# Ensure the directory for the CSV file exists
csv_dir = os.path.dirname(CSV_FILE_PATH)
if not os.path.exists(csv_dir):
    # Using %-formatting for logger as per project standards
    logger.error("Directory %s does not exist.", csv_dir)
    exit(1) # Consider raising an exception for better error handling in larger apps

# Ensure the CSV file exists
if not os.path.isfile(CSV_FILE_PATH):
    logger.error("CSV file %s does not exist.", CSV_FILE_PATH)
    exit(1) # Consider raising an exception

# Function to send a file to the remote host using curl with POST and filename in header
def send_file(file_path: str):
    """
    Sends the specified file to the remote host using curl.
    """
    # Using print statements here, consider replacing with logger.debug or logger.info
    # as per project standards for application flow.
    # For now, keeping them as they were in the original script.
    print(f"Attempting to upload file: {file_path}")
    try:
        file_name = os.path.basename(file_path) # Extract file name from the full file path
        # Using Popen and communicate. Consider requests library for http tasks.
        process = subprocess.Popen(
            ['curl', '-k', '-X', 'POST', '--data-binary', f'@{file_path}', '-H', f'x-filename:{file_name}', REMOTE_HOST_URL],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            print(f"Successfully uploaded {file_path}")
            logger.info("Successfully uploaded %s", file_path)
        else:
            # Ensure stderr is decoded for printing/logging
            error_message = stderr.decode('utf-8', errors='replace').strip()
            print(f"Failed to upload {file_path}: {error_message}")
            logger.error("Failed to upload %s: %s", file_path, error_message)

    except FileNotFoundError:
        print(f"Error: File not found at {file_path} during upload attempt.")
        logger.error("File not found at %s during upload attempt.", file_path)
    except Exception as e:
        # Generic exception, good for catching unexpected issues
        print(f"An error occurred while uploading {file_path}: {str(e)}")
        logger.error("An error occurred while uploading %s: %s", file_path, str(e))


# Event handler for monitoring the CSV file
class LogFileHandler(FileSystemEventHandler): # Consider renaming to CsvFileHandler
    def __init__(self):
        super().__init__() # Good practice to call super().__init__()
        self.processed_lines = set()
        # Pre-load existing lines if the script might restart and process an already populated file
        self._load_initial_lines()
        logger.info("Initialized LogFileHandler. %d lines pre-processed from %s.", len(self.processed_lines), CSV_FILE_PATH)

    def _load_initial_lines(self):
        """Loads existing lines from the CSV file to avoid reprocessing."""
        try:
            with open(CSV_FILE_PATH, 'r', encoding='utf-8') as f:
                self.processed_lines.update(line.strip() for line in f)
        except FileNotFoundError:
            logger.warning("CSV file %s not found during initial load. Will be created or error out if not writeable.", CSV_FILE_PATH)
        except Exception as e:
            logger.error("Error loading initial lines from %s: %s", CSV_FILE_PATH, e)


    def on_modified(self, event):
        if event.is_directory:
            return # Ignore directory events

        if event.src_path == CSV_FILE_PATH:
            logger.info("Detected modification in %s", CSV_FILE_PATH)
            new_lines_processed_this_event = []
            try:
                with open(CSV_FILE_PATH, 'r', encoding='utf-8') as f:
                    current_lines = [line.strip() for line in f if line.strip()] # Read and strip
                    # Determine actual new lines not yet seen
                    new_unique_lines = []
                    for line in current_lines:
                        if line not in self.processed_lines:
                            new_unique_lines.append(line)
                            self.processed_lines.add(line) # Add to processed set immediately

                if new_unique_lines:
                    logger.info("%d new unique lines detected.", len(new_unique_lines))
                    for line_content in new_unique_lines:
                        # Assuming the pcap path is the second field in a CSV: timestamp,filepath,hash
                        # Original regex: r'([a-zA-Z0-9/_-]+\.pcap)' might be too broad or too narrow
                        # depending on the actual content of CSV_FILE_PATH.
                        # If CSV format is "timestamp,filepath.pcap,hash", then:
                        parts = line_content.split(',')
                        if len(parts) >= 2: # Ensure there are at least two parts
                            # The prompt mentions "Full path to the corresponding .pcap file"
                            # so the file path should be directly usable.
                            file_path_to_upload = parts[1].strip()

                            # Validate if it looks like a pcap file path (optional, but good for robustness)
                            if file_path_to_upload.endswith(".pcap") and os.path.isabs(file_path_to_upload): # Check if it's an absolute path
                                logger.info("Extracted file path to upload: %s", file_path_to_upload)
                                # Before sending, check if the file actually exists
                                if os.path.exists(file_path_to_upload):
                                    send_file(file_path_to_upload)
                                else:
                                    logger.warning("File path %s from CSV does not exist on filesystem.", file_path_to_upload)
                            else:
                                logger.warning("Line does not contain a valid .pcap file path in the expected format: %s", line_content)
                        else:
                            logger.warning("Line does not have enough parts to extract a filepath: %s", line_content)
                # else:
                #     logger.info("No new unique lines found in %s after modification.", CSV_FILE_PATH)

            except Exception as e:
                logger.error("Error processing modification of %s: %s", CSV_FILE_PATH, e)


# Main function to start the file monitoring
def main():
    logger.info("Starting pcap uploader script.")
    event_handler = LogFileHandler()
    observer = Observer()
    # Watch the directory containing the CSV file, as watching a single file can be unreliable across OS/filesystems
    # However, the handler logic specifically checks event.src_path == CSV_FILE_PATH
    observer.schedule(event_handler, path=csv_dir, recursive=False)
    observer.start()
    logger.info("Monitoring %s for new file names...", CSV_FILE_PATH)

    try:
        while True:
            time.sleep(1) # Keep the main thread alive
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
    finally:
        observer.stop()
        observer.join()
        logger.info("Observer stopped. Exiting.")

if __name__ == "__main__":
    main()