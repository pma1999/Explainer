-- Explainer: server-side reading progress mutations.
-- Keeps progress writes atomic and avoids returning project JSON over PostgREST.

create or replace function public.apply_project_subsection_progress(
  p_project_id uuid,
  p_user_id uuid,
  p_part_id integer,
  p_tab text default 'explicacion',
  p_completed_subsection_ids text[] default '{}'::text[],
  p_uncompleted_subsection_ids text[] default '{}'::text[],
  p_last_subsection_id text default null
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_project public.projects%rowtype;
  v_progress jsonb;
  v_completed_ids text[] := '{}'::text[];
  v_before_completed_ids text[] := '{}'::text[];
  v_existing_id text;
  v_incoming_id text;
  v_remove_ids text[] := '{}'::text[];
  v_changed boolean := false;
  v_now timestamptz;
  v_last_subsection jsonb;
  v_part_prefix text := 'subsec-' || p_part_id::text || '-%';
begin
  select *
    into v_project
    from public.projects
   where id = p_project_id
     and user_id = p_user_id
   for update;

  if not found then
    return 'not_found';
  end if;

  if not exists (
    select 1
      from jsonb_array_elements(
        case
          when jsonb_typeof(v_project.segmentation->'partes') = 'array'
            then v_project.segmentation->'partes'
          else '[]'::jsonb
        end
      ) as part(item)
     where part.item->>'numero' = p_part_id::text
  ) then
    return 'part_not_found';
  end if;

  if p_last_subsection_id is not null
     and p_last_subsection_id <> ''
     and p_last_subsection_id not like v_part_prefix then
    return 'invalid_subsection';
  end if;

  foreach v_incoming_id in array coalesce(p_completed_subsection_ids, '{}'::text[]) loop
    if v_incoming_id is not null
       and v_incoming_id <> ''
       and v_incoming_id not like v_part_prefix then
      return 'invalid_subsection';
    end if;
  end loop;

  foreach v_incoming_id in array coalesce(p_uncompleted_subsection_ids, '{}'::text[]) loop
    if v_incoming_id is not null
       and v_incoming_id <> ''
       and v_incoming_id not like v_part_prefix then
      return 'invalid_subsection';
    end if;
  end loop;

  v_progress := coalesce(v_project.reading_progress, '{}'::jsonb);

  for v_existing_id in
    select value
      from jsonb_array_elements_text(
        case
          when jsonb_typeof(v_progress->'completed_subsections') = 'array'
            then v_progress->'completed_subsections'
          else '[]'::jsonb
        end
      ) as existing(value)
  loop
    if v_existing_id is not null and not (v_existing_id = any(v_completed_ids)) then
      v_completed_ids := array_append(v_completed_ids, v_existing_id);
    end if;
  end loop;

  foreach v_incoming_id in array coalesce(p_completed_subsection_ids, '{}'::text[]) loop
    if v_incoming_id is not null
       and v_incoming_id <> ''
       and not (v_incoming_id = any(v_completed_ids)) then
      v_completed_ids := array_append(v_completed_ids, v_incoming_id);
      v_changed := true;
    end if;
  end loop;

  v_remove_ids := coalesce(p_uncompleted_subsection_ids, '{}'::text[]);
  if array_length(v_remove_ids, 1) is not null then
    v_before_completed_ids := v_completed_ids;
    select coalesce(array_agg(item), '{}'::text[])
      into v_completed_ids
      from unnest(v_completed_ids) as remaining(item)
     where not (item = any(v_remove_ids));

    if v_completed_ids is distinct from v_before_completed_ids then
      v_changed := true;
    end if;
  end if;

  if v_changed or v_progress ? 'completed_subsections' then
    v_progress := jsonb_set(v_progress, '{completed_subsections}', to_jsonb(v_completed_ids), true);
  end if;

  if p_last_subsection_id is not null and p_last_subsection_id <> '' then
    v_last_subsection := jsonb_build_object(
      'part_id', p_part_id,
      'subsection_id', p_last_subsection_id,
      'tab', coalesce(nullif(p_tab, ''), 'explicacion')
    );
    if v_progress->'last_subsection' is distinct from v_last_subsection then
      v_progress := jsonb_set(v_progress, '{last_subsection}', v_last_subsection, true);
      v_changed := true;
    end if;
  end if;

  if not v_changed then
    return 'noop';
  end if;

  v_now := now();
  if p_last_subsection_id is not null and p_last_subsection_id <> '' then
    v_progress := jsonb_set(
      v_progress,
      '{last_read_at}',
      to_jsonb(to_char(v_now at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
      true
    );
  end if;

  update public.projects
     set reading_progress = v_progress,
         updated_at = v_now
   where id = p_project_id
     and user_id = p_user_id;

  return 'ok';
end;
$$;

create or replace function public.apply_project_section_progress(
  p_project_id uuid,
  p_user_id uuid,
  p_part_id integer,
  p_completed boolean default true
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_project public.projects%rowtype;
  v_progress jsonb;
  v_completed_ids integer[] := '{}'::integer[];
  v_changed boolean := false;
  v_now timestamptz;
begin
  select *
    into v_project
    from public.projects
   where id = p_project_id
     and user_id = p_user_id
   for update;

  if not found then
    return 'not_found';
  end if;

  if not exists (
    select 1
      from jsonb_array_elements(
        case
          when jsonb_typeof(v_project.segmentation->'partes') = 'array'
            then v_project.segmentation->'partes'
          else '[]'::jsonb
        end
      ) as part(item)
     where part.item->>'numero' = p_part_id::text
  ) then
    return 'part_not_found';
  end if;

  if coalesce(v_project.partes_contenido->(p_part_id::text)->>'status', '') <> 'completed' then
    return 'content_not_ready';
  end if;

  v_progress := coalesce(v_project.reading_progress, '{}'::jsonb);

  select coalesce(array_agg(part_id order by part_id), '{}'::integer[])
    into v_completed_ids
    from (
      select distinct existing.value::integer as part_id
        from jsonb_array_elements_text(
          case
            when jsonb_typeof(v_progress->'completed_parts') = 'array'
              then v_progress->'completed_parts'
            else '[]'::jsonb
          end
        ) as existing(value)
       where existing.value ~ '^[0-9]+$'
    ) as existing_parts;

  if p_completed then
    if p_part_id = any(v_completed_ids) then
      return 'noop';
    end if;
    v_completed_ids := array_append(v_completed_ids, p_part_id);
    v_changed := true;
  else
    if not (p_part_id = any(v_completed_ids)) then
      return 'noop';
    end if;
    select coalesce(array_agg(item order by item), '{}'::integer[])
      into v_completed_ids
      from unnest(v_completed_ids) as remaining(item)
     where item <> p_part_id;
    v_changed := true;
  end if;

  if not v_changed then
    return 'noop';
  end if;

  select coalesce(array_agg(item order by item), '{}'::integer[])
    into v_completed_ids
    from unnest(v_completed_ids) as sorted(item);

  v_now := now();
  v_progress := jsonb_set(v_progress, '{completed_parts}', to_jsonb(v_completed_ids), true);
  v_progress := jsonb_set(
    v_progress,
    '{last_read_at}',
    to_jsonb(to_char(v_now at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    true
  );

  update public.projects
     set reading_progress = v_progress,
         updated_at = v_now
   where id = p_project_id
     and user_id = p_user_id;

  return 'ok';
end;
$$;

revoke all on function public.apply_project_subsection_progress(uuid, uuid, integer, text, text[], text[], text) from public;
revoke all on function public.apply_project_subsection_progress(uuid, uuid, integer, text, text[], text[], text) from anon;
revoke all on function public.apply_project_subsection_progress(uuid, uuid, integer, text, text[], text[], text) from authenticated;
grant execute on function public.apply_project_subsection_progress(uuid, uuid, integer, text, text[], text[], text) to service_role;

revoke all on function public.apply_project_section_progress(uuid, uuid, integer, boolean) from public;
revoke all on function public.apply_project_section_progress(uuid, uuid, integer, boolean) from anon;
revoke all on function public.apply_project_section_progress(uuid, uuid, integer, boolean) from authenticated;
grant execute on function public.apply_project_section_progress(uuid, uuid, integer, boolean) to service_role;
