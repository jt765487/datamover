# Guide 2: Code & Unit Test Generation for [ModuleName/ComponentName]

**Associated Requirements Doc:** [Link to or name of the Guide 1 output for this module]
**Date Started:** YYYY-MM-DD
**Version:** 1.0

## 0. Preparation & Context Review

*   [ ] Review the **Requirements Document** for [ModuleName/ComponentName].
*   [ ] Review **Guide 4: Architecture & Project Context** for project-wide standards (logging, error handling, common utilities, etc.).
*   [ ] Review our **"How We Build Together"** principles (modularity, DI, purity, etc.).
*   [ ] Identify relevant existing project code/utils (e.g., common `FS` protocol, `conftest.py` fixtures, helper functions). List them here:
    *   `[path/to/util1.py]`
    *   `[path/to/conftest.py]`

## 1. Define/Refine Dependency Interfaces

*   **Dependency 1: [Name from Req Doc, e.g., FS Abstraction]**
    *   **Interface/Protocol Definition (Python snippet or path to existing):**
      ```python
      # Example:
      # class FSProtocol(Protocol):
      #     def read(self, path: Path) -> bytes: ...
      #     def write(self, path: Path, data: bytes) -> None: ...
      ```
    *   **Injection Method:** [e.g., Constructor, Method Argument]

*   **Dependency 2: [Name from Req Doc]**
    *   **Interface/Protocol Definition:**
    *   **Injection Method:**

*   *(Add for all direct external dependencies of this module)*

## 2. Generate/Implement Code

*   **Module/Class Structure Plan:**
    *   [Brief outline of classes and key methods within this module/component.]
    *   [e.g., `PurgerLogic` class with `__init__` and `decide_and_execute_purge` method.]

*   **Code Generation & Review Iterations:**
    *   **(AI Generates Code for a part / the whole module)**
    *   **Code Review Checklist Pass (Human + AI):**
        *   [ ] Adheres to requirements?
        *   [ ] Follows "How We Build Together" principles (modularity, clarity, DI)?
        *   [ ] Uses agreed interfaces for dependencies?
        *   [ ] Logging implemented as per NFRs/Project Context?
        *   [ ] Error handling implemented as per NFRs/Project Context?
        *   [ ] Docstrings for public classes/methods?
        *   [ ] (Optional) No function > X lines? (Project specific heuristic)
        *   [ ] (Optional) No direct filesystem/network calls (uses abstractions)?
    *   **(Iterate on generation/review until satisfactory)**

*   **Final Implemented Code Location(s):**
    *   `[path/to/module_code.py]`

## 3. Agree on Unit Test Scenarios

*(For each key public method or logical unit)*

*   **Method/Unit: `[ClassName.method_name or function_name]`**
    *   **Scenario 1: [Descriptive name, e.g., "Happy path - valid inputs"]**
        *   **Preconditions/Arrange:** [Inputs, initial state, mock setups]
        *   **Act:** [Call the method/function]
        *   **Assert:** [Expected return value, state changes, mock calls, log messages, exceptions]
    *   **Scenario 2: [e.g., "Edge case - empty input list"]**
        *   **Preconditions/Arrange:**
        *   **Act:**
        *   **Assert:**
    *   **Scenario 3: [e.g., "Error case - dependency raises XError"]**
        *   **Preconditions/Arrange:**
        *   **Act:**
        *   **Assert:**
    *   *(Add as many scenarios as needed to cover requirements and branches)*

*   **(Optional) Consider need for a simple "Smoke Test" for this module?** [Yes/No, Rationale]

## 4. Generate Unit Tests

*   **(AI Generates Pytest Tests based on agreed scenarios and project's Pytest guidelines from System Prompt)**
*   **Test Code Review:**
    *   [ ] Tests align with agreed scenarios?
    *   [ ] AAA pattern followed?
    *   [ ] Mocks used correctly (spec, return_values, side_effects)?
    *   [ ] Assertions are specific and correct?
    *   [ ] `caplog` / `find_log_record` used as per guidelines?
    *   [ ] Type hints present and correct (`mypy --strict` compliance)?
*   **(Iterate on generation/review until satisfactory)**
*   **Run Tests:** [All Pass / Issues Noted]
*   **(Optional) Test Coverage Goal:** [e.g., >90% branch coverage. Actual: X%]

*   **Final Test Code Location(s):**
    *   `[path/to/test_module_code.py]`

## 5. Outputs & Notes

*   **Implemented Code:** `[path/to/module_code.py]`
*   **Pytest Suite:** `[path/to/test_module_code.py]`
*   **Newly Defined Interfaces/Protocols (if any):** `[path/to/interfaces.py]`
*   **Notes/Edge Concerns/TODOs for future:**
    *   [Any observations, potential refactorings, or integration points to remember.]

---