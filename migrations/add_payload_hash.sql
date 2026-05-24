-- Migration: add payload_hash column + idempotency index
-- Apply BEFORE deploying feat/pre-live-hardening to production.
--
-- Safe to run on a live database: ADD COLUMN with a nullable default
-- does not rewrite existing rows in PostgreSQL 11+.
--
-- Apply with:
--   psql "$DATABASE_URL" -f migrations/add_payload_hash.sql

ALTER TABLE rebalance_events
    ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_rebalance_events_payload_hash
    ON rebalance_events (payload_hash)
    WHERE payload_hash IS NOT NULL;

-- To roll back:
--   DROP INDEX IF EXISTS uq_rebalance_events_payload_hash;
--   ALTER TABLE rebalance_events DROP COLUMN IF EXISTS payload_hash;
