import argparse
import re
import sqlite3
import sys
from playvine.utils.AtomicSQL import AtomicSQL

"""
Add keys to key vault. File should have one KID:KEY per-line.
Optionally you can also put `:<title here>` at the end (after `KEY`).
"""

parser = argparse.ArgumentParser(
    "Key Vault DB Poster",
    description="Add or update key information to a key vault database."
)
parser.add_argument(
    "-t", "--table",
    help="Table to store keys to.",
    required=True)
parser.add_argument(
    "-i", "--input",
    help="Data used to parse from.",
    required=True)
parser.add_argument(
    "-o", "--output",
    help="A key store database.",
    required=True)
parser.add_argument(
    "-d", "--dry-run",
    help="Run without saving changes.",
    action="store_true", required=False)
args = parser.parse_args()

output_db = AtomicSQL()
output_db_id = output_db.load(sqlite3.connect(args.output))

add_count = 0
update_count = 0
existed_count = 0

if args.input == "-":
    input_ = sys.stdin.read()
else:
    with open(args.input, encoding="utf-8") as fd:
        input_ = fd.read()

for line in input_.splitlines(keepends=False):
    match = re.search(r"^(?P<kid>[0-9a-fA-F]{32}):(?P<key>[0-9a-fA-F]{32})(:(?P<title>[\w .:-]*))?$", line)
    if not match:
        continue
    kid = match.group("kid").lower()
    key = match.group("key").lower()
    title = match.group("title") or None

    exists = output_db.safe_execute(
        output_db_id,
        lambda db, cursor: cursor.execute(
            f"SELECT title FROM `{args.table}` WHERE `kid`=:kid",
            {"kid": kid}
        )
    ).fetchone()

    if exists:
        if title and not exists[0]:
            update_count += 1
            print(f"Updating {args.table} {kid}: {title}")
            output_db.safe_execute(
                output_db_id,
                lambda db, cursor: cursor.execute(
                    f"UPDATE `{args.table}` SET `title`=:title",
                    {"title": title}
                )
            )
        else:
            existed_count += 1
            print(f"Key {args.table} {kid} already exists in the database.")
    else:
        add_count += 1
        print(f"Adding {args.table} {kid} ({title}): {key}")
        output_db.safe_execute(
            output_db_id,
            lambda db, cursor: cursor.execute(
                f"INSERT INTO `{args.table}` (kid, key_, title) VALUES (:kid, :key, :title)",
                {"kid": kid, "key": key, "title": title}
            )
        )

if args.dry_run:
    print("No changes commited due to dry run.")
else:
    output_db.commit(output_db_id)

print(
    "Done!\n"
    f"{add_count} added, {update_count} updated, {existed_count} already exist."
)