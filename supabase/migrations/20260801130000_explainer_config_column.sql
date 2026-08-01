-- C2 "Repaso activo": guarda la config del explainer (provider + modelo)
-- usada al procesar cada proyecto, para reutilizarla en el endpoint de review.
alter table public.projects
  add column if not exists explainer_config jsonb;
