BEGIN;

-- 1. Allow explicit consent for storing health-related data.
ALTER TABLE public.user_consents
    DROP CONSTRAINT user_consents_consent_type_check;

ALTER TABLE public.user_consents
    ADD CONSTRAINT user_consents_consent_type_check
    CHECK (
        consent_type = ANY (
            ARRAY[
                'privacy_policy',
                'external_ai_processing',
                'research_participation',
                'terms_of_service',
                'health_data_storage'
            ]::text[]
        )
    );

-- 2. Distinguish not asked, unknown, no reported allergies,
--    and user-reported allergies.
CREATE TABLE public.user_allergy_profiles (
    user_id UUID PRIMARY KEY
        REFERENCES public.app_users(user_id) ON DELETE CASCADE,

    allergy_status TEXT NOT NULL DEFAULT 'not_asked'
        CHECK (
            allergy_status IN (
                'not_asked',
                'unknown',
                'none_reported',
                'has_reported_allergies'
            )
        ),

    source_type TEXT NOT NULL DEFAULT 'user_reported'
        CHECK (
            source_type IN (
                'user_reported',
                'imported_document',
                'clinician_documented'
            )
        ),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Store individual allergy reports.
CREATE TABLE public.user_allergies (
    allergy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES public.app_users(user_id) ON DELETE CASCADE,

    allergen_code TEXT NOT NULL
        CHECK (length(trim(allergen_code)) BETWEEN 1 AND 100),

    display_label TEXT NOT NULL
        CHECK (length(trim(display_label)) BETWEEN 1 AND 200),

    confirmation_status TEXT NOT NULL DEFAULT 'reported_unconfirmed'
        CHECK (
            confirmation_status IN (
                'reported_unconfirmed',
                'user_confirmed',
                'inactive'
            )
        ),

    source_type TEXT NOT NULL DEFAULT 'user_reported'
        CHECK (
            source_type IN (
                'user_reported',
                'imported_document',
                'clinician_documented',
                'other'
            )
        ),

    notes TEXT
        CHECK (notes IS NULL OR length(notes) <= 1000),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_user_allergies_user_status
    ON public.user_allergies (
        user_id,
        confirmation_status,
        allergen_code
    );

COMMIT;
