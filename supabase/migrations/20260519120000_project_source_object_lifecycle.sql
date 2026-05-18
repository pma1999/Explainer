-- Persist the lifecycle of uploaded PDF source objects so they can be cleaned up
-- deterministically even if the backend restarts mid-processing.

alter table public.projects
  add column if not exists source_object_path text,
  add column if not exists source_object_status text,
  add column if not exists source_object_deleted_at timestamptz;

update public.projects
set source_object_path = concat(user_id::text, '/', id::text, '/', pdf_filename)
where source_type = 'pdf'
  and coalesce(source_object_path, '') = '';

update public.projects
set source_object_status = case
  when source_type <> 'pdf' then 'none'
  when coalesce(source_object_status, '') in ('none', 'stored', 'deleted') then source_object_status
  when coalesce(source_object_path, '') <> '' then 'stored'
  else 'none'
end
where source_object_status is distinct from case
  when source_type <> 'pdf' then 'none'
  when coalesce(source_object_status, '') in ('none', 'stored', 'deleted') then source_object_status
  when coalesce(source_object_path, '') <> '' then 'stored'
  else 'none'
end;

update public.projects
set source_object_deleted_at = now()
where source_object_status = 'deleted'
  and source_object_deleted_at is null;

update public.projects
set source_object_status = 'none'
where source_object_status is null;

alter table public.projects
  alter column source_object_status set default 'none',
  alter column source_object_status set not null;

alter table public.projects
  drop constraint if exists projects_source_object_status_check;

alter table public.projects
  add constraint projects_source_object_status_check
  check (source_object_status in ('none', 'stored', 'deleted'));

comment on column public.projects.source_object_path is
  'Canonical path of the uploaded PDF inside storage bucket project-pdfs.';

comment on column public.projects.source_object_status is
  'Lifecycle state for the uploaded PDF source object: none, stored, or deleted.';

comment on column public.projects.source_object_deleted_at is
  'Timestamp when the uploaded PDF source object was confirmed deleted from Supabase Storage.';
