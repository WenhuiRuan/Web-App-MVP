"""Forward-only, checksummed, transactional SQLite migrations."""
import argparse
import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MigrationError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path, *, migrations_dir: Path | None = None):
        self.path = Path(path)
        self.migrations_dir = migrations_dir or PROJECT_ROOT / 'db' / 'migrations'

    @contextmanager
    def connect(self, *, create: bool = True):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        uri = self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw')
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA busy_timeout=5000')
            yield conn
        finally:
            conn.close()

    def migration_files(self):
        files = sorted(self.migrations_dir.glob('[0-9][0-9][0-9]_*.sql'))
        versions = [int(p.name.split('_', 1)[0]) for p in files]
        if not files or versions != list(range(1, len(files) + 1)):
            raise MigrationError('Migration files must start at 001 and be contiguous')
        return files

    def migrate(self) -> list[int]:
        files = self.migration_files()
        applied = []
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))) STRICT")
                history = {row['version']: row for row in conn.execute('SELECT * FROM schema_migrations')}
                if set(history) - set(range(1, len(files) + 1)):
                    raise MigrationError('Database schema is newer than this application')
                if sorted(history) != list(range(1, len(history) + 1)):
                    raise MigrationError('Migration history has a gap')
                for version, path in enumerate(files, 1):
                    source = path.read_bytes()
                    digest = hashlib.sha256(source).hexdigest()
                    if version in history:
                        if history[version]['checksum'] != digest or history[version]['name'] != path.name:
                            raise MigrationError('Applied migration changed; restore it and add a new migration')
                        continue
                    statement = ''
                    for line in source.decode('utf-8').splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ''
                    if statement.strip():
                        raise MigrationError('Incomplete migration statement')
                    conn.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES (?,?,?)', (version, path.name, digest))
                    applied.append(version)
                conn.execute('COMMIT')
            except Exception as exc:
                if conn.in_transaction:
                    conn.execute('ROLLBACK')
                if isinstance(exc, MigrationError):
                    raise
                raise MigrationError('Migration failed; transaction rolled back') from None
        return applied

    def ready(self) -> bool:
        try:
            files = self.migration_files()
            with self.connect(create=False) as conn:
                rows = list(conn.execute('SELECT version,name,checksum FROM schema_migrations ORDER BY version'))
                return len(rows) == len(files) and all(
                    row['version'] == i and row['name'] == path.name and row['checksum'] == hashlib.sha256(path.read_bytes()).hexdigest()
                    for i, (row, path) in enumerate(zip(rows, files), 1)
                )
        except (sqlite3.Error, OSError, MigrationError):
            return False


def main():
    from .config import load_settings
    parser = argparse.ArgumentParser(description='Initialize or upgrade the local SQLite database')
    parser.add_argument('--path', type=Path)
    args = parser.parse_args()
    database = Database(args.path or load_settings().database_path)
    try:
        versions = database.migrate()
    except MigrationError as exc:
        raise SystemExit(str(exc)) from None
    print(f'Migrations applied: {versions}; schema ready: {database.ready()}')


if __name__ == '__main__':
    main()
