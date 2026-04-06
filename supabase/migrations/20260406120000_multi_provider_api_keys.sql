-- Migration: Multi-provider API keys support
-- Changes user_api_keys PK from (user_id) to (user_id, provider)
-- so each user can store one key per provider independently.

-- 1. Drop old single-column primary key
alter table public.user_api_keys
  drop constraint user_api_keys_pkey;

-- 2. Add composite primary key
alter table public.user_api_keys
  add primary key (user_id, provider);

-- 3. Replace the now-redundant single-column index with a provider-aware one
drop index if exists public.idx_user_api_keys_user_id;
create index if not exists idx_user_api_keys_user_provider
  on public.user_api_keys(user_id, provider);

-- 4. Update column comments
comment on column public.user_api_keys.user_id is 'Reference to auth.users. Each user can have one key per provider.';
comment on column public.user_api_keys.provider is 'API provider identifier (google_gemini, openrouter, …). Part of the composite PK.';
