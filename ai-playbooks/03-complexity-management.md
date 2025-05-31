# Guide 3: Complexity Management

This guide outlines general principles for managing complexity to ensure our collaborative development remains efficient and our modules remain understandable, testable, and maintainable.

## Core Principle

We aim to keep the cognitive load and the amount of context required for any single task (requirements definition, code generation, testing for a module) manageable. If a task or component feels too large or overwhelming, it's a signal to pause and consider decomposition.

## Guidelines & Heuristics

1.  **Requirements Phase (Guide 1):**
    *   If a single component's requirements document is becoming excessively long (e.g., significantly more than 3-4 concise pages for a focused component) or covers many distinct, loosely related areas of responsibility, discuss splitting it into multiple, smaller components, each with its own focused requirements document.

2.  **Code & Test Generation Phase (Guide 2):**
    *   A "module" or "component" being worked on in this phase should ideally map to one or a very small number (e.g., 1-3) of closely related Python files.
    *   **Cohesion is Key:** Files should group highly cohesive functionality.
    *   **Rough Size Heuristics (evolvable):**
        *   Individual functions/methods: Strive for clarity and single responsibility. If a function exceeds ~50-75 lines (excluding comments/docstrings), consider if it can be broken down.
        *   Classes: Should represent a clear abstraction. If a class has too many methods covering disparate concerns, or manages too much unrelated state, consider refactoring.
        *   Test files: If a test file for a single module becomes excessively long (e.g., >20-30 individual test functions or >500-700 lines), it might indicate the module under test is too complex or that tests could be better organized (e.g., using test classes, parametrization).
    *   **"Working Memory" Check:** Can we (human and AI) reasonably hold the core requirements, the code of the current unit, its direct dependency interfaces, and the immediate test plan in mind without getting lost? If not, the unit might be too large.

3.  **Regular "Complexity Retrospectives" (Optional but Recommended):**
    *   Periodically (e.g., after completing 2-4 modules, or at natural project milestones), briefly discuss:
        *   "Did any recent module feel too complex or take unexpectedly long due to its size/scope?"
        *   "Are our heuristics for 'too complex' still appropriate, or do they need adjustment based on our experience?"
        *   "Are there opportunities to refactor existing larger modules into smaller ones?"

## Goal

The goal is not to rigidly enforce arbitrary limits but to use these as triggers for discussion and proactive decomposition, leading to a more manageable and maintainable codebase.

---