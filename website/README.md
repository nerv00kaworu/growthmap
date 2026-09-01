# GrowthMap public website

This directory contains the deployed public site for <https://growthmap.work>. It presents the current Windows Personal release, product boundaries, activation information, and public documentation. It is separate from desktop packaging.

## Public-site contract

- Project data remains in the desktop's local SQLite workspace; the public website does not receive desktop project databases.
- Activation concerns licensing-related data only; it is not a project-data sync service.
- Current download evidence is defined in `content/release.ts` and must match the published release exactly.
- The installer is unsigned and updates are manual. Public copy must tell users to verify filename, size, and SHA-256 and stop on any warning or mismatch; it must never advise bypassing Windows security.
- Legal and product copy is factual public information, not legal advice or a promise of uninterrupted service/data retention.

## Commands

```sh
cd website
npm ci
npm test
npm run typecheck
npm run lint
npm run build
```

Use the current release page and root README as public release references. Do not place infrastructure, credentials, internal deployment paths, or private operational details in this directory's documentation.
