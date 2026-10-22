BEGIN;

ALTER TABLE public.app_users
    ADD COLUMN account_type TEXT NOT NULL DEFAULT 'registered';

ALTER TABLE public.app_users
    ADD CONSTRAINT app_users_account_type_check
    CHECK (account_type IN ('registered', 'guest'));

COMMIT;
