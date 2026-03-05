---
name: implementation-spec
description: "Converts an approved plan into an executable implementation spec: PR-sized phases, atomic tasks with acceptance criteria and tests, plus optional discovery tasks when repo specifics are unknown. No code."
---
# IMPLEMENTATION SPEC MODE

You are converting a **Plan Document into an executable implementation specification**.

## Instructions

- Do NOT write code
- Produce **PR-sized implementation phases**
- Tasks must be **atomic, explicit, and executable**
- If file paths or functions are unknown, include a **Discovery Phase**

## Output Requirements

### 1. Goal
- Short description of feature

### 2. Inputs
- Key decisions from plan
- Affected components

### 3. Implementation Plan

Split work into PRs (≤300 LOC preferred, ≤500 max)

---

### PR-0 (Discovery) [ONLY if needed]
- Goal: Identify exact files and patterns

Tasks:
- Search for related modules/services
- Identify existing patterns to follow
- Document file paths

---

### PR-1
- Goal: [describe]

Tasks:
- Explicit changes (file, function, behavior)
- Include validation rules

Acceptance Criteria:
- What must be true after this PR

Tests:
- Required tests

---

### PR-2
(same structure)

---

### PR-N
(same structure)

---

### 4. Files Affected
- List files (or expected files)

### 5. Dependencies
- Libraries, services, migrations

### 6. Risks
- Technical risks

### 7. Notes for Code Generation
- Important patterns to follow
- Naming conventions
- Constraints

## Rules

- No ambiguity
- No large PRs
- No missing steps
- Each PR must be independently testable
