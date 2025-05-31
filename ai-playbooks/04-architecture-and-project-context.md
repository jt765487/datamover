# Guide 4: DataMover - Architecture & Project Context

**Last Updated:** YYYY-MM-DD
**Version:** X.Y

This document serves as the "Project Bible," outlining the overall architecture, shared services, common utilities, and project-wide conventions for the DataMover project. It is intended to be a living document, updated as the project evolves.

## 1. High-Level Architecture Overview

*   [Insert or link to high-level diagrams if available. Textual description of main components and their interactions.]
*   [e.g., "DataMover consists of: Input Scanners, a central Processing Core, an Uploader, and a Purger. They communicate via XYZ mechanism..."]

## 2. Core Shared Services & Utilities

| Service/Utility             | Description & Purpose                                       | Location/Definition                                     | Usage Notes/Conventions                                     |
| :-------------------------- | :---------------------------------------------------------- | :------------------------------------------------------ | :---------------------------------------------------------- |
| **Filesystem Abstraction (FS)** | Provides a consistent interface for all file operations.    | `datamover.file_functions.fs_mock.FS` (or `protocols.FS`) | Inject via DI. Use `mock_fs` fixture in tests.             |
| **Logging Framework**         | Standard Python `logging`, configured globally.             | (Global setup)                                          | See "Logging Conventions" below. Use `tests.utils.logging_helpers.find_log_record`. |
| **Configuration Management**  | How application configuration is loaded and accessed.     | `datamover.startup_code.load_config.Config` (example)   | Injected where needed or accessed via a global instance.    |
| **Custom Exceptions Base**    | Base exceptions for the project.                            | `datamover.file_functions.file_exceptions` (example)  | Inherit from these for domain-specific errors.            |
| **HTTP Client Wrapper (if any)**| Centralized way to make HTTP requests.                    | `datamover.utils.http_client` (example)                 | Handles retries, timeouts, common headers.                  |
| **`GatheredEntryData`**       | Standard data structure for file metadata.                  | `datamover.purger.scanner.GatheredEntryData`            | Represents regular files; sorts by mtime then size.       |
| *(Add other shared components)*|                                                             |                                                         |                                                             |

## 3. Project-Wide Conventions

### 3.1. Coding Style & Linting
*   [e.g., "Follow PEP 8."]
*   [e.g., "Linters: Black, Flake8, Mypy (strict mode). Configuration in `pyproject.toml`."]

### 3.2. Dependency Injection (DI)
*   [e.g., "Prefer constructor injection for mandatory dependencies."]
*   [e.g., "Method injection can be used for optional or per-call dependencies."]
*   [e.g., "Define clear Python Protocols or ABCs for injectable interfaces."]

### 3.3. Logging Conventions (Referenced by System Prompt)
*   [As per your existing detailed system prompt section 5.7, e.g., use of `find_log_record`, log levels, structured logging for summaries.]
*   [e.g., "Include `self.name` or class name in log messages from threaded/class-based components for clarity."]

### 3.4. Error Handling Strategy
*   [e.g., "Use specific custom exceptions for known, handlable error conditions."]
*   [e.g., "Allow unexpected/system errors to propagate to a higher-level handler or terminate the thread/process safely."]
*   [e.g., "Log errors appropriately (ERROR for handled, EXCEPTION for unhandled with traceback)."]

### 3.5. Testing (Referenced by System Prompt)
*   **Framework:** Pytest
*   **Structure:** `tests/unit/`, `tests/integration/`, `tests/e2e/`. `conftest.py` at appropriate levels.
*   **Core Principles:** Clarity, Isolation, Readability (AAA), Consistency, Maintainability, Mypy Compliance.
*   **Naming:** `test_<module>.py`, `Test<ComponentName>`, `test_<unit>_<scenario>_<expected>`.
*   **Fixtures:** Use fixtures for setup. Default to function scope.
*   **Mocking:** `unittest.mock.patch`, DI. Use `spec` for mocks. `cast()` for Mypy.
*   **(Add key points from your system prompt's testing guidelines here)**

### 3.6. Naming Conventions (General)
*   [e.g., `snake_case` for functions, methods, variables. `PascalCase` for classes.]

## 4. Common Interface Definitions Location
*   [e.g., "Shared Python Protocols are defined in `datamover/protocols.py`."]
*   [e.g., "Dataclasses used across modules are in `datamover/shared_types.py`."]

## 5. Target Runtime Environments & Constraints (Optional)
*   [e.g., "Python 3.9+"]
*   [e.g., "Target OS: Linux"]
*   [e.g., "Expected to run in Docker containers with X memory/CPU limits."]

## 6. Health Check & Observability Blueprint (Optional)
*   [e.g., "Long-running services should implement a `HealthCheckable` protocol with a `check_health()` method."]
*   [e.g., "Metrics will be exposed via a Prometheus client, using a shared `MetricsCollector` abstraction."]

## 7. Version Log

| Version | Date       | Changes                                      |
| :------ | :--------- | :------------------------------------------- |
| 1.0     | YYYY-MM-DD | Initial draft.                               |
| 1.1     | YYYY-MM-DD | Added section on HTTP Client Wrapper.        |

---