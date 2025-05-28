**Requirements: Restart Trigger for Stuck Applications**

**Document Version:** 2.1
**Date:** 2025-05-01
**Author:** Data Mover Team

---

## 1. Purpose

When a data‐producing application ("app") writes a file that continues growing beyond a configured "stuck" timeout, the Scan Thread must signal an external supervisor (e.g., systemd) to restart that specific app. Because the supervisor removes the trigger almost immediately, the Scan Thread tracks at the *application* level to avoid repeated signals during a single stuck episode.

This document captures the requirements for that restart‐trigger feature.

---

## 2. Glossary

* **App Name**: The prefix of a data file’s name before the first hyphen (e.g., `IXXY` in `IXXY-20250525-194400.pcap`).
* **Stuck File**: A file that is still actively being written and has been present longer than the `stuck_active_timeout_seconds`.
* **Stuck App**: The application owning one or more *stuck files*.
* **Restart Trigger File**: An empty file named `{app_name}.restart` created in the CSV/trigger directory to signal a restart.
* **Signaled Apps**: The set of app names for which a restart trigger has already been issued in the current stuck episode.

---

## 3. Functional Requirements

### FR1. Identification of Stuck Apps

1. **Scan Cycle**: Each cycle, determine `current_stuck_file_paths`.
2. **Derive App Set**: Compute `current_stuck_apps = {app_from(path) for path in current_stuck_file_paths}`.

### FR2. Restart Trigger Logic

1. **Track Previously Signaled**: Maintain `previously_signaled_apps: Set[str]` across cycles.
2. **Newly Stuck**: Compute `newly_stuck_apps = current_stuck_apps - previously_signaled_apps`.
3. **Create Trigger**: For each `app` in `newly_stuck_apps`, atomically create an empty file `{csv_dir}/{app}.restart` *only if it does not already exist*.
4. **Update Memory**: Set `previously_signaled_apps = current_stuck_apps` (so only fresh apps will be signaled next time).

### FR3. Interplay with External Supervisor

1. **Immediate Removal**: The supervisor’s oneshot service removes the `.restart` file almost immediately after issuing the restart.
2. **Persistence in Memory**: Because the file on disk is transient, the logic must rely on `previously_signaled_apps`, *not* on the filesystem, to avoid re‑signaling the same app in one stuck phase.

### FR4. Recovery and Re‑Signaling

1. **Unstuck Detection**: As soon as an app’s stuck file stops growing (it no longer appears in `current_stuck_file_paths`), it is dropped from `current_stuck_apps`.
2. **Memory Reset**: In that cycle, `previously_signaled_apps` is updated to no longer include that app—making it eligible for a future signal if it gets stuck again.
3. **Subsequent Stuck Phase**: If later that app produces a new stuck file, it will be in `newly_stuck_apps` again and receive a new `.restart` file.

---

## 4. Non‑Functional Requirements

* **NFR1 Idempotency**: Creating a trigger file for an already-signaled app must be skipped.
* **NFR2 Robustness**: Handle filesystem failures (e.g., directory missing, permission errors) by logging and continuing without crashing.
* **NFR3 Testability**: Expose `determine_app_restart_actions(current, previous, dir)` as a pure function for unit testing.

---

## 5. Example Flow

1. Cycle 1: `fileA-...` is active > timeout → `current_stuck_apps={"fileA"}`; `previously_signaled_apps={}` → signal → create `fileA.restart`; store `previously_signaled_apps={"fileA"}`.
2. Cycle 2..N: File still growing → `current_stuck_apps={"fileA"}`; `newly_stuck_apps={}` → do nothing.
3. Cycle N+1: File stops growing → `current_stuck_apps={}`; `previously_signaled_apps` updated to `{}`.
4. Later: New stuck file for `fileA` → step 1 repeats.

---
