-- content_updated_at: versión de contenido (segmentation/partes_contenido).
-- updated_at sigue siendo el reloj de actividad (el progreso de lectura lo bumpea).
alter table public.projects add column content_updated_at timestamptz;
update public.projects set content_updated_at = updated_at where content_updated_at is null;
alter table public.projects alter column content_updated_at set default now();
alter table public.projects alter column content_updated_at set not null;
