-- Migration: User provider connections (Codex / ChatGPT OAuth link)
-- Stores the encrypted ChatGPT credentials blob and link state per user.
-- Esquema fijo (global-constraints.md §Persistence): one row per user (PK user_id),
-- provider is fixed to 'codex' (CHECK), status transitions none -> pending -> linked|failed
-- and linked -> none. encrypted_credentials is a Fernet blob produced by the backend
-- (encrypt_user_api_key(json.dumps(auth_json), user_id)); never plaintext.
--
-- Re-applicable: create table if not exists + drop policy if exists before each
-- create policy.

-- ========== TABLE: public.user_provider_connections ==========
create table if not exists public.user_provider_connections (
  user_id uuid primary key references auth.users(id) on delete cascade,
  provider text not null default 'codex' check (provider = 'codex'),
  status text not null default 'none' check (status in ('none','pending','linked','failed')),
  encrypted_credentials text,
  login_id text,
  plan_type text,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Enable Row Level Security
alter table public.user_provider_connections enable row level security;

-- ========== RLS POLICIES ==========
-- Users can only access their own connection row (pattern of user_api_keys).
-- The backend accesses with service_role (bypasses RLS); the identity always comes
-- from the verified JWT (get_current_user_id).

drop policy if exists "Users can view own provider connection"
  on public.user_provider_connections;
create policy "Users can view own provider connection"
  on public.user_provider_connections for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own provider connection"
  on public.user_provider_connections;
create policy "Users can insert own provider connection"
  on public.user_provider_connections for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own provider connection"
  on public.user_provider_connections;
create policy "Users can update own provider connection"
  on public.user_provider_connections for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ========== COMMENTS ==========
comment on table public.user_provider_connections is 'Stores the ChatGPT (Codex) OAuth link per user: encrypted credentials blob + link state. Credentials are encrypted by the backend with Fernet (per-user key) before storage; never plaintext.';
comment on column public.user_provider_connections.user_id is 'Reference to auth.users (uuid). One connection row per user.';
comment on column public.user_provider_connections.provider is 'Fixed to codex (CHECK). Reserved for future providers.';
comment on column public.user_provider_connections.status is 'Link state: none -> pending -> linked | failed, and linked -> none (unlink).';
comment on column public.user_provider_connections.encrypted_credentials is 'Opaque Fernet blob (encrypt_user_api_key of the auth.json content). Only the backend with the master key can decrypt.';
comment on column public.user_provider_connections.login_id is 'Device-code login identifier from account/login/start (not a secret).';
comment on column public.user_provider_connections.plan_type is 'Raw ChatGPT plan type reported by account/read.planType (not a secret).';
comment on column public.user_provider_connections.last_error is 'Safe user-facing error message only (no credentials, no blob content).';
