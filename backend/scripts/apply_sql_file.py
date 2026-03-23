import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List

# Allow running as a script: `python scripts/apply_sql_file.py`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import engine


def _split_sql_statements(sql_text: str) -> List[str]:
    statements: List[str] = []
    current: List[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0

    while i < len(sql_text):
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < len(sql_text) else ""

        if in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            current.append(ch)
            if ch == "*" and nxt == "/":
                current.append(nxt)
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if not in_single and not in_double:
            if ch == "-" and nxt == "-":
                current.append(ch)
                current.append(nxt)
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                current.append(ch)
                current.append(nxt)
                in_block_comment = True
                i += 2
                continue

        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


def _should_skip_statement(statement: str) -> bool:
    normalized = " ".join(statement.strip().split()).lower()
    return normalized in {"begin", "commit", "rollback"}


async def apply_sql_file(sql_file: Path, dry_run: bool) -> None:
    if not sql_file.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_file}")

    sql_text = sql_file.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql_text)
    executable = [stmt for stmt in statements if not _should_skip_statement(stmt)]

    async with engine.begin() as conn:
        for index, statement in enumerate(executable, start=1):
            await conn.exec_driver_sql(statement)
            print(f"[{index}/{len(executable)}] executed")

        if dry_run:
            await conn.rollback()
            print("Dry-run complete: transaction rolled back.")
        else:
            print("SQL file applied successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a SQL file using backend DB connection settings.")
    parser.add_argument("sql_file", help="Path to .sql file to execute")
    parser.add_argument("--dry-run", action="store_true", help="Execute in a transaction and roll back")
    args = parser.parse_args()

    sql_path = Path(args.sql_file).resolve()
    asyncio.run(apply_sql_file(sql_path, dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()
