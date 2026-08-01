-- Explainer: add failed_parts column to projects
-- Tracks part ids whose explainer failed (honest part-state quick win).
-- Run in Supabase SQL Editor or via: supabase db push

alter table public.projects
  add column if not exists failed_parts jsonb;
