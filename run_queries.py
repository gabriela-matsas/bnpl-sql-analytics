"""
Runs every query in queries.sql and prints the results as tables.

Usage:
    python run_queries.py          # runs all queries
    python run_queries.py Q06 Q10  # runs only the ones you list
"""
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "bnpl.db"
QUERIES_PATH = HERE / "queries.sql"
MAX_ROWS = 15


def load_queries(text: str):
    """Splits queries.sql into (id, title, description, sql) blocks."""
    queries, current = [], None
    for line in text.splitlines():
        header = re.match(r"^-- (Q\d+)\.\s*(.*)$", line)
        if header:
            if current:
                queries.append(current)
            current = {"id": header.group(1), "title": header.group(2), "desc": [], "sql": []}
        elif current is not None:
            if line.startswith("--") and not current["sql"]:
                current["desc"].append(line[2:].strip())
            elif line.strip() or current["sql"]:
                current["sql"].append(line)
    if current:
        queries.append(current)

    for query in queries:
        query["sql"] = "\n".join(query["sql"]).strip()
    return queries


def print_table(columns, rows):
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(str(col)), *(len(r[i]) for r in cells)) if cells else len(str(col))
              for i, col in enumerate(columns)]
    print("  " + "  ".join(str(col).ljust(widths[i]) for i, col in enumerate(columns)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in cells[:MAX_ROWS]:
        print("  " + "  ".join(row[i].ljust(widths[i]) for i in range(len(columns))))
    if len(cells) > MAX_ROWS:
        print(f"  ... ({len(cells) - MAX_ROWS} more rows)")


def main() -> None:
    if not DB_PATH.exists():
        print("Database not found. Creating it with seed.py...\n")
        subprocess.run([sys.executable, str(HERE / "seed.py")], check=True)
        print()

    wanted = {arg.upper() for arg in sys.argv[1:]}
    queries = load_queries(QUERIES_PATH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)

    for query in queries:
        if wanted and query["id"] not in wanted:
            continue
        print("=" * 78)
        print(f"{query['id']}. {query['title']}")
        for line in query["desc"]:
            print(f"   {line}")
        print()
        cursor = conn.execute(query["sql"])
        rows = cursor.fetchall()
        if not rows:
            print("  (no rows)")
        else:
            print_table([col[0] for col in cursor.description], rows)
        print()
    conn.close()


if __name__ == "__main__":
    main()
