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
    environment TEXT NOT NULL DEFAULT 'testnet' CHECK (environment IN ('testnet', 'real')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, label)
);

-- Migration: add key_meta/secret_meta if upgrading from initial schema
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS key_meta    TEXT NOT NULL DEFAULT '';
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS secret_meta TEXT NOT NULL DEFAULT '';

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
    PRIMARY KEY (account_id, asset)
);

CREATE TABLE IF NOT EXISTS worker_leases (
    account_id  UUID PRIMARY KEY REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    worker_id   TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS: users can only read/write their own data
ALTER TABLE exchange_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE live_positions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own_accounts" ON exchange_accounts
    USING (user_id = auth.uid());

CREATE POLICY "own_trades" ON trades
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));

CREATE POLICY "own_equity" ON equity_snapshots
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));

CREATE POLICY "own_positions" ON live_positions
    USING (account_id IN (SELECT id FROM exchange_accounts WHERE user_id = auth.uid()));
