-- Hercules 3.0 — Supabase schema
-- Auth handled by Supabase auth.users (built-in).
-- All user_id columns reference auth.users.id (UUID).

CREATE TABLE IF NOT EXISTS exchange_accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    api_key     TEXT NOT NULL,        -- AES-GCM ciphertext, base64
    key_meta    TEXT NOT NULL,        -- "nonce_b64:tag_b64"
    api_secret  TEXT NOT NULL,        -- AES-GCM ciphertext, base64
    secret_meta TEXT NOT NULL,        -- "nonce_b64:tag_b64"
    environment TEXT NOT NULL DEFAULT 'testnet' CHECK (environment IN ('paper', 'testnet', 'real')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, label)
);

-- Migration: add key_meta/secret_meta if upgrading from initial schema
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS key_meta    TEXT NOT NULL DEFAULT '';
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS secret_meta TEXT NOT NULL DEFAULT '';
ALTER TABLE exchange_accounts DROP CONSTRAINT IF EXISTS exchange_accounts_environment_check;
ALTER TABLE exchange_accounts ADD CONSTRAINT exchange_accounts_environment_check CHECK (environment IN ('paper', 'testnet', 'real'));

CREATE TABLE IF NOT EXISTS trades (
    id            BIGSERIAL PRIMARY KEY,
    account_id    UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    asset         TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    entry_time    TIMESTAMPTZ NOT NULL,
    exit_time     TIMESTAMPTZ,
    entry_price   NUMERIC(20, 8) NOT NULL,
    exit_price    NUMERIC(20, 8),
    quantity      NUMERIC(20, 8) NOT NULL,
    pnl           NUMERIC(20, 8),
    fee           NUMERIC(20, 8),
    outcome       TEXT CHECK (outcome IN ('win', 'loss', 'open', 'liquidated')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    account_id  UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL,
    equity_usdt NUMERIC(20, 8) NOT NULL,
    UNIQUE (account_id, ts)
);

CREATE TABLE IF NOT EXISTS live_positions (
    account_id  UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    asset       TEXT NOT NULL,
    side        TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT', 'FLAT')),
    size_usdt   NUMERIC(20, 8) NOT NULL DEFAULT 0,
    entry_price NUMERIC(20, 8),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, asset, side)
);
-- Upgrade installations created by the original (account_id, asset) key.
ALTER TABLE live_positions DROP CONSTRAINT IF EXISTS live_positions_pkey;
ALTER TABLE live_positions ADD PRIMARY KEY (account_id, asset, side);

CREATE TABLE IF NOT EXISTS worker_leases (
    account_id  UUID PRIMARY KEY REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    worker_id   TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Atomic lease acquisition. The conditional upsert makes concurrent workers
-- deterministic: only the current owner or an expired lease can be replaced.
CREATE OR REPLACE FUNCTION acquire_worker_lease(
    p_account_id UUID, p_worker_id TEXT, p_ttl_seconds INTEGER DEFAULT 60
) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    INSERT INTO worker_leases(account_id, worker_id, expires_at, acquired_at)
    VALUES (p_account_id, p_worker_id, now() + make_interval(secs => p_ttl_seconds), now())
    ON CONFLICT (account_id) DO UPDATE
      SET worker_id = EXCLUDED.worker_id,
          expires_at = EXCLUDED.expires_at,
          acquired_at = EXCLUDED.acquired_at
      WHERE worker_leases.expires_at <= now() OR worker_leases.worker_id = EXCLUDED.worker_id;
    RETURN FOUND;
END;
$$;
REVOKE ALL ON FUNCTION acquire_worker_lease(UUID, TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION acquire_worker_lease(UUID, TEXT, INTEGER) TO service_role;

-- RLS: users can only read/write their own data
ALTER TABLE exchange_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE live_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE worker_leases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_accounts" ON exchange_accounts;
DROP POLICY IF EXISTS "own_trades" ON trades;
DROP POLICY IF EXISTS "own_equity" ON equity_snapshots;
DROP POLICY IF EXISTS "own_positions" ON live_positions;
DROP POLICY IF EXISTS "own_worker_leases" ON worker_leases;

CREATE POLICY "own_accounts" ON exchange_accounts
    USING (user_id = auth.uid());

CREATE POLICY "own_trades" ON trades
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));

CREATE POLICY "own_equity" ON equity_snapshots
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));

CREATE POLICY "own_positions" ON live_positions
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));

CREATE POLICY "own_worker_leases" ON worker_leases
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()))
    WITH CHECK (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));
