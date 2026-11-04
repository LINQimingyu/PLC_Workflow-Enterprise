#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username postgres --dbname plc_enterprise <<'SQL'
CREATE ROLE ep_app LOGIN;
SELECT format('ALTER ROLE ep_app PASSWORD %L', btrim(pg_read_file('/run/secrets/app_password'), E'\n\r')) \gexec
ALTER DATABASE plc_enterprise OWNER TO ep_app;
GRANT ALL ON SCHEMA public TO ep_app;
SQL
