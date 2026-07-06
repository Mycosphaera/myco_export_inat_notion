-- Migration: add inat_user_id to user_profiles
-- Purpose: store each user's NUMERIC iNaturalist user id (from the "Portail du
--          mycologue" Notion DB) so searches can use it as `user_id`. A numeric
--          id never triggers a 422 (unlike a malformed login / email), which is
--          the root fix of the "email-as-username" bug (PR #29).
-- Idempotent : safe to re-run. The app also degrades gracefully if this column
--          is missing (create/update_user_profile retry without it), so it can
--          be applied at any time.

alter table public.user_profiles
    add column if not exists inat_user_id text;

comment on column public.user_profiles.inat_user_id is
    'Numeric iNaturalist user id (stored as text), backfilled from the "iNaturalist ID" field of the user''s "Portail du mycologue" Notion page when they claim it. Preferred over the login as the `user_id` search parameter (numeric ids never 422). Cleared when the user manually edits their pseudo (stale), then re-filled on next page claim.';
