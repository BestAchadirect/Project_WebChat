from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings


COPY_START_RE = re.compile(r"^COPY\s+.+\sFROM\s+stdin;$", re.IGNORECASE)
COPY_SCHEMA_RE = re.compile(r'^COPY\s+"?(?P<schema>[\w]+)"?\."?(?P<table>[\w]+)"?\s*\(', re.IGNORECASE)


def _execute_buffer(cursor, buffer: list[str]) -> None:
    statement = "".join(buffer).strip()
    buffer.clear()
    if statement:
        cursor.execute(statement)


def import_dump(dump_path: Path, dsn: str, skip_schemas: set[str]) -> None:
    if not dump_path.is_file():
        raise FileNotFoundError(f"Dump file not found: {dump_path}")

    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = False
        with conn.cursor() as cursor:
            sql_buffer: list[str] = []
            in_copy = False
            skip_copy = False
            copy_sql = ""
            copy_temp_path: str | None = None
            copy_temp_handle = None
            copy_count = 0
            skipped_copy_count = 0

            with dump_path.open("r", encoding="utf-8", newline="") as dump_file:
                for raw_line in dump_file:
                    line = raw_line

                    if in_copy:
                        if line.strip() == r"\.":
                            if not skip_copy:
                                assert copy_temp_path is not None
                                assert copy_temp_handle is not None
                                copy_temp_handle.flush()
                                copy_temp_handle.seek(0)
                                cursor.copy_expert(copy_sql, copy_temp_handle)
                                copy_temp_handle.close()
                                os.remove(copy_temp_path)
                                copy_temp_path = None
                                copy_temp_handle = None
                                copy_count += 1
                            else:
                                skipped_copy_count += 1
                            in_copy = False
                            skip_copy = False
                            copy_sql = ""
                        else:
                            if not skip_copy:
                                assert copy_temp_path is not None
                                assert copy_temp_handle is not None
                                copy_temp_handle.write(line)
                        continue

                    stripped = line.strip()
                    if not stripped or stripped.startswith("--"):
                        continue

                    if COPY_START_RE.match(stripped):
                        _execute_buffer(cursor, sql_buffer)
                        schema_match = COPY_SCHEMA_RE.match(stripped)
                        schema_name = schema_match.group("schema") if schema_match else ""
                        skip_copy = schema_name in skip_schemas
                        in_copy = True
                        copy_sql = stripped
                        if not skip_copy:
                            handle = tempfile.NamedTemporaryFile(
                                mode="w+",
                                encoding="utf-8",
                                newline="",
                                delete=False,
                            )
                            copy_temp_path = handle.name
                            copy_temp_handle = handle
                        continue

                    sql_buffer.append(line)
                    if stripped.endswith(";"):
                        _execute_buffer(cursor, sql_buffer)

            _execute_buffer(cursor, sql_buffer)
            conn.commit()
            print(f"Imported dump from {dump_path} into {dsn}")
            print(f"Applied {copy_count} COPY blocks")
            if skipped_copy_count:
                print(f"Skipped {skipped_copy_count} COPY blocks for schemas: {', '.join(sorted(skip_schemas))}")
    except Exception:
        if copy_temp_handle is not None and not copy_temp_handle.closed:
            copy_temp_handle.close()
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a Supabase pg_dump file into the local database.")
    parser.add_argument(
        "--dump",
        type=Path,
        default=Path("..") / "supabase" / "data.sql",
        help="Path to the pg_dump data file.",
    )
    parser.add_argument(
        "--dsn",
        default=settings.DATABASE_URL,
        help="PostgreSQL DSN for the destination database.",
    )
    parser.add_argument(
        "--skip-schema",
        action="append",
        default=["storage"],
        help="Schema to skip while importing COPY blocks. Can be provided multiple times.",
    )
    args = parser.parse_args()

    import_dump(args.dump.resolve(), args.dsn, set(args.skip_schema))


if __name__ == "__main__":
    main()
