from testcontainers.community.postgres import PostgresContainer


def test_custom_dump_restores_money_and_pgvector_in_a_fresh_database():
    # Dedicated disposable container: this never overwrites or connects to a business database.
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as postgres:
        script = """
set -eu
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION vector;
CREATE TABLE restore_quotes(total_paise BIGINT NOT NULL, embedding vector(3));
INSERT INTO restore_quotes VALUES (45000, '[1,0,0]');"
pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl \
  --file=/tmp/munim-restore-check.dump
createdb -U "$POSTGRES_USER" restore_probe
pg_restore -U "$POSTGRES_USER" -d restore_probe --exit-on-error /tmp/munim-restore-check.dump
psql -U "$POSTGRES_USER" -d restore_probe -tA -c "SELECT total_paise FROM restore_quotes
WHERE embedding='[1,0,0]'::vector;"
"""
        result = postgres.get_wrapped_container().exec_run(["sh", "-eu", "-c", script])
        assert result.exit_code == 0, result.output.decode()
        assert result.output.decode().strip().endswith("45000")
