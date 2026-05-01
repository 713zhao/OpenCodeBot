<!-- SYNC IMPACT REPORT
Version change: (none) → 1.0.0
Initial constitution creation — all placeholder tokens replaced with concrete values.

Modified principles: N/A (initial creation)

Added sections:
  - Core Principles (5 principles defined)
  - Development Standards
  - Development Workflow
  - Governance

Removed sections: N/A

Templates reviewed:
  - .specify/templates/plan-template.md      ✅ aligned — Constitution Check section present
  - .specify/templates/spec-template.md      ✅ aligned — functional requirements + edge cases present
  - .specify/templates/tasks-template.md     ✅ aligned — test-before-implementation pattern present
  - .specify/templates/checklist-template.md ✅ aligned — no principle-specific updates needed

Follow-up TODOs: None — all placeholders resolved.
-->

# opencoding Constitution

## Core Principles

### I. Python Expertise

Use idiomatic, modern Python (3.11+). All code MUST comply with PEP 8 (style), PEP 20 (Zen of
Python), and PEP 257 (docstrings). Type hints MUST be used throughout — including function
signatures and class attributes. Prefer standard library solutions before reaching for
third-party packages; every external dependency MUST be explicitly justified.

### II. Deep Thinking Before Acting

Before writing any code, thoroughly analyze requirements, edge cases, failure modes, and design
trade-offs. Reasoning MUST be documented in specs and plans. Jumping straight to implementation
without understanding the full problem space is prohibited. Phase 0 research and Phase 1 design
are non-negotiable steps in the implementation workflow.

### III. Test-Before-Delivery (NON-NEGOTIABLE)

Every deliverable MUST have tests written or updated before the implementation is considered
complete. Use pytest. Tests MUST cover: happy path, edge cases, and error conditions. No feature
is "done" without passing tests. TDD (Test-Driven Development) is strongly encouraged — write
tests first when possible (Red-Green-Refactor). A feature with untested code MUST NOT be merged.

### IV. Code Quality

Keep functions small and single-purpose. Prefer composition over inheritance. Avoid global state.
Handle errors explicitly with informative messages. Functions MUST do one thing; if a function
spans more than ~30 lines, it is a candidate for decomposition. Complexity MUST be justified —
every abstraction layer added requires an explicit rationale documented in the plan.

### V. Security

Validate all external inputs at system boundaries (CLI args, API payloads, file contents, env
vars). Never hardcode credentials, tokens, or secrets in source code. Use environment variables
for secrets, managed via a `.env` file (excluded from VCS) or a secrets manager. Treat all
external data as untrusted until validated.

## Development Standards

**Language**: Python 3.11+
**Style**: PEP 8 enforced via `ruff` or `flake8`; formatting via `black` or `ruff format`
**Type checking**: `mypy` in strict mode
**Testing**: `pytest` with `pytest-cov`; minimum 80% line coverage on new code
**Dependency management**: `pip` with `pyproject.toml`; third-party packages MUST be pinned to
exact or compatible versions
**Secrets**: `python-dotenv` for local `.env` loading; `.env` MUST be listed in `.gitignore`
**Linting**: All CI runs MUST pass lint and type-check gates before merge

## Development Workflow

1. **Spec first**: Create a spec (`/speckit.specify`) before planning or coding.
2. **Plan before implement**: Run `/speckit.plan` to research, design, and produce a task list.
3. **Constitution check**: Every plan MUST verify compliance with all five core principles before
   Phase 0 research begins and again after Phase 1 design.
4. **TDD cycle**: Write failing tests → implement → make tests pass → refactor.
5. **Code review**: All PRs MUST be reviewed for principle compliance before merge.
6. **No skipping gates**: Complexity violations MUST be documented in the plan's Complexity
   Tracking table with explicit justification.

## Governance

This constitution supersedes all other development practices for the opencoding project.
Amendments require:

1. A written proposal describing the change, motivation, and impact on existing code.
2. A version increment following the semantic versioning rules below.
3. A migration plan if existing code violates the amended principle.
4. An update to this file including a revised Sync Impact Report comment.

**Versioning policy**:
- **MAJOR**: Backward-incompatible governance changes, principle removals, or redefinitions that
  invalidate previously compliant code.
- **MINOR**: New principle, section, or materially expanded guidance added.
- **PATCH**: Clarifications, wording fixes, or non-semantic refinements.

**Compliance review**: All PRs and agent-driven development sessions MUST verify adherence to
the five Core Principles. Use `.specify/memory/constitution.md` as the authoritative reference.

**Version**: 1.0.0 | **Ratified**: 2026-05-01 | **Last Amended**: 2026-05-01
