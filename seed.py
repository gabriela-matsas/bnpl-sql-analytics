"""
Generates the FICTIONAL data for the BNPL (pay in 4) database.

Nothing here comes from a real company or real people: names, stores and
amounts are invented. The random seed is fixed, so everyone who runs this
script gets exactly the same database.

Usage:
    python seed.py
"""
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "bnpl.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# "Today" for the data. Fixed on purpose, so results never change between runs.
REFERENCE_DATE = date(2026, 11, 1)

SEED = 42
N_CUSTOMERS = 300

FIRST_NAMES = [
    "Ana", "Bruno", "Camila", "Daniel", "Eduarda", "Felipe", "Gabriel", "Helena",
    "Igor", "Julia", "Kaio", "Larissa", "Marcos", "Natalia", "Otavio", "Paula",
    "Rafael", "Sofia", "Thiago", "Vitoria",
]
LAST_INITIALS = "ABCDEFGHJLMNPRST"

CITIES = [
    "Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Porto Alegre",
    "Salvador", "Recife", "Fortaleza", "Brasilia", "Campinas",
]

# (name, category, popularity weight) -- all invented store names
MERCHANTS = [
    ("Moda Aurora", "Fashion", 10), ("Trilha Sports", "Sports", 8),
    ("Casa Bela", "Home", 9), ("Eletro Norte", "Electronics", 12),
    ("Brilho Cosmeticos", "Beauty", 9), ("Passo Certo Calcados", "Fashion", 7),
    ("TecnoMais", "Electronics", 11), ("Lar Doce Lar", "Home", 6),
    ("Fit Vida", "Sports", 5), ("Essencia Perfumaria", "Beauty", 6),
    ("Urban Jeans", "Fashion", 8), ("Smart Gadgets", "Electronics", 7),
    ("Moveis Prime", "Home", 4), ("Pedal Livre", "Sports", 3),
    ("Pele Viva", "Beauty", 5), ("Estilo Sul", "Fashion", 6),
    ("Casa & Cia", "Home", 5), ("Game Zone", "Electronics", 6),
    ("Corrida Total", "Sports", 4), ("Glow Studio", "Beauty", 4),
]

# Hidden customer behaviour (NOT stored in the database): probability that an
# installment is not paid on time. The SQL queries have to discover it.
RISK_PROFILES = [
    ("low", 0.70, 0.03),
    ("medium", 0.22, 0.12),
    ("high", 0.08, 0.35),
]


def random_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


def pick_risk_profile() -> float:
    """Returns the late-payment probability for a new customer."""
    roll, cumulative = random.random(), 0.0
    for _, weight, late_probability in RISK_PROFILES:
        cumulative += weight
        if roll <= cumulative:
            return late_probability
    return RISK_PROFILES[-1][2]


def build_installments(order_id, order_date, total, late_probability, installment_id):
    """Splits an order in 4 installments (one every 14 days) and decides how each one was paid."""
    base = round(total / 4, 2)
    amounts = [base, base, base, round(total - 3 * base, 2)]
    rows = []
    for number, amount in enumerate(amounts, start=1):
        due = order_date + timedelta(days=14 * (number - 1))
        paid_date, status = None, "pending"

        if due <= REFERENCE_DATE:
            # The first installment is paid at checkout, so it is never late.
            is_late = number > 1 and random.random() < late_probability
            if not is_late:
                paid_date = due - timedelta(days=random.randint(0, 3)) if number > 1 else due
                paid_date = max(paid_date, order_date)
                status = "paid"
            elif random.random() < 0.6:
                candidate = due + timedelta(days=random.randint(1, 20))
                if candidate <= REFERENCE_DATE:
                    paid_date, status = candidate, "paid_late"
                else:
                    status = "overdue"
            else:
                status = "overdue"

        rows.append((
            installment_id, order_id, number, due.isoformat(), amount,
            paid_date.isoformat() if paid_date else None, status,
        ))
        installment_id += 1
    return rows


def main() -> None:
    random.seed(SEED)

    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    # --- merchants ---
    merchant_rows = [(i, name, category) for i, (name, category, _) in enumerate(MERCHANTS, start=1)]
    merchant_weights = [weight for _, _, weight in MERCHANTS]
    conn.executemany("INSERT INTO merchants VALUES (?, ?, ?)", merchant_rows)

    # --- customers ---
    customers, late_probability_by_customer = [], {}
    for customer_id in range(1, N_CUSTOMERS + 1):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_INITIALS)}."
        signup = random_date(date(2025, 1, 1), date(2026, 9, 30))
        customers.append((customer_id, name, random.choice(CITIES), signup.isoformat()))
        late_probability_by_customer[customer_id] = pick_risk_profile()
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)

    # --- orders and installments ---
    orders, installments = [], []
    order_id, installment_id = 1, 1
    for customer_id, _, _, signup_iso in customers:
        signup = date.fromisoformat(signup_iso)
        n_orders = random.choices([1, 2, 3, 4, 5, 6, 8], weights=[30, 25, 18, 12, 8, 5, 2])[0]
        for _ in range(n_orders):
            order_date = random_date(signup, REFERENCE_DATE - timedelta(days=1))
            merchant_id = random.choices(range(1, len(MERCHANTS) + 1), weights=merchant_weights)[0]
            total = round(random.lognormvariate(5.0, 0.6), 2)   # typical ticket around R$ 150
            total = min(max(total, 40.0), 1500.0)
            orders.append((order_id, customer_id, merchant_id, order_date.isoformat(), total))
            rows = build_installments(
                order_id, order_date, total, late_probability_by_customer[customer_id], installment_id
            )
            installments.extend(rows)
            installment_id += len(rows)
            order_id += 1

    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
    conn.executemany("INSERT INTO installments VALUES (?, ?, ?, ?, ?, ?, ?)", installments)
    conn.commit()

    # --- quick sanity check ---
    for table in ("customers", "merchants", "orders", "installments"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:<13} {count:>6} rows")
    print(f"\nDatabase created at: {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
