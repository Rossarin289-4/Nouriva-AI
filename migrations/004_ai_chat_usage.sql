BEGIN;

ALTER TABLE public.app_users
    ADD COLUMN IF NOT EXISTS ai_plan TEXT NOT NULL DEFAULT 'free';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'app_users_ai_plan_check'
          AND conrelid = 'public.app_users'::regclass
    ) THEN
        ALTER TABLE public.app_users
            ADD CONSTRAINT app_users_ai_plan_check
            CHECK (ai_plan IN ('free', 'premium'));
    END IF;
END
$$;


CREATE TABLE IF NOT EXISTS public.ai_chat_usage_events (
    usage_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES public.app_users(user_id)
        ON DELETE CASCADE,

    provider TEXT NOT NULL
        CHECK (provider IN ('gemini', 'openai')),

    usage_date DATE NOT NULL,

    status TEXT NOT NULL DEFAULT 'reserved'
        CHECK (status IN ('reserved', 'succeeded', 'failed')),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reservation_expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,

    CONSTRAINT ai_chat_usage_events_completion_check
        CHECK (
            (status = 'reserved' AND completed_at IS NULL)
            OR
            (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
        ),

    CONSTRAINT ai_chat_usage_events_expiry_check
        CHECK (reservation_expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_ai_chat_usage_user_provider_date
    ON public.ai_chat_usage_events (
        user_id,
        provider,
        usage_date,
        status
    );

CREATE INDEX IF NOT EXISTS idx_ai_chat_usage_reservation_expiry
    ON public.ai_chat_usage_events (
        reservation_expires_at
    )
    WHERE status = 'reserved';

CREATE INDEX IF NOT EXISTS idx_ai_chat_usage_created_at
    ON public.ai_chat_usage_events (created_at);

COMMIT;
