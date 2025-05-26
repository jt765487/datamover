## Requirements for the Data File Scan Thread

**Document Version:** 2.0
**Date:** 2023-10-28
**Purpose:** This document defines the requirements for the "Scan Thread," a component of the Python application responsible for detecting and initiating recovery actions for data files that have not been processed by the primary file handling mechanisms. It focuses on files in a designated source directory that are either "lost" (static and old) or "stuck" (unexpectedly growing for too long).

**1. Glossary**

*   **Application ({app_name}):** An external process that generates data files.
*   **Data File:** A file created by an {app_name}, typically following the naming convention `{app_name}-{timestamp}.{extension}` (e.g., `IXXY-20231028-120000.pcap`).
*   **Source Directory (`scan_directory_path`):** The filesystem directory monitored by this Scan Thread, where {app_name}s write their Data Files.
*   **CSV Directory (`csv_restart_directory`):** The filesystem directory where this Scan Thread creates `.restart` trigger files. This directory also typically contains `{app_name}.csv` ledger files managed by other parts of the system.
*   **File Extension (`file_extension_to_scan`):** The specific file extension (e.g., "pcap") that the Scan Thread targets in the Source Directory.
*   **Scan Interval (`scan_interval_seconds`):** The configured frequency (in seconds) at which the Scan Thread performs a full scan cycle of the Source Directory.
*   **Lost File:** A Data File in the Source Directory that:
    1.  Is no longer being actively written to (its size and modification time are stable compared to the previous scan, or it's the first time it's seen and its mtime is old).
    2.  Its last modification time (`mtime`) is older than the current time by more than the `lost_timeout_seconds`.
*   **Lost Timeout (`lost_timeout_seconds`):** The configurable duration (in seconds). If a Data File's `mtime` is older than `current_time - lost_timeout_seconds`, it's a candidate for being "Lost".
*   **Stuck File:** A Data File in the Source Directory that:
    1.  Is still being actively written to (its size or modification time has changed since the last scan).
    2.  Has been continuously active and present in the Source Directory for a duration exceeding `stuck_active_file_timeout_seconds` since it was *first observed by this Scan Thread*.
