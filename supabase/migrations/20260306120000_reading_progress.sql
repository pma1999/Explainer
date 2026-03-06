-- Explainer: reading progress per project
-- Tracks which sections the user has completed reading

alter table public.projects
  add column if not exists reading_progress jsonb not null default '{}';

comment on column public.projects.reading_progress is 'User reading progress: { "completed_parts": [1,2,3], "last_read_at": "ISO8601" }';
