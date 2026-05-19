-- Migration: add notion_portail_page_id to user_profiles
-- Purpose: store the Notion page ID of each user's "Portail du mycologue" entry,
--          so that imports can populate the Mycologue (relation) column on the BD Observations.
-- Applied to project lcnkefumkqsswptfkhql (Fongarium-manager) on 2026-05-19 via Supabase MCP.
-- Idempotent : safe to re-run.

alter table public.user_profiles
    add column if not exists notion_portail_page_id text;

comment on column public.user_profiles.notion_portail_page_id is
    'Notion page ID (UUID with or without dashes) of the user''s entry in the "Portail du mycologue" Notion database. Used by the Streamlit Portail Myco import worker to populate the Mycologue (relation) column on each imported observation. Mandatory for new signups; existing users are prompted to fill it on their next login.';
