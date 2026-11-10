-- ============================================================
-- BNPL (pay in 4) analytics: SQL queries
-- Database: SQLite  |  All data is fictional (see seed.py)
--
-- Reference date used in the queries: 2026-11-01 ("today" for the data).
-- Run everything with:  python run_queries.py
-- ============================================================


-- Q01. Business overview
-- How many customers bought, how many orders, total sales (GMV) and average order value?
SELECT
    COUNT(DISTINCT customer_id)        AS customers_with_orders,
    COUNT(*)                           AS orders,
    ROUND(SUM(total_amount), 2)        AS gmv,
    ROUND(AVG(total_amount), 2)        AS avg_order_value
FROM orders;


-- Q02. Sales by month
-- GROUP BY + date functions: orders, GMV and average order value per month.
SELECT
    strftime('%Y-%m', order_date)      AS month,
    COUNT(*)                           AS orders,
    ROUND(SUM(total_amount), 2)        AS gmv,
    ROUND(AVG(total_amount), 2)        AS avg_order_value
FROM orders
GROUP BY month
ORDER BY month;


-- Q03. Running total and month-over-month growth
-- CTE + window functions (SUM OVER, LAG) to see how sales evolve.
WITH monthly AS (
    SELECT strftime('%Y-%m', order_date) AS month,
           SUM(total_amount)             AS gmv
    FROM orders
    GROUP BY month
)
SELECT
    month,
    ROUND(gmv, 2)                                              AS gmv,
    ROUND(SUM(gmv) OVER (ORDER BY month), 2)                   AS running_gmv,
    ROUND(100.0 * (gmv - LAG(gmv) OVER (ORDER BY month))
                / LAG(gmv) OVER (ORDER BY month), 1)           AS mom_growth_pct
FROM monthly
ORDER BY month;


-- Q04. Top 10 merchants and their share of total sales
-- JOIN + GROUP BY + a window function over an aggregate for the percentage.
SELECT
    m.name,
    m.category,
    COUNT(*)                                                   AS orders,
    ROUND(SUM(o.total_amount), 2)                              AS gmv,
    ROUND(100.0 * SUM(o.total_amount)
                / SUM(SUM(o.total_amount)) OVER (), 1)         AS share_pct
FROM orders o
JOIN merchants m ON m.merchant_id = o.merchant_id
GROUP BY m.merchant_id
ORDER BY gmv DESC
LIMIT 10;


-- Q05. Sales by merchant category
-- Which categories bring more volume, and which have the biggest baskets?
SELECT
    m.category,
    COUNT(*)                           AS orders,
    ROUND(SUM(o.total_amount), 2)      AS gmv,
    ROUND(AVG(o.total_amount), 2)      AS avg_order_value
FROM orders o
JOIN merchants m ON m.merchant_id = o.merchant_id
GROUP BY m.category
ORDER BY gmv DESC;


-- Q06. Late payment rate (overall)
-- Only installments whose due date has already passed are counted.
-- "Late" = paid after the due date OR still unpaid (overdue).
SELECT
    COUNT(*)                                                           AS installments_due,
    SUM(CASE WHEN status IN ('paid_late', 'overdue') THEN 1 ELSE 0 END) AS late_installments,
    ROUND(100.0 * SUM(CASE WHEN status IN ('paid_late', 'overdue') THEN 1 ELSE 0 END)
                / COUNT(*), 2)                                         AS late_rate_pct,
    ROUND(SUM(CASE WHEN status = 'overdue' THEN amount ELSE 0 END), 2) AS overdue_amount
FROM installments
WHERE due_date <= '2026-11-01';


-- Q07. Late rate by due month
-- Is the late rate getting better or worse over time?
SELECT
    strftime('%Y-%m', due_date)                                        AS due_month,
    COUNT(*)                                                           AS installments_due,
    SUM(CASE WHEN status IN ('paid_late', 'overdue') THEN 1 ELSE 0 END) AS late_installments,
    ROUND(100.0 * SUM(CASE WHEN status IN ('paid_late', 'overdue') THEN 1 ELSE 0 END)
                / COUNT(*), 2)                                         AS late_rate_pct
FROM installments
WHERE due_date <= '2026-11-01'
GROUP BY due_month
ORDER BY due_month;


