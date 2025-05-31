# Guide 1: Requirements Definition for [ModuleName/ComponentName]

**Component Name:** `[Clearly state the name of the module or component]`
**Date Created:** `YYYY-MM-DD`
**Last Updated:** `YYYY-MM-DD`
**Version:** `1.0`
**Primary Author(s)/Owner(s):** `[Your Name/Team, AI Assistant]`
**Stakeholders (Optional):** `[e.g., Product Lead, QA Lead, DevOps Lead - for sign-off/review]`

## 1. Introduction & Purpose

### 1.1. Component Overview
[Briefly describe what this component is, its primary responsibility, and how it fits into the larger DataMover system (if applicable). What problem does it solve or what value does it provide?]

### 1.2. Goals & Objectives
*   [Goal 1: e.g., To efficiently monitor disk space usage across specified directories.]
*   [Goal 2: e.g., To reliably purge files based on age and predefined thresholds when space limits are exceeded.]
*   [Objective 1: e.g., Achieve X% reduction in disk space within Y minutes of a purge trigger.]

### 1.3. Scope
*   **In Scope:**
    *   [Clearly list key functionalities and responsibilities that ARE part of this component.]
    *   [e.g., Scanning `uploaded_dir` and `work_dir` for regular files.]
    *   [e.g., Calculating total disk space used by these files.]
    *   [e.g., Triggering a purge operation if `max_total_data_size_bytes` is exceeded.]
    *   [e.g., Deleting files from `uploaded_dir` then `work_dir` based on mtime/size until `purge_target_data_size_bytes` is met.]
*   **Out of Scope:**
    *   [Clearly list functionalities that ARE NOT part of this component but might be related or confused with it.]
    *   [e.g., Recursive directory scanning.]
    *   [e.g., Determining the initial values for threshold configurations.]
    *   [e.g., Global application logging setup (though this component will use it).]

## 2. Definitions & Terminology

| Term                             | Definition                                                                                                                                                                                                 | Source/Reference (Optional) |
| :------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------- |
| `[Term1: e.g., uploaded_dir]`      | `[Definition1: e.g., Path to the directory containing successfully processed files, primary purge candidates.]`                                                                                              | Guide 4 (Project Context)   |
| `[Term2: e.g., GatheredEntryData]` | `[Definition2: e.g., Dataclass (mtime: float, size: int, path: Path) representing a scanned file. Sorts by mtime (ASC), then size (ASC). Path ignored for sorting.]`                                       | `datamover.purger.scanner`    |
| `[CustomExceptionName]`          | `[e.g., ScanDirectoryError: Raised if a directory cannot be fully scanned due to permissions, non-existence, etc.]`                                                                                        | `datamover.file_exceptions` |
| *(Add other relevant terms)*     |                                                                                                                                                                                                            |                             |

## 3. Functional Requirements (FR)

*(Annotation Key: [MVP] - Minimal Viable Product/Phase 1; [P2] - Phase 2; [OPT] - Optional)*

*   **FR-ID: `FR-001` [MVP]**
    *   **Title:** Component Initialization and Configuration Validation
    *   **Description:** The component shall be initializable with parameters A, B, C. Parameter A must be a positive integer; if not, a `ValueError` shall be raised. If parameter B is not less than A, a WARNING log shall be issued.
    *   **Inputs:** `param_A: int`, `param_B: int`, `param_C: str`
    *   **Acceptance Criteria:**
        1.  Given valid A, B, C, initialization succeeds.
        2.  Given A <= 0, `ValueError` is raised with message "param_A must be positive".
        3.  Given B >= A, a WARNING log containing "param_B should be less than param_A" is emitted.
    *   **Related NFRs:** NFR-LOG-01, NFR-ERR-01

*   **FR-ID: `FR-002` [MVP]**
    *   **Title:** [Descriptive Title for Requirement 2]
    *   **Description:** [Detailed description. "The system shall..."]
    *   **Inputs:** [...]
    *   **Processing Steps (Optional - if complex):**
        1.  [Step 1]
        2.  [Step 2]
    *   **Outputs/Side Effects:** [...]
    *   **Acceptance Criteria:**
        1.  [Clear, testable statement 1: Given X, when Y, then Z.]
        2.  [Clear, testable statement 2]
    *   **Error Conditions & Handling:** [Specific errors this FR might encounter/handle and expected behavior.]
    *   **Related NFRs:** [...]

*   *(Add as many FRs as needed, following a similar structure)*

## 4. Non-Functional Requirements (NFR)

