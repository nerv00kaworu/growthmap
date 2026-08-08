# Gift License local candidate

This source-only candidate adds strict `GMG1.<gift UUID>.<32-char base64url secret>` activation capabilities. The raw claim secret is returned only by admin create/recovery rotation and is represented in the Authority database solely by a SHA-256 digest of the 192-bit CSPRNG secret. Public claim possession grants activation only; it grants no list, recovery, revoke, or device-management authority.

Default policy is explicit: personal, major 1, two devices, perpetual, 30-day check-in. Gift activations reuse the existing one-time Ed25519 device challenge and signed v2 certificate path, including external signer ceremony/anchor verification and the transactional seat ledger. Rotation consumes outstanding challenges; revocation deactivates devices and consumes requests/challenges.

## Production status

**BLOCKED_EXTERNAL.** `licensing.gift_api.create_candidate_app` requires an injected Authority and `AdminSessionVerifier`; `from_env` is intentionally blocked and does not accept a raw signing secret. Public deployment still requires reviewed external signer custody, rollback-resistant anchor/database, formal admin authentication/TLS, distributed rate limiting, monitoring/backups, and signed packaged Windows Gift E2E review.
