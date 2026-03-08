-- Web source support and cached extraction metadata

alter table public.projects
  add column if not exists source_type text,
  add column if not exists source_url text,
  add column if not exists source_text text,
  add column if not exists source_metadata jsonb;

update public.projects
set source_type = coalesce(nullif(source_type, ''), 'pdf')
where source_type is null or source_type = '';

update public.projects
set source_metadata = '{}'::jsonb
where source_metadata is null;

alter table public.projects
  alter column source_type set default 'pdf',
  alter column source_type set not null,
  alter column source_metadata set default '{}'::jsonb,
  alter column source_metadata set not null;

do $$
declare
  constraint_name text;
begin
  for constraint_name in
    select c.conname
    from pg_constraint c
    where c.conrelid = 'public.projects'::regclass
      and c.contype = 'c'
      and pg_get_constraintdef(c.oid) ilike '%source_type%'
  loop
    execute format(
      'alter table public.projects drop constraint if exists %I',
      constraint_name
    );
  end loop;
end $$;

alter table public.projects
  add constraint projects_source_type_check
  check (source_type in ('pdf', 'youtube', 'web'));
