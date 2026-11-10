"""
Automated tests for the BNPL SQL project.

Run from the project folder:
    python -m unittest discover -s tests -v

Only the Python standard library is used (unittest + sqlite3).
"""
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import run_queries  # noqa: E402
import seed  # noqa: E402


def dump_tables(conn):
    """Returns every row of every table, so two databases can be compared."""
    tables = ("customers", "merchants", "orders", "installments")
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables}


class DatabaseTestCase(unittest.TestCase):
    """Builds ONE fresh database for all the tests in the class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "test.db"
        seed.create_database(cls.db_path, verbose=False)
        cls.conn = sqlite3.connect(cls.db_path)
        cls.conn.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def scalar(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]


class TestGeneratedData(DatabaseTestCase):
    """The fictional data must be complete and consistent."""

    def test_expected_row_counts(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM customers"), seed.N_CUSTOMERS)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM merchants"), len(seed.MERCHANTS))
        self.assertGreater(self.scalar("SELECT COUNT(*) FROM orders"), 0)

    def test_every_order_has_exactly_four_installments(self):
        wrong = self.query(
            "SELECT order_id FROM installments GROUP BY order_id HAVING COUNT(*) != 4"
        )
        self.assertEqual(wrong, [])
        orders = self.scalar("SELECT COUNT(*) FROM orders")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM installments"), 4 * orders)

    def test_installments_add_up_to_the_order_total(self):
        wrong = self.query(
            """SELECT o.order_id FROM orders o JOIN installments i ON i.order_id = o.order_id
               GROUP BY o.order_id HAVING ABS(o.total_amount - SUM(i.amount)) > 0.01"""
        )
        self.assertEqual(wrong, [])

    def test_no_foreign_key_violations(self):
        self.assertEqual(self.query("PRAGMA foreign_key_check"), [])

    def test_orders_happen_after_signup_and_before_the_reference_date(self):
        too_early = self.scalar(
            """SELECT COUNT(*) FROM orders o JOIN customers c ON c.customer_id = o.customer_id
               WHERE o.order_date < c.signup_date"""
        )
        too_late = self.scalar(
            "SELECT COUNT(*) FROM orders WHERE order_date >= ?", (seed.REFERENCE_DATE.isoformat(),)
        )
        self.assertEqual(too_early, 0)
        self.assertEqual(too_late, 0)

    def test_nothing_is_paid_before_the_order_or_in_the_future(self):
        before_order = self.scalar(
            """SELECT COUNT(*) FROM installments i JOIN orders o ON o.order_id = i.order_id
               WHERE i.paid_date < o.order_date"""
        )
        in_future = self.scalar(
            "SELECT COUNT(*) FROM installments WHERE paid_date > ?", (seed.REFERENCE_DATE.isoformat(),)
        )
        self.assertEqual(before_order, 0)
        self.assertEqual(in_future, 0)

    def test_first_installment_is_never_late(self):
        late_first = self.scalar(
            "SELECT COUNT(*) FROM installments WHERE installment_number = 1 AND status != 'paid'"
        )
        self.assertEqual(late_first, 0)

    def test_installments_are_14_days_apart(self):
        rows = self.query(
            """SELECT o.order_date, i.installment_number, i.due_date
               FROM installments i JOIN orders o ON o.order_id = i.order_id"""
        )
        for order_date, number, due_date in rows:
            expected = date.fromisoformat(order_date).toordinal() + 14 * (number - 1)
            self.assertEqual(date.fromisoformat(due_date).toordinal(), expected)

    def test_status_matches_the_dates(self):
        today = seed.REFERENCE_DATE.isoformat()
        for installment_id, due, paid, status in self.query(
            "SELECT installment_id, due_date, paid_date, status FROM installments"
        ):
            with self.subTest(installment_id=installment_id):
                if status == "pending":
                    self.assertGreater(due, today)
                    self.assertIsNone(paid)
                elif status == "overdue":
                    self.assertLessEqual(due, today)
                    self.assertIsNone(paid)
                elif status == "paid":
                    self.assertIsNotNone(paid)
                    self.assertLessEqual(due, today)
                elif status == "paid_late":
                    self.assertIsNotNone(paid)
                    self.assertGreater(paid, due)
                    self.assertLessEqual(paid, today)
                else:
                    self.fail(f"unexpected status {status!r}")


class TestDeterminism(unittest.TestCase):
    def test_two_runs_generate_exactly_the_same_data(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / "a.db", Path(folder) / "b.db"
            seed.create_database(first, verbose=False)
            seed.create_database(second, verbose=False)
            conn_a, conn_b = sqlite3.connect(first), sqlite3.connect(second)
            try:
                self.assertEqual(dump_tables(conn_a), dump_tables(conn_b))
            finally:
                conn_a.close()
                conn_b.close()


class TestSchemaConstraints(DatabaseTestCase):
    """Bad data must be rejected by the database itself."""

    def test_rejects_an_invalid_installment_status(self):
        # Everything in this row is valid EXCEPT the status, so only the status rule can reject it.
        # (The new order is rolled back at the end, so it does not affect the other tests.)
        self.addCleanup(self.conn.rollback)
        order_id = self.conn.execute(
            "INSERT INTO orders (customer_id, merchant_id, order_date, total_amount) "
            "VALUES (1, 1, '2026-01-01', 100)"
        ).lastrowid
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO installments (order_id, installment_number, due_date, amount, status) "
                "VALUES (?, 1, '2026-01-01', 25, 'banana')",
                (order_id,),
            )

    def test_rejects_an_installment_number_outside_1_to_4(self):
        self.addCleanup(self.conn.rollback)
        order_id = self.conn.execute(
            "INSERT INTO orders (customer_id, merchant_id, order_date, total_amount) "
            "VALUES (1, 1, '2026-01-01', 100)"
        ).lastrowid
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO installments (order_id, installment_number, due_date, amount, status) "
                "VALUES (?, 9, '2026-01-01', 25, 'pending')",
                (order_id,),
            )

    def test_rejects_an_order_with_a_negative_amount(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO orders (customer_id, merchant_id, order_date, total_amount) "
                "VALUES (1, 1, '2026-01-01', -5)"
            )

    def test_rejects_an_order_from_a_customer_that_does_not_exist(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO orders (customer_id, merchant_id, order_date, total_amount) "
                "VALUES (999999, 1, '2026-01-01', 50)"
            )

    def test_rejects_a_duplicate_installment_number(self):
        order_id = self.scalar("SELECT order_id FROM installments LIMIT 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO installments (order_id, installment_number, due_date, amount, status) "
                "VALUES (?, 1, '2026-01-01', 10, 'pending')",
                (order_id,),
            )


class TestQueries(DatabaseTestCase):
    """Every query in queries.sql must run, and the known answers must stay the same."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        text = (PROJECT_DIR / "queries.sql").read_text(encoding="utf-8")
        cls.queries = {q["id"]: q for q in run_queries.load_queries(text)}

    def run_query(self, query_id):
        return self.conn.execute(self.queries[query_id]["sql"]).fetchall()

    def test_all_15_queries_are_found(self):
        self.assertEqual(sorted(self.queries), [f"Q{n:02d}" for n in range(1, 16)])

    def test_every_query_runs_without_errors(self):
        for query_id in self.queries:
            with self.subTest(query=query_id):
                self.conn.execute(self.queries[query_id]["sql"]).fetchall()

    def test_data_quality_queries_return_no_rows(self):
        self.assertEqual(self.run_query("Q14"), [])
        self.assertEqual(self.run_query("Q15"), [])

    def test_overview_matches_the_raw_tables(self):
        customers, orders, gmv, avg_order = self.run_query("Q01")[0]
        self.assertEqual(orders, self.scalar("SELECT COUNT(*) FROM orders"))
        self.assertEqual(customers, self.scalar("SELECT COUNT(DISTINCT customer_id) FROM orders"))
        self.assertAlmostEqual(gmv, self.scalar("SELECT SUM(total_amount) FROM orders"), places=1)
        self.assertAlmostEqual(avg_order, gmv / orders, places=1)

    def test_monthly_sales_add_up_to_the_total(self):
        monthly_total = sum(row[2] for row in self.run_query("Q02"))
        self.assertAlmostEqual(monthly_total, self.run_query("Q01")[0][2], delta=1.0)

    def test_running_total_ends_at_the_total_gmv(self):
        last_running_total = self.run_query("Q03")[-1][2]
        self.assertAlmostEqual(last_running_total, self.run_query("Q01")[0][2], delta=1.0)

    def test_merchant_shares_never_exceed_100_percent(self):
        shares = [row[4] for row in self.run_query("Q04")]
        self.assertLessEqual(sum(shares), 100.0 + 0.5)
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_late_rate_matches_a_python_calculation(self):
        today = seed.REFERENCE_DATE.isoformat()
        rows = self.query("SELECT status FROM installments WHERE due_date <= ?", (today,))
        late = sum(1 for (status,) in rows if status in ("paid_late", "overdue"))
        expected = round(100.0 * late / len(rows), 2)

        due, late_sql, rate, _ = self.run_query("Q06")[0]
        self.assertEqual(due, len(rows))
        self.assertEqual(late_sql, late)
        self.assertEqual(rate, expected)

    def test_the_first_installment_has_a_zero_late_rate(self):
        by_number = {row[0]: row[2] for row in self.run_query("Q08")}
        self.assertEqual(by_number[1], 0.0)
        self.assertTrue(all(by_number[n] > 0 for n in (2, 3, 4)))

    def test_risk_flag_only_returns_customers_above_the_threshold(self):
        for _, _, due, late, rate in self.run_query("Q11"):
            self.assertGreaterEqual(due, 4)
            self.assertGreaterEqual(rate, 30.0)
            self.assertLessEqual(late, due)

    def test_repeat_customer_segments_add_up_to_100_percent(self):
        rows = self.run_query("Q12")
        self.assertEqual(sum(r[1] for r in rows), seed.N_CUSTOMERS)
        self.assertAlmostEqual(sum(r[2] for r in rows), 100.0, delta=0.2)

    def test_known_results_for_the_default_seed(self):
        """Regression test: if these change, the data or a query changed."""
        self.assertEqual(self.run_query("Q01")[0], (300, 784, 142264.63, 181.46))
        due, late, rate, overdue_amount = self.run_query("Q06")[0]
        self.assertEqual((due, late, rate), (2823, 135, 4.78))


class TestQueryParser(unittest.TestCase):
    def test_splits_blocks_and_keeps_descriptions_apart_from_sql(self):
        text = (
            "-- header comment\n\n"
            "-- Q01. First question\n"
            "-- Some description\n"
            "SELECT 1;\n\n"
            "-- Q02. Second question\n"
            "SELECT 2\nFROM t;\n"
        )
        queries = run_queries.load_queries(text)
        self.assertEqual([q["id"] for q in queries], ["Q01", "Q02"])
        self.assertEqual(queries[0]["title"], "First question")
        self.assertEqual(queries[0]["desc"], ["Some description"])
        self.assertEqual(queries[0]["sql"], "SELECT 1;")
        self.assertEqual(queries[1]["sql"], "SELECT 2\nFROM t;")


if __name__ == "__main__":
    unittest.main()
