# GrowthMap manual payments v1 operator runbook

Status: candidate. This flow intentionally performs no automatic PayPal or chain settlement.

## Public purchase settings

- Issuer: `Growthmap`
- Base network: `eip155:8453` (Base mainnet)
- Asset: Circle native USDC `0x833589fCD6eDb6E08f4C7C32D4f71b54bdA02913`
- Recipient: `0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591`
- PayPal: `https://www.paypal.com/ncp/payment/R2M3YAQJNNCZA`
- Contact: `nerv00kaworu@gmail.com`, `https://x.com/nerv00kaworu`
- First 50 globally payment-confirmed licenses: 10 USDC / USD 10. Later licenses: 29 USDC / USD 29.

## Buyer submission

Ask for order ID, rail, PayPal transaction ID or Base transaction hash, license display name, and contact email. Screenshots are never payment evidence. Never ask for a wallet private key, seed phrase, PayPal password, or signing key.

## Base verification

Before confirmation, independently inspect a final Base transaction and record:

1. Chain ID is 8453.
2. Token contract is the exact Circle native USDC address above.
3. Recipient is the exact configured address.
4. Amount exactly matches the order's current tier; token decimals are 6.
5. Transaction succeeded and has sufficient finality under the operator policy.
6. Transaction hash has never been used for another order.
7. Sender/reference and observed UTC time are recorded in the private operator evidence.

Do not accept ETH, bridged/wrapped USDC, a different network, a screenshot, or a block-explorer URL without checking the underlying transaction.

## PayPal verification

Open PayPal independently. Match the submitted transaction ID, Goods & Services/commercial payment status, `COMPLETED`, exact USD amount, intended payee, and payer/reference. Reject screenshots and pending/reversed/refunded payments. A transaction ID may confirm only one order.

## Issuance

Use the issuer tool on a trusted offline/operator machine. The Ed25519 private key, settlement MAC key and checkpoint must live outside the repository/workspace and must never be pasted into chat, logged, bundled, emailed, or copied into the desktop database. Confirming an order atomically allocates the next sale ordinal and signs the License JSON. Deliver only the License JSON and retain the recovery code through a private channel.

The approved local operator paths for this installation are:

- Private signing key: `~/.local/share/growthmap-secrets/license-signing-private.pem` (mode 0600)
- Public signing key backup: `~/.local/share/growthmap-secrets/license-signing-public.pem`
- Settlement MAC key: `~/.local/share/growthmap-secrets/settlement-mac-key.bin` (mode 0600)
- Production ledger: `~/.local/share/growthmap-secrets/manual-payments.sqlite`
- External authenticated checkpoint: `~/.local/share/growthmap-secrets/manual-payments.checkpoint.json`

The packaged public key SHA-256 is `1b2050b8b416261e54d748b752f3e8aa6d4c30276378a5ea77dc07ab7d18fab6`. Before every issuance session, verify this hash against `src/backend/desktop/license_public_key.pem`. The production ledger/checkpoint are intentionally not initialized by a smoke test; the first real order creates them together under the issuer service's fail-closed checkpoint protocol.

## Refunds and revocation

Never delete ledger evidence. Record refund/chargeback, issue the signed revocation assertion, and deliver/import it or make it available at the next authenticated check-in. Offline copies remain usable until they receive verified revocation/check-in evidence; this limitation must be disclosed.

## Backup and incident response

Use SQLite online backup or quiesce writes; preserve DB/WAL consistently. Back up the encrypted issuer DB, external MAC key, checkpoint and Ed25519 private key separately. Loss of the private key prevents re-signing; loss of MAC/checkpoint may fail closed. If any trust material is suspected exposed, stop issuance immediately and do not improvise a new key without a reviewed migration plan.