*   **Stuck Active Timeout (`stuck_active_file_timeout_seconds`):** The configurable duration (in seconds). If a Data File has been actively growing and observed by the scanner for longer than this, it's considered "Stuck".
*   **Restart Trigger File (`{app_name}.restart`):** An empty file created by the Scan Thread in the CSV Directory. Its presence signals an external mechanism (e.g., `systemd`) to restart the specified {app_name}.
*   **Lost File Queue (`lost_file_queue`):** A queue to which the Scan Thread enqueues the `Path` objects of identified "Lost Files" for downstream processing.
*   **Scan Thread:** The Python `threading.Thread` instance executing this logic.
*   **File State Record:** An internal data structure used by the Scan Thread to track the observed state (path, size, mtime, first seen time, previous scan's size/mtime) of each file across scan cycles.
*   **Monotonic Clock:** A clock that only moves forward and is not affected by system time changes (e.g., `time.monotonic()`), used for measuring durations like "first seen" and timeouts related to presence.
*   **Wall Clock:** Standard system time (e.g., `time.time()`), used for comparing file modification times.

**2. Functional Requirements**

*   **FR1: Configuration**
    *   FR1.1: The Scan Thread shall be configurable with the absolute path to the Source Directory to monitor.
    *   FR1.2: The Scan Thread shall be configurable with the absolute path to the CSV Directory where Restart Trigger Files are to be created.
    *   FR1.3: The Scan Thread shall be configurable with the file extension (e.g., "pcap", without the dot) of Data Files to scan for.
    *   FR1.4: The Scan Thread shall be configurable with the Scan Interval in seconds.
    *   FR1.5: The Scan Thread shall be configurable with the Lost Timeout in seconds.
    *   FR1.6: The Scan Thread shall be configurable with the Stuck Active Timeout in seconds.
        *   *Note:* While not a strict logical dependency for detection, `stuck_active_file_timeout_seconds` is typically configured to be greater than `lost_timeout_seconds` to allow a file to become "lost" before it might be considered "stuck" if it stopped growing just before the stuck timeout.

*   **FR2: Scan Cycle Operation**
    *   FR2.1: The Scan Thread shall periodically execute a scan cycle at the configured Scan Interval.
    *   FR2.2: In each scan cycle, the Scan Thread shall list all files in the Source Directory matching the configured File Extension.
    *   FR2.3: For each discovered file, the Scan Thread shall retrieve its current size and last modification time (`mtime`).
    *   FR2.4: The Scan Thread shall maintain a File State Record for each unique file path encountered across scan cycles.
        *   FR2.4.1: For newly discovered files, the File State Record shall store its path, current size, current `mtime`, and the current Monotonic Clock time as `first_seen_mono`. Its `prev_scan_size` and `prev_scan_mtime_wall` shall be initialized to its current size and `mtime` respectively (indicating no change *between scans* has yet been observed for this new file).
        *   FR2.4.2: For files seen in previous cycles, the File State Record shall be updated with the current size and `mtime`, while preserving its original `first_seen_mono`. The previous cycle's size and `mtime` shall be stored as `prev_scan_size` and `prev_scan_mtime_wall`.
    *   FR2.5: Files that were tracked in a previous File State Record but are no longer found in the Source Directory shall be removed from tracking.

*   **FR3: Lost File Detection and Handling**
    *   FR3.1: In each scan cycle, for every tracked file (including those seen for the first time in the current cycle), the Scan Thread shall determine if it is a "Lost File."
    *   FR3.2: A file is identified as "Lost" if:
        *   Condition A: Its current `mtime` is older than `current_wall_clock_time - Lost Timeout`.
    *   FR3.3: If a file is identified as "Lost" and was not identified as "Lost" in the immediately preceding scan cycle ("newly lost"), its `Path` shall be enqueued onto the Lost File Queue.
    *   FR3.4: Appropriate logging shall occur for newly lost files.

*   **FR4: Stuck File Detection and Handling**
    *   FR4.1: In each scan cycle, for every tracked file, the Scan Thread shall determine if it is a "Stuck File."
    *   FR4.2: A file is identified as "Stuck" if *all* of the following conditions are met:
        *   Condition A (Activity): The file's current size or `mtime` is different from its `prev_scan_size` or `prev_scan_mtime_wall` stored in its File State Record. (Note: Newly discovered files will not meet this condition in their first scan cycle due to initialization of `prev_scan_` values).
        *   Condition B (Prolonged Presence): The duration `current_monotonic_clock_time - file_state.first_seen_mono` is greater than the Stuck Active Timeout.
    *   FR4.3: If a file is identified as "Stuck" and was not identified as "Stuck" in the immediately preceding scan cycle ("newly stuck"):
        *   FR4.3.1: The Scan Thread shall attempt to parse an `{app_name}` from the Data File's filename (e.g., the leading part of `APPNAME-timestamp.ext`).
        *   FR4.3.2: If an `{app_name}` is successfully parsed:
            *   A Restart Trigger File, named `{app_name}.restart`, shall be created in the configured CSV Directory.
            *   Creation shall be skipped if a Restart Trigger File for that `{app_name}` already exists in the CSV Directory (idempotency).
        *   FR4.3.3: Appropriate critical logging shall occur for newly stuck files and any actions taken (or skipped) regarding the Restart Trigger File.
    *   FR4.4: "Stuck Files" shall NOT be enqueued onto the Lost File Queue by this detection logic directly. (They are expected to become "Lost" after the external application restarts and the file becomes static).

*   **FR5: Post-Restart Handling of Previously Stuck Files**
    *   FR5.1: After an {app_name} is restarted (externally triggered by a Restart Trigger File), a previously "Stuck File" associated with that app is expected to cease growing and become static.
    *   FR5.2: In subsequent scan cycles, this now-static file, if still present in the Source Directory, shall be evaluated by the "Lost File" detection logic (FR3). If it meets the "Lost File" criteria (old `mtime`), it will be identified as "Lost" and enqueued.

*   **FR6: Thread Management and Logging**
    *   FR6.1: The Scan Thread shall run as a daemon thread.
    *   FR6.2: The Scan Thread shall support a graceful stop mechanism (e.g., via a `threading.Event`).
    *   FR6.3: The Scan Thread shall log its initialization, start, stop, cycle activities, and any significant events or errors encountered, using appropriate log levels.
    *   FR6.4: If a critical error occurs that prevents scanning the Source Directory (e.g., permission denied), the Scan Thread should log the error and terminate.

**3. Non-Functional Requirements**

*   **NFR1: Robustness**
    *   NFR1.1: The Scan Thread must handle filesystem errors gracefully during file operations (e.g., file disappearing between listing and stat-ing, though `os.scandir` helps mitigate this).
    *   NFR1.2: Creation of Restart Trigger Files must be idempotent; if a restart is already pending for an app, another trigger should not overwrite or cause issues.
*   **NFR2: Performance**
    *   NFR2.1: The scanning process should be efficient and minimize I/O load, especially if the Source Directory can contain a large number of files. (Use of `fs.scandir` is good).
*   **NFR3: Testability**
    *   NFR3.1: The Scan Thread and its core logic components shall be designed for testability, utilizing dependency injection for filesystem operations, time functions, and queues.

**4. Assumptions**

*   A1: An external mechanism (e.g., `systemd`) monitors the CSV Directory for `*.restart` files and will restart the corresponding {app_name} when such a file appears.
*   A2: The external mechanism (e.g., `systemd`) is responsible for removing the `*.restart` file after processing it.
*   A3: The consumer of the Lost File Queue is capable of processing the `Path` objects of Data Files passed to it.
*   A4: The Python application running the Scan Thread has necessary read permissions for the Source Directory and read/write permissions for the CSV Directory.
*   A5: An {app_name}, after restarting, will resume normal operation, and any previously "Stuck File" it was writing will become static.
*   A6: Data File names reliably start with an `{app_name}` followed by a hyphen, allowing for parsing.

**5. Out of Scope**

*   OS1: The implementation of the external application restart mechanism (e.g., `systemd` configuration).
*   OS2: The implementation of the consumer of the Lost File Queue.
*   OS3: Management or cleanup of the `{app_name}.csv` ledger files; this Scan Thread does not use them for its detection logic.

---

**Key Changes from Previous Requirements (v1.1) and Clarifications:**

*   **Lost File Detection (FR3.1, FR3.2):** Specified that files are eligible for "lost" status on their first sight if their `mtime` is old enough. This implies removing the `if path in existing_states:` guard for the lost check in `process_scan_results`.
*   **Stuck File Activity (FR4.2 Condition A):** Clarified that newly discovered files won't meet the "active since last scan" criteria in their first cycle, naturally deferring their "stuck" classification.
*   **Timeout Relationship (FR1.6 Note):** Added a note about the typical configuration of timeouts.
*   **Glossary and Definitions:** Made definitions more precise.
*   **Overall Structure:** Aimed for a more formal and complete requirements document structure.
