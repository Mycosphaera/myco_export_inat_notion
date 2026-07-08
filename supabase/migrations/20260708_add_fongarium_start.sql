-- Migration: add fongarium_start to user_profiles
-- Purpose: "plancher" = last fongarium number a member already used OUTSIDE the
--          app (iNat / personal files). The next auto-assigned number never goes
--          below it: next = max(max_in_notion, fongarium_start) + 1 → seamless
--          continuity for members who join mid-route with an existing sequence,
--          without touching/reusing their old numbers.
-- Idempotent : safe to re-run.
-- Applied to project lcnkefumkqsswptfkhql (Fongarium-manager) on 2026-07-08 via Supabase MCP.

alter table public.user_profiles
    add column if not exists fongarium_start integer;

comment on column public.user_profiles.fongarium_start is
    'Dernier n° de fongarium déjà utilisé HORS app (plancher). Prochain n° auto-assigné = max(max Notion, fongarium_start) + 1 — jamais en arrière. NULL/0 = pas de plancher. Saisi/édité depuis « Mon Profil ».';
