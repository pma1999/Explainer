-- OpenRouter PDF OCR parse cache (shared across Koyeb cold starts)
-- Keyed by document SHA-256 + parser engine; payload mirrors data/openrouter_pdf_cache JSON files.

create table if not exists public.openrouter_pdf_ocr_cache (
  source_sha256 text not null,
  engine text not null,
  payload jsonb not null,
  row_version integer not null default 1,
  updated_at timestamptz not null default now(),
  primary key (source_sha256, engine),
  constraint openrouter_pdf_ocr_cache_row_version_positive check (row_version >= 1)
);

create index if not exists idx_openrouter_pdf_ocr_cache_updated_at
  on public.openrouter_pdf_ocr_cache (updated_at desc);

alter table public.openrouter_pdf_ocr_cache enable row level security;

-- No policies for anon/authenticated: only service_role (backend) bypasses RLS.

comment on table public.openrouter_pdf_ocr_cache is
  'Server-only cache for OpenRouter file-parser OCR; keyed by PDF SHA-256 and engine.';
