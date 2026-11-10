-- ============================================================
-- Schema for a small "buy now, pay later" (pay in 4) database.
-- All data in this project is FICTIONAL (see seed.py).
-- ============================================================
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS installments;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS merchants;
DROP TABLE IF EXISTS customers;

-- People who buy using installments
CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    city         TEXT NOT NULL,
    signup_date  TEXT NOT NULL            -- ISO date: YYYY-MM-DD
);

-- Stores where the purchases happen
CREATE TABLE merchants (
    merchant_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL
);

-- One row per purchase
CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers (customer_id),
    merchant_id   INTEGER NOT NULL REFERENCES merchants (merchant_id),
    order_date    TEXT NOT NULL,
    total_amount  REAL NOT NULL CHECK (total_amount > 0)
);

-- Each order is split in 4 installments, one every 14 days.
-- status:
--   paid       -> paid on or before the due date
--   paid_late  -> paid after the due date
--   overdue    -> due date has passed and it is still unpaid
--   pending    -> due date is still in the future
CREATE TABLE installments (
    installment_id      INTEGER PRIMARY KEY,
    order_id            INTEGER NOT NULL REFERENCES orders (order_id),
    installment_number  INTEGER NOT NULL CHECK (installment_number BETWEEN 1 AND 4),
    due_date            TEXT NOT NULL,
    amount              REAL NOT NULL CHECK (amount > 0),
    paid_date           TEXT,             -- NULL while unpaid
    status              TEXT NOT NULL CHECK (status IN ('paid', 'paid_late', 'overdue', 'pending')),
    UNIQUE (order_id, installment_number)
);

-- Indexes on the columns used most often in JOINs and filters
CREATE INDEX idx_orders_customer      ON orders (customer_id);
CREATE INDEX idx_orders_merchant      ON orders (merchant_id);
CREATE INDEX idx_orders_date          ON orders (order_date);
CREATE INDEX idx_installments_order   ON installments (order_id);
CREATE INDEX idx_installments_due     ON installments (due_date);
