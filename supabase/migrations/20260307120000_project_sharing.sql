-- Explainer: project sharing - share_token for public read-only links
-- Allows registered users to share completed projects with unregistered users

alter table public.projects
  add column if not exists share_token text unique;

create unique index if not exists idx_projects_share_token
  on public.projects(share_token)
  where share_token is not null;

comment on column public.projects.share_token is 'URL-safe token for public sharing. When set, unauthenticated users can view project content via /api/shared/{token}';
