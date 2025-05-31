# Project Playbook Collection: DataMover

This collection outlines the structured processes and guidelines for collaborative development on the DataMover project. These playbooks are designed to ensure clarity, consistency, testability, and effective collaboration between human developers and AI assistants.

## Core Guiding Principles ("How We Build Together")

(We can either link to a separate `HOW_WE_BUILD.md` or summarize key points here from our previous discussion: Modularity, Clear Interfaces & DI, Purity & State Management, Explicit Requirements, Structured Logging & Error Handling, Iterative Refinement.)

## The Playbooks

1.  **[Guide 1: Requirements Definition Playbook](./01-requirements-definition.md)**
    *   For collaboratively producing a clear, concise, testable requirements document for a specific module or component.
2.  **[Guide 2: Code & Unit Test Generation Playbook](./02-code-and-test-generation.md)**
    *   For implementing a module/component and concurrently developing robust unit tests.
3.  **[Guide 3: Complexity Management Playbook](./03-complexity-management.md)**
    *   General principles for managing cognitive load and ensuring appropriately sized work units.
4.  **[Guide 4: Architecture & Project Context Playbook](./04-architecture-and-project-context.md)**
    *   For establishing and maintaining shared understanding of the overall project architecture, common utilities, and conventions.
5.  **(Future) [Guide 5: Integration Testing Playbook](./05-integration-testing.md)**

---

Now, for the individual playbook templates:

**Template 1: `docs/playbooks/01-requirements-definition.md`**

```markdown
# Guide 1: Requirements Definition for [ModuleName/ComponentName]

**Date:** YYYY-MM-DD
**Version:** 1.0
**Stakeholders (Optional):** [List any key stakeholders and their roles, e.g., Product Owner, Lead Dev]

## 1. Introduction & Purpose

*   **Component Name:** [ModuleName/ComponentName]
*   **Primary Purpose:** [Briefly describe why this component exists and its main goal. What problem does it solve?]
*   **Scope:**
    *   **In Scope:** [List key functionalities/responsibilities that ARE part of this component.]
    *   **Out of Scope:** [List functionalities/responsibilities that ARE NOT part of this component but might be related.]

## 2. Definitions & Terminology

| Term                             | Definition                                                                                                   |
| :------------------------------- | :----------------------------------------------------------------------------------------------------------- |
| [Term1]                          | [Definition1]                                                                                                |
| [Term2]                          | [Definition2]                                                                                                |
| `DataStructureName` (if any)     | [Description, key attributes, behavior e.g., sort order. Provide Python @dataclass snippet if available/simple] |
| `CustomExceptionName` (if any)   | [Purpose of this exception]                                                                                  |

## 3. Functional Requirements

*(For each requirement, consider annotating with MVP/Phase if applicable, e.g., FR-1 [MVP])*

*   **FR-1: [Descriptive Title for Requirement 1]**
    *   [Detailed description of the functionality. "The system shall..."]
    *   **Inputs:** [If specific to this FR]
    *   **Processing:** [Key steps or logic]
    *   **Outputs/Side Effects:** [Expected results or changes]
    *   **Error Conditions:** [Specific errors this FR might encounter/handle]

*   **FR-2: [Descriptive Title for Requirement 2]**
    *   [...]

*   *(Add as many FRs as needed)*

## 4. Non-Functional Requirements

*   **NFR-1: Logging**
    *   [Specific logging expectations for this component, e.g., "Log INFO on start/stop," "Log ERROR for X condition," "Summary logs should be structured as per Project Context Guide."]
    *   [Refer to Guide 4: Architecture & Project Context for global logging standards.]

*   **NFR-2: Error Handling**
    *   [Specific error handling philosophy for this component, e.g., "Fail fast for critical errors," "Retry X times for transient network issues (if applicable)."]
    *   [Custom exceptions to be raised/handled by this component.]

*   **NFR-3: Performance (Optional)**
    *   [Any specific performance targets, e.g., "Process X items per second," "Respond within Y ms."]

*   **NFR-4: Testability**
    *   [Guideline: Component should be designed for unit testability, favoring DI and separation of concerns as per "How We Build Together" principles.]

## 5. External Dependencies (High-Level)

*   [Dependency 1 Name]: [Brief description of what it's used for, e.g., "Filesystem Abstraction (FS) for all file operations."]
*   [Dependency 2 Name]: [e.g., "Time Source for timestamps."]
*   [Dependency 3 Name]: [e.g., "Specific Deletion Logic for removing files."]

## 6. Assumptions

*   [Assumption 1, e.g., "The underlying filesystem behaves consistently."]
*   [Assumption 2, e.g., "Input data structures will conform to the defined format."]

## 7. Preliminary Next Steps (for Guide 2)

*   [e.g., "Define precise Python interfaces/protocols for identified external dependencies."]
*   [e.g., "Design the class structure for [ModuleName/ComponentName]."]
*   [e.g., "Outline key methods based on Functional Requirements."]

## 8. Traceability Matrix (Optional Appendix - to be filled later)

| Req ID | Description Snippet | Implemented In (Class/Method) | Test Case(s) |
| :----- | :------------------ | :---------------------------- | :----------- |
| FR-1   | ...                 |                               |              |
| NFR-1  | Logging             |                               |              |

---