*   **NFR-ID: `NFR-LOG-01` [MVP]**
    *   **Category:** Logging
    *   **Description:** All significant operations, errors, and state changes shall be logged according to the project's logging standards (see Guide 4).
    *   **Acceptance Criteria:**
        1.  Successful initialization logged at INFO level with key config parameters.
        2.  Specific error condition X logged at ERROR level with relevant context.
        3.  Summary of operation Y logged at INFO level in structured format.
    *   **References:** Guide 4 (Architecture & Project Context - Logging Conventions)

*   **NFR-ID: `NFR-ERR-01` [MVP]**
    *   **Category:** Error Handling & Resilience
    *   **Description:** The component shall handle expected errors gracefully (e.g., `DependencyErrorX` from Dependency Y) by [logging and continuing/retrying/failing safely]. Unexpected errors should [be logged with a traceback and allow the component/thread to recover if possible / terminate cleanly].
    *   **Acceptance Criteria:**
        1.  When `DependencyErrorX` occurs, an ERROR log is emitted, and operation Z is skipped/retried.
        2.  When an unhandled `RuntimeError` occurs, an EXCEPTION log with traceback is emitted.
    *   **References:** Guide 4 (Architecture & Project Context - Error Handling Strategy)

*   **NFR-ID: `NFR-TEST-01` [MVP]**
    *   **Category:** Testability
    *   **Description:** The component shall be designed to maximize unit testability, adhering to principles of DI, separation of concerns, and modularity as outlined in "How We Build Together."
    *   **Acceptance Criteria:**
        1.  Core logic is testable in isolation from I/O and threading.
        2.  All external dependencies can be mocked for unit tests.
    *   **References:** "How We Build Together" Guide

*   **NFR-ID: `NFR-PERF-01` [P2] (Optional)**
    *   **Category:** Performance
    *   **Description:** [e.g., The scan operation for a directory with 10,000 files should complete within X seconds.]
    *   **Acceptance Criteria:**
        1.  [Testable performance metric under specified load conditions.]

*   *(Add other NFRs as relevant: Security, Usability (for CLI tools), Maintainability, etc.)*

## 5. External Dependencies & Interfaces

*(This section defines the contracts this module relies on. Precise interfaces will be finalized in Guide 2, but this outlines the needs.)*

| Dependency Name           | Provided By / Type     | Purpose within this Component                                 | Key Methods/Interactions Expected (High-Level)                     |
| :------------------------ | :--------------------- | :------------------------------------------------------------ | :----------------------------------------------------------------- |
| Filesystem Abstraction (FS) | Injected (`FSProtocol`) | All direct file/directory operations (stat, unlink, scandir). | `lstat()`, `unlink()`, `scandir()`, `resolve()`                    |
| Time Source               | Injected (`Callable`)  | Obtaining current timestamps for age calculations.            | `time_source()` returns `float`                                    |
| File Deletion Logic       | Injected (`Callable`)  | Performing the actual safe deletion of a file.                | `delete_function(path: Path, fs: FS)` raises `DeleteValidationError` |
| *(Add others)*            |                        |                                                               |                                                                    |

## 6. Assumptions

*   `A-001:` [e.g., The underlying filesystem provides consistent mtime values.]
*   `A-002:` [e.g., External dependencies (listed above) will adhere to their expected interfaces and behaviors.]
*   `A-003:` [e.g., Input configuration parameters (like directory paths) are syntactically valid; existence/permissions are checked at runtime by the component or its dependencies.]

## 7. Open Questions / Items for Discussion

*   `Q-001:` [e.g., How should the component behave if both `uploaded_dir` and `work_dir` are inaccessible during a scan cycle?]
*   `Q-002:` [e.g., Is there a maximum number of files to delete in a single purge cycle, irrespective of the target size?]

## 8. Preliminary Plan for Implementation (Guide 2)

*   Solidify Python interfaces/protocols for dependencies listed in Section 5.
*   Design the primary class(es) and method signatures for `[ModuleName/ComponentName]`.
*   Identify key unit test scenarios based on FRs and NFRs.

## 9. Traceability Matrix (To be filled progressively or as an appendix)

| Req ID (FR/NFR) | Description Snippet                    | Implemented In (Class/Method - Guide 2) | Test Case ID(s) (Guide 2) | Status (Planned, Implemented, Tested) |
| :-------------- | :------------------------------------- | :------------------------------------ | :------------------------ | :------------------------------------ |
| FR-001          | Initialization & Config Validation     | `[ClassName.__init__]`                | `test_init_valid`, `test_init_invalid_A` | Planned                             |
| FR-002          | ...                                    |                                       |                           | Planned                             |
| NFR-LOG-01      | Logging standards met                  | (Throughout)                          | (Verified in various tests) | Planned                             |
| ...             |                                        |                                       |                           |                                     |

---