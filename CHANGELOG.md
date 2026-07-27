# Changelog

All notable changes to the GrowthMap **authoring/editor** package are documented here.

## [0.1.0-authoring.1] - 2026-07-24

### Release boundary
- Declares GrowthMap as the authoring/editor package only.
- Excludes the split Abyss Bureau player Web/API runtime, gameplay release/replay tooling, player database, payment, PvP, runtime LLM, and runtime image generation.
- Excludes local databases, backups, logs, runtime state, historical player artifacts, and candidate artwork from release inputs.

### Changed
- Adds formal node authoring fields to the editor surface: description, rules, constraints, examples, questions, decision notes, workflow status, priority, confidence, and file paths.
- Enforces one `child_of` mainline per parent through shared API write logic plus SQLite protection for compatible databases.
- Normalizes legacy nullable fields at API output boundaries.
- Makes CORS an exact opt-in allowlist outside development/test and adds authoring deep-health readiness.
- Replaces unsafe launch behavior with a loopback-default launcher that refuses port collisions, dependency installation, and implicit database selection.

### Verification
- Frontend lint, typecheck, and production build pass.
- Backend compile and in-memory SQLite test suite pass.
- Launcher smoke test passes with an isolated temporary SQLite database.

### Known limitations
- Backend schema compatibility steps execute at startup against the explicitly selected `DATABASE_URL`; operators must retain a verified backup before upgrading an existing database.
- Automated tests use isolated in-memory SQLite and do not cover external AI provider integration.

### Upgrade note
- Provide an explicit `DATABASE_URL` before starting. Backend startup can apply lightweight schema compatibility steps to that database; take an operator-managed backup before upgrading an existing database.
