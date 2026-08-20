"""Dependency-free adversarial tests for provider-selection DDL inspection."""
import sqlite3
import unittest

from db.schema_contract import provider_selection_contract_problem

INFO = [
    (0, "singleton_id", "INTEGER", 1, None, 1),
    (1, "provider_id", "VARCHAR(36)", 0, None, 0),
    (2, "selection_revision", "INTEGER", 1, "1", 0),
    (3, "updated_at", "DATETIME", 1, None, 0),
]
FKS = [(0, 0, "provider_configs", "provider_id", "id", "NO ACTION", "SET NULL", "NONE")]
REAL = """CREATE TABLE provider_selection (
 singleton_id INTEGER NOT NULL PRIMARY KEY,
 provider_id VARCHAR(36) REFERENCES provider_configs(id) ON DELETE SET NULL,
 selection_revision INTEGER NOT NULL DEFAULT 1,
 updated_at DATETIME NOT NULL,
 CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1),
 CONSTRAINT ck_provider_selection_revision_safe CHECK
   (selection_revision >= 1 AND selection_revision <= 9007199254740991)
)"""

def problem(sql):
    return provider_selection_contract_problem(INFO, FKS, sql)


class ProviderSelectionLexicalContract(unittest.TestCase):
    def test_sqlalchemy_like_and_handwritten_ddl_are_accepted(self):
        self.assertIsNone(problem(REAL))
        quoted = '''CREATE TABLE "provider_selection" (
          "singleton_id" INTEGER NOT NULL PRIMARY KEY,
          "provider_id" VARCHAR(36) REFERENCES "provider_configs" ("id") ON DELETE SET NULL,
          "selection_revision" INTEGER DEFAULT 1 NOT NULL,
          "updated_at" DATETIME NOT NULL,
          CONSTRAINT "ck_provider_selection_singleton" CHECK ([singleton_id] = 1),
          CONSTRAINT `ck_provider_selection_revision_safe` CHECK (`selection_revision` BETWEEN 1 AND 9007199254740991)
        )'''
        self.assertIsNone(problem(quoted))

    def test_quoted_identifier_cannot_forge_check_tokens(self):
        exploit = REAL.replace(
            "CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1),",
            'CONSTRAINT "ck_provider_selection_singleton check check(singleton_id = 1)" CHECK (singleton_id >= 1),',
        )
        self.assertEqual(problem(exploit), "sql lexical")

        # The fixture itself is executable but unsafe: absent the validator,
        # SQLite accepts a singleton_id that violates the required contract.
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE provider_configs (id VARCHAR(36) PRIMARY KEY)")
        connection.execute(exploit)
        connection.execute(
            "INSERT INTO provider_selection "
            "(singleton_id, provider_id, selection_revision, updated_at) "
            "VALUES (2, NULL, 1, '2026-08-20')"
        )
        self.assertEqual(connection.execute("SELECT singleton_id FROM provider_selection").fetchone(), (2,))
        connection.close()

    def test_quoted_identifiers_are_atomic_and_fail_closed(self):
        valid_names = ('"ck_provider_selection_singleton"',
                       '[ck_provider_selection_singleton]',
                       '`ck_provider_selection_singleton`')
        for quoted_name in valid_names:
            with self.subTest(valid=quoted_name):
                self.assertIsNone(problem(REAL.replace("ck_provider_selection_singleton", quoted_name)))

        invalid_names = (
            '"ck_provider_selection_singleton""escaped"',
            '[ck_provider_selection_singleton]]escaped]',
            '`ck_provider_selection_singleton``escaped`',
            '"ck_provider_selection_singleton check"',
            '[ck_provider_selection_singleton-check]',
            '`ck_provider_selection_singleton.check`',
        )
        for quoted_name in invalid_names:
            with self.subTest(invalid=quoted_name):
                sql = REAL.replace("ck_provider_selection_singleton", quoted_name)
                self.assertEqual(problem(sql), "sql lexical")

    def test_comment_and_literal_bait_cannot_supply_checks(self):
        unsafe = REAL.replace(
            "CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1),",
            "CHECK (singleton_id >= 1), -- CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1)\n",
        )
        self.assertEqual(problem(unsafe), "singleton check")
        block = REAL.replace(
            "CONSTRAINT ck_provider_selection_revision_safe CHECK\n   (selection_revision >= 1 AND selection_revision <= 9007199254740991)",
            "CHECK (selection_revision >= 0), /* CONSTRAINT ck_provider_selection_revision_safe CHECK (selection_revision BETWEEN 1 AND 9007199254740991) */",
        )
        self.assertEqual(problem(block), "revision check")
        literal = REAL.replace(
            "CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1),",
            "CHECK (singleton_id >= 1), CHECK ('CONSTRAINT ck_provider_selection_singleton CHECK (singleton_id = 1)' != ''),",
        )
        self.assertEqual(problem(literal), "singleton check")

    def test_unsafe_real_checks_remain_rejected_despite_comment_bait(self):
        unsafe = REAL.replace("singleton_id = 1", "singleton_id >= 1").replace(
            "selection_revision >= 1 AND selection_revision <= 9007199254740991",
            "selection_revision >= 0",
        ) + "\n/* CONSTRAINT ck_provider_selection_singleton CHECK(singleton_id=1); " \
            "CONSTRAINT ck_provider_selection_revision_safe CHECK(selection_revision BETWEEN 1 AND 9007199254740991) */"
        self.assertIsNotNone(problem(unsafe))

    def test_unterminated_comments_and_quotes_fail_closed(self):
        for suffix in (" /* bait", " -- ok then\n'open", ' "open', " `open", " [open"):
            self.assertEqual(problem(REAL + suffix), "sql lexical")


if __name__ == "__main__":
    unittest.main()
