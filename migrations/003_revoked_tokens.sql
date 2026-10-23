BEGIN;

CREATE TABLE IF NOT EXISTS public.revoked_auth_tokens (
    token_jti UUID PRIMARY KEY,
    user_id UUID NOT NULL
        REFERENCES public.app_users(user_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_revoked_auth_tokens_expires_at
    ON public.revoked_auth_tokens (expires_at);

COMMIT;
