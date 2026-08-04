# GrowthMap official website (Phase 1)

Independent Next.js product site. It is intentionally outside `src/frontend` and is not referenced by desktop packaging.

## Commands

```sh
cd website
npm install
npm run dev
npm test && npm run typecheck && npm run lint && npm run build
```

## Boundaries

- Public content and typed static release/order fixtures only; no production API, credentials, wallet, payment, activation, recovery, analytics, or deployment.
- Desktop project data stays local and is never sent to the website.
- `/buy` and `/order/[id]` are no-store offline/staging UX. The sole displayed key is explicitly test-only and appears only in the `key_ready` fixture.
- Candidate download metadata is documented but the CTA has no href and is disabled. This is **not a public release**.

## Environment

`NEXT_PUBLIC_CANONICAL_BASE` is optional, e.g. `https://example.invalid`. When absent, canonical URLs, sitemap entries, and public indexing are safely disabled. Configure production canonical and review legal copy only during an approved release/deploy process.

## Status

No deployment and no production payment/finality/Authority functionality are included or authorized in this phase.

## Standalone VPS run contract (template; do not deploy from this task)

The directory is self-contained and can be copied unchanged into a separate repository or `/srv/growthmap-website`. It has no parent-repository imports, scripts, runtime paths, or release-build dependency.

```sh
cd /srv/growthmap-website
cp .env.example /etc/growthmap-website.env   # set public canonical domain and loopback HOST/PORT
npm ci
npm run build
npm start
curl -fsS http://127.0.0.1:3000/api/health
```

`HOST` and `PORT` configure `npm start`; defaults bind to `127.0.0.1:3000`, suitable for a reverse proxy. `app/api/health` returns only static service liveness and does not check or disclose payment, order, activation, or Authority state.

Deployment templates are deliberately non-active:

- `deploy/growthmap-website.service.example` — systemd service template
- `deploy/nginx-growthmap.conf.example` — reverse-proxy template

Before a VPS deployment, provision a least-privilege `growthmap` user, restrict environment-file permissions, replace the example domain, configure TLS, review systemd hardening against installed Node/npm paths, and obtain release approval. This task does not deploy.
