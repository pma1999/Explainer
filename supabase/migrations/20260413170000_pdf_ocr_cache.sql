-- Provider-neutral PDF OCR cache (shared across server instances)
-- Keyed by document SHA-256 + OCR engine; payload mirrors data/pdf_ocr_cache JSON files.

create table if not exists public.pdf_ocr_cache (
  source_sha256 text not null,
  engine text not null,
  payload jsonb not null,
  row_version integer not null default 1,
  updated_at timestamptz not null default now(),
  primary key (source_sha256, engine),
  constraint pdf_ocr_cache_row_version_positive check (row_version >= 1)
);

create index if not exists idx_pdf_ocr_cache_updated_at
  on public.pdf_ocr_cache (updated_at desc);

alter table public.pdf_ocr_cache enable row level security;

-- No policies for anon/authenticated: only service_role (backend) bypasses RLS.

comment on table public.pdf_ocr_cache is
  'Server-only cache for provider-neutral PDF OCR; keyed by PDF SHA-256 and OCR engine.';
