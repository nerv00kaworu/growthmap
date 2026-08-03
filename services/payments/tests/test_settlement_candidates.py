"""Facilitator-accepted tx candidates are durable lookup hints, never paid evidence."""
import sqlite3

import pytest

from growthmap_payments.service import BASE_NETWORK, PaymentService
from test_payments import RECIPIENT, config

PAYER = "0x" + "2" * 40
TX = "0x" + "3" * 64
RESPONSE_HASH = "4" * 64


def prepared(tmp_path, name="candidate"):
    service = PaymentService(config(tmp_path / f"{name}.sqlite"))
    order = service.create_order("x402", f"{name}@e.test")
    intent = service.prepare_x402_intent(order["order_id"], f"proof-{name}", f"nonce-{name}", 10_000_000, PAYER)
    return service, order, intent


def test_candidate_is_durable_ambiguous_and_never_allocates_or_issues(tmp_path):
    service, order, intent = prepared(tmp_path)
    candidate = service.record_settlement_candidate(
        intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000,
        "payai.facilitator.accepted", RESPONSE_HASH,
    )
    assert candidate["tx_hash"] == TX and candidate["payer"] == PAYER
    with service._db() as db:
        assert db.execute("SELECT state FROM settlement_intents").fetchone()[0] == "ambiguous"
        row = db.execute("SELECT state,sale_ordinal,tx_hash FROM orders WHERE id=?", (order["order_id"],)).fetchone()
        assert tuple(row) == ("manual_review", None, None)
        assert db.execute("SELECT count(*) FROM payment_proofs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM entitlement_outbox").fetchone()[0] == 0
    restarted = PaymentService(service.config)
    with restarted._db() as db:
        assert tuple(db.execute("SELECT tx_hash,response_hash FROM settlement_candidates").fetchone()) == (TX, RESPONSE_HASH)


def test_candidate_exact_idempotency_and_conflicts_fail_closed(tmp_path):
    service, _, intent = prepared(tmp_path, "idempotent")
    args = (intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH)
    first = service.record_settlement_candidate(*args)
    second = service.record_settlement_candidate(*args)
    assert first["observed_at"] == second["observed_at"]
    for changed in (
        (intent["intent_id"], "0x" + "5" * 64, PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH),
        (intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000, "other.source", RESPONSE_HASH),
        (intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", "6" * 64),
    ):
        with pytest.raises(ValueError, match="conflicting settlement candidate"):
            service.record_settlement_candidate(*changed)


def test_candidate_binding_and_global_reuse_rejected(tmp_path):
    service, _, intent = prepared(tmp_path, "binding")
    invalid = [
        ("not-tx", PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH, "invalid settlement candidate"),
        (TX, "0x" + "7" * 40, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH, "binding mismatch"),
        (TX, PAYER, "eip155:1", 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH, "invalid settlement candidate"),
        (TX, PAYER, BASE_NETWORK, 1, "payai.facilitator.accepted", RESPONSE_HASH, "binding mismatch"),
    ]
    for tx, payer, network, amount, source, digest, pattern in invalid:
        with pytest.raises(ValueError, match=pattern):
            service.record_settlement_candidate(intent["intent_id"], tx, payer, network, amount, source, digest)

    service.record_settlement_candidate(intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH)
    other = service.create_order("x402", "other@e.test")
    other_intent = service.prepare_x402_intent(other["order_id"], "other-proof", "other-nonce", 10_000_000, PAYER)
    with pytest.raises(ValueError, match="already used"):
        service.record_settlement_candidate(other_intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", "8" * 64)


def test_candidate_rows_are_sql_immutable_and_checkpoint_authenticated(tmp_path):
    service, _, intent = prepared(tmp_path, "immutable")
    service.record_settlement_candidate(intent["intent_id"], TX, PAYER, BASE_NETWORK, 10_000_000, "payai.facilitator.accepted", RESPONSE_HASH)
    with service._db() as db:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            db.execute("UPDATE settlement_candidates SET tx_hash=?", ("0x" + "9" * 64,))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            db.execute("DELETE FROM settlement_candidates")
    with sqlite3.connect(service.config.db_path) as db:
        db.execute("DROP TRIGGER settlement_candidate_immutable")
        db.execute("UPDATE settlement_candidates SET tx_hash=?", ("0x" + "9" * 64,))
    with pytest.raises(RuntimeError, match="checkpoint/database mismatch"):
        PaymentService(service.config)