-- Q08. Late rate by installment number
-- Installment 1 is paid at checkout, so it should never be late. Do the others differ?
SELECT
    installment_number,
    COUNT(*)                                                           AS installments_due,
    ROUND(100.0 * SUM(CASE WHEN status IN ('paid_late', 'overdue') THEN 1 ELSE 0 END)
                / COUNT(*), 2)                                         AS late_rate_pct
FROM installments
WHERE due_date <= '2026-11-01'
GROUP BY installment_number
ORDER BY installment_number;


-- Q09. How late are the late payments?
-- julianday() turns dates into numbers, so we can subtract them.
SELECT
    COUNT(*)                                                                   AS late_paid_installments,
    ROUND(AVG(julianday(paid_date) - julianday(due_date)), 1)                  AS avg_days_late,
    CAST(MAX(julianday(paid_date) - julianday(due_date)) AS INTEGER)           AS max_days_late
FROM installments
WHERE status = 'paid_late';


-- Q10. Customers with the most unpaid (overdue) installments
-- Three-table JOIN + HAVING to keep only customers with 2 or more overdue installments.
SELECT
    c.customer_id,
    c.name,
    c.city,
    COUNT(*)                       AS overdue_installments,
    ROUND(SUM(i.amount), 2)        AS overdue_amount
FROM installments i
JOIN orders    o ON o.order_id    = i.order_id
JOIN customers c ON c.customer_id = o.customer_id
WHERE i.status = 'overdue'
GROUP BY c.customer_id
HAVING COUNT(*) >= 2
ORDER BY overdue_amount DESC
LIMIT 15;


-- Q11. Risk flag: customers who are late too often
-- CTE computes each customer's late rate; the outer query keeps the risky ones.
-- (A simple rule-based flag, the kind of signal a fraud or credit team would review.)
WITH customer_risk AS (
    SELECT
        c.customer_id,
        c.name,
        COUNT(*)                                                           AS installments_due,
        SUM(CASE WHEN i.status IN ('paid_late', 'overdue') THEN 1 ELSE 0 END) AS late_installments
    FROM installments i
    JOIN orders    o ON o.order_id    = i.order_id
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE i.due_date <= '2026-11-01'
    GROUP BY c.customer_id
)
SELECT
    customer_id,
    name,
    installments_due,
    late_installments,
    ROUND(100.0 * late_installments / installments_due, 1) AS late_rate_pct
FROM customer_risk
WHERE installments_due >= 4
  AND 100.0 * late_installments / installments_due >= 30
ORDER BY late_rate_pct DESC, late_installments DESC
LIMIT 15;


-- Q12. Repeat customers
-- How many customers bought once, 2-3 times, or 4+ times?
WITH per_customer AS (
    SELECT customer_id, COUNT(*) AS n_orders
    FROM orders
    GROUP BY customer_id
)
SELECT
    CASE
        WHEN n_orders = 1              THEN '1 order'
        WHEN n_orders BETWEEN 2 AND 3  THEN '2-3 orders'
        ELSE '4+ orders'
    END                                                        AS segment,
    COUNT(*)                                                   AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)         AS pct_of_customers
FROM per_customer
GROUP BY segment
ORDER BY MIN(n_orders);


-- Q13. Signup cohorts
-- LEFT JOIN keeps customers who signed up but never bought.
SELECT
    strftime('%Y-%m', c.signup_date)                              AS signup_month,
    COUNT(DISTINCT c.customer_id)                                 AS customers,
    COUNT(o.order_id)                                             AS orders,
    ROUND(1.0 * COUNT(o.order_id) / COUNT(DISTINCT c.customer_id), 2) AS orders_per_customer
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.customer_id
GROUP BY signup_month
ORDER BY signup_month;


-- Q14. Data quality check: do the installments add up to the order total?
-- This query should return ZERO rows. If it returns rows, the data is inconsistent.
SELECT
    o.order_id,
    o.total_amount,
    ROUND(SUM(i.amount), 2) AS installments_total
FROM orders o
JOIN installments i ON i.order_id = o.order_id
GROUP BY o.order_id
HAVING ABS(o.total_amount - SUM(i.amount)) > 0.01;


-- Q15. Data quality check: installments paid before the order existed
-- This query should also return ZERO rows.
SELECT
    i.installment_id,
    i.order_id,
    o.order_date,
    i.paid_date
FROM installments i
JOIN orders o ON o.order_id = i.order_id
WHERE i.paid_date < o.order_date;
