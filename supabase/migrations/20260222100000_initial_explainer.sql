-- Explainer: projects table + RLS, Storage bucket and policies
-- Run in Supabase SQL Editor or via: supabase db push

-- ========== STORAGE BUCKET ==========
insert into storage.buckets (id, name, public)
values ('project-pdfs', 'project-pdfs', false)
on conflict (id) do nothing;

-- ========== TABLE: public.projects ==========
create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text not null,
  pdf_filename text not null,
  file_uri text,
  status text not null default 'pending',
  segmentation jsonb,
  partes_contenido jsonb not null default '{}',
  usage jsonb not null default '{}',
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_projects_user_id on public.projects(user_id);
create index if not exists idx_projects_updated_at on public.projects(updated_at desc);

alter table public.projects enable row level security;

create policy "Users can do everything on own projects"
  on public.projects for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ========== STORAGE: bucket project-pdfs (private) ==========
-- Bucket is created via Dashboard or API; policy below assumes bucket_id = 'project-pdfs'
-- Path convention: {user_id}/{project_id}/{filename}

-- Allow authenticated users to read only their own folder (first path segment = user_id)
create policy "Users can read own PDFs"
on storage.objects for select
to authenticated
using (
  bucket_id = 'project-pdfs'
  and (storage.foldername(name))[1] = auth.uid()::text
);

-- Allow authenticated users to upload only into their own folder
create policy "Allow uploads to user folder"
on storage.objects for insert
to authenticated
with check (
  bucket_id = 'project-pdfs'
  and (storage.foldername(name))[1] = auth.uid()::text
);

-- Allow authenticated users to update/delete only their own folder
create policy "Users can update own PDFs"
on storage.objects for update
to authenticated
using (
  bucket_id = 'project-pdfs'
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id = 'project-pdfs'
  and (storage.foldername(name))[1] = auth.uid()::text
);

create policy "Users can delete own PDFs"
on storage.objects for delete
to authenticated
using (
  bucket_id = 'project-pdfs'
  and (storage.foldername(name))[1] = auth.uid()::text
);

-- Note: Create the bucket 'project-pdfs' in Supabase Dashboard (Storage > New bucket, private)
-- or via API. Name must match policy bucket_id above.
