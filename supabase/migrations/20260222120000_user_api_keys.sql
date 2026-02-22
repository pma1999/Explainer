-- Migration: User API Keys (BYOK - Bring Your Own Key)
-- Creates table for storing encrypted API keys per user with strict RLS policies

-- ========== TABLE: public.user_api_keys ==========
create table if not exists public.user_api_keys (
  user_id uuid primary key references auth.users(id) on delete cascade,
  encrypted_api_key text not null,
  provider text not null default 'google_gemini',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Index for faster lookups by user (though PK is already indexed, this documents intent)
create index if not exists idx_user_api_keys_user_id on public.user_api_keys(user_id);

-- Enable Row Level Security
alter table public.user_api_keys enable row level security;

-- ========== RLS POLICIES ==========
-- Users can only access their own API keys

create policy "Users can view own API key"
  on public.user_api_keys for select
  using (auth.uid() = user_id);

create policy "Users can insert own API key"
  on public.user_api_keys for insert
  with check (auth.uid() = user_id);

create policy "Users can update own API key"
  on public.user_api_keys for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own API key"
  on public.user_api_keys for delete
  using (auth.uid() = user_id);

-- ========== TRIGGER: Auto-update updated_at ==========
create or replace function public.update_updated_at_column()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger update_user_api_keys_updated_at
  before update on public.user_api_keys
  for each row
  execute function public.update_updated_at_column();

-- ========== COMMENTS ==========
comment on table public.user_api_keys is 'Stores encrypted API keys per user (BYOK model). Keys are encrypted by the backend using Fernet (AES-128) before storage.';
comment on column public.user_api_keys.user_id is 'Reference to auth.users. Each user can have at most one API key (1:1 relationship).';
comment on column public.user_api_keys.encrypted_api_key is 'API key encrypted with Fernet. Only the backend with the master key can decrypt.';
comment on column public.user_api_keys.provider is 'API provider identifier (e.g., google_gemini, openai, etc.)';
