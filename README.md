# GrowthMap

GrowthMap is a local-first visual project workspace for people and AI Agents. Shape ideas into trees, decisions, risks, tasks, and implementation evidence—while people retain control of the canonical project.

## Download GrowthMap Personal for Windows

- Official site: <https://growthmap.work>
- Current release: [growthmap-personal-v1-live-sync-20260901](https://github.com/nerv00kaworu/growthmap/releases/tag/growthmap-personal-v1-live-sync-20260901)
- Installer: `GrowthMap-Setup-0.1.0-desktop.2-x64.exe` (Windows x64)
- Size: `145385238` bytes
- SHA-256: `cc1a4e15a390b8b56773d531902617ee84c41526c6fedbcfd233b5960ba8b928`

The installer is unsigned. Windows may show Unknown Publisher or SmartScreen. Download only from the official site or linked release, verify the filename, byte size, and SHA-256 above, and **stop if a warning or hash does not match**. Do not disable or bypass Windows security features. Updates are manual: download a newer installer and install it over the existing app.

## What it does

- Visual project Tree and Graph: ideas, modules, tasks, decisions, risks, resources, notes, branches, and mainlines.
- AI Expand and Deepen suggestions, plus JSON backup and Markdown export.
- Production Personal activation for licensing-related data only.
- Live canonical collaboration: shared revisions and compare-and-swap (CAS) prevent stale writes; SSE journal events signal possible stale state but are not mutation truth or a cloud project database.

## Agent governance

Agent Access is a Windows-user, workspace-global master grant. It does **not** grant blanket project access: every operation must carry an explicit `project_id` and scoped intent. Use review-first proposals for judgment-sensitive work; Direct collaboration requires an explicit authorization. Agent Access does not grant filesystem, shell, Git, deployment, credential, or general network authority. See [Agent onboarding](website/content/whitepapers/growthmap-agent-llm-onboarding.md).

## Local data and privacy

Project SQLite data is local to the desktop workspace. The Production Activation API handles activation/license information, not desktop project databases. Back up local data before destructive work; retention is a design expectation, not a guarantee. Read [PRIVACY.md](PRIVACY.md), [EULA.md](EULA.md), and [SUPPORT.md](SUPPORT.md).

## Development and checks

Source contributors can inspect package-specific instructions in [src/backend/README.md](src/backend/README.md) and [website/README.md](website/README.md). Typical website checks:

```sh
cd website
npm test
npm run typecheck
npm run lint
npm run build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and the [current/historical documentation index](docs/README.md).
