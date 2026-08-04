#!/usr/bin/env bash
# A nightly copy of the bookmarks. Small by construction — the database holds
# reading positions and readers' own corrections, never a book — so a dump is
# kilobytes and keeping a fortnight of them costs nothing.
#
# What this protects against: a bad migration, a mistaken DELETE, a table
# dropped. What it does NOT protect against is losing the machine, because the
# copy sits on the same disk. Moving them off-box needs somewhere to put them
# and is a separate decision.
set -euo pipefail

DB=${BIREAD_DB:-love}
DIR=${BIREAD_BACKUP_DIR:-/srv/backups/biread}
KEEP=${BIREAD_BACKUP_DAYS:-14}

mkdir -p "$DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$DIR/$DB-$STAMP.sql.gz"

# --clean --if-exists so a restore can run over an existing database.
pg_dump --clean --if-exists "$DB" | gzip -9 > "$OUT.partial"
mv "$OUT.partial" "$OUT"          # named only once it is whole
chmod 600 "$OUT"

find "$DIR" -name "$DB-*.sql.gz" -mtime +"$KEEP" -delete
find "$DIR" -name "*.partial" -mtime +1 -delete

# A dump that cannot be read is not a backup. Say the size so a run that quietly
# produced nothing is visible in the journal.
echo "$(basename "$OUT") — $(stat -c %s "$OUT") bytes, $(ls -1 "$DIR"/$DB-*.sql.gz | wc -l) kept"
gzip -t "$OUT"
