# Spec: Listado ligero de proyectos + merge seguro (OOM / plan gratuito)

**Fecha:** 2026-04-08  
**Estado:** Aprobado  
**Alcance:** `GET /api/projects`, capa de datos Supabase, y `mergeProjects` en `frontend/js/storage.js`. **Fuera de alcance:** paralelismo del pipeline de IA (`MAX_CONCURRENT_PARTS`, `asyncio.gather` de agentes, límites de hilos del procesamiento).

---

## 1. Problema

En hosts con poca RAM (p. ej. ~512 MB, plan gratuito), `GET /api/projects` hace `select("*")` y devuelve **filas completas**, incluidos `partes_contenido` y a menudo `source_text` — JSON muy grandes. Varios clientes o pestañas disparan peticiones concurrentes; el pico de memoria en el proceso Python contribuye a **OOM (exit code 9)**.

El cuello de botella no es el paralelismo de la IA en background, sino **transferir y parsear demasiado dato en el listado HTTP**.

---

## 2. Decisión de producto (opción elegida por diseño)

Se adopta la **opción B (pragmática)** frente a A y C:

| Opción | Por qué no es la principal |
|--------|-----------------------------|
| **A** (máxima seguridad solo vía BD) | Exige migraciones / vistas / RPC y más operativa sin aportar más garantías que un merge bien definido en cliente. |
| **C** (híbrido con N+1 fetches) | Multiplica peticiones en el arranque y en sync; empeora latencia y puede volver a estrujar la instancia en ráfagas. |

**B** reduce memoria en el **caso común** (una petición de lista) y localiza la complejidad en reglas de fusión **testeables** entre respuesta del servidor y backup IndexedDB.

---

## 3. Solución elegida

### 3.1 Contrato del API `GET /api/projects`

- La respuesta sigue siendo un **array de objetos proyecto**, pero cada elemento es un **resumen de lista**:
  - Incluye todos los campos necesarios para la UI de tarjetas (`id`, `name`, `description`, `status`, fechas, `pdf_filename`, `source_type`, `source_url`, `source_metadata`, `file_uri`, `segmentation`, `usage`, `reading_progress`, `error_message`, `share_token` según el caso).
  - **Excluye por defecto** los campos pesados: `partes_contenido` y `source_text` (carga vía `GET /api/projects/{id}` cuando haga falta el detalle).
  - Cada objeto debe llevar **`"list_summary": true`** (boolean fijo) para que el cliente no infiera el modo solo por claves ausentes.

**Nota:** Si `segmentation` sigue siendo grande en algunos proyectos, una fase posterior puede recortar solo lo necesario para el contador de partes (p. ej. longitud de `partes`) sin incluir el resto del JSON; no es requisito del MVP si omitir `partes_contenido` + `source_text` ya estabiliza memoria.

### 3.2 Capa de datos (`backend/supabase_data.py`)

- Añadir **`list_projects_summary(user_id)`** (o renombrar el flujo actual) que ejecute un `select` **con lista explícita de columnas** — equivalente a “todo menos `partes_contenido` y `source_text`”, manteniendo el mismo ordenamiento que hoy (`updated_at` desc).
- Reutilizar `_row_to_project` o una variante `_row_to_list_item` que añada `list_summary: True` y no espere esas columnas.
- **`get_project` / export / import** no cambian de contrato: siguen devolviendo el documento completo cuando se pide por id o export.

### 3.3 Reglas de merge en cliente (`mergeProjects`)

Objetivo: si el servidor envía un resumen **más reciente** que el backup local, actualizar metadatos (estado, costes, progreso, nombres, etc.) **sin borrar** `partes_contenido` / `source_text` almacenados offline.

**Definición:** un objeto servidor es “resumen” si `project.list_summary === true`.

**Algoritmo (por par `local` y `server` del mismo `id`):**

1. Calcular cuál tiene **`updated_at` más reciente** (igual que hoy).
2. Si el candidato ganador por fecha es el **servidor** y `server.list_summary === true`:
   - Construir el resultado como **`{ ...server, ...heavyFromLocal }`** donde `heavyFromLocal` son:
     - `partes_contenido`: del **local** si el servidor no los trae (omitidos en resumen).
     - `source_text`: idem.
   - Opcional: si en el futuro el resumen incluye `segmentation` reducida y el local tiene `segmentation` completa más nueva en sentido de contenido, preferir la política documentada en implementación; para el MVP basta con **servidor gana en campos presentes en el resumen**, y campos omitidos se rellenan desde local.
3. Si el ganador es **local** más reciente que el servidor → comportamiento actual (quedarse con local).
4. Si el servidor **no** es resumen (p. ej. datos antiguos en caché) o trae `partes_contenido` explícito → merge **idéntico al actual** por `updated_at` sobre objetos completos.

**Invariante:** nunca persistir en backup un objeto que pierda `partes_contenido` presente en local **solo** porque el servidor envió un resumen más nuevo.

### 3.4 Paralelismo de IA

No se modifica `MAX_CONCURRENT_PARTS`, `asyncio.to_thread` para agentes, ni el ancho del pipeline de procesamiento. Este spec solo afecta **lecturas HTTP del listado** y **fusión en cliente**.

---

## 4. Pruebas

- **Backend:** test que `list_projects` (o el endpoint final) no incluye claves `partes_contenido` ni `source_text` en la respuesta serializada; incluye `list_summary: true`.
- **Frontend:** tests unitarios de `mergeProjects` con casos:
  - resumen servidor más nuevo + local con `partes_contenido` → resultado conserva cuerpo local y metadatos del servidor;
  - local más nuevo → sin cambio respecto al comportamiento previo;
  - servidor completo más nuevo → servidor gana entero.

---

## 5. Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Código legado asume listado = proyecto completo | Buscar usos de `api('/api/projects')` y validar que abrir proyecto siempre pasa por `GET .../{id}` o caché ya rellenada. |
| `segmentation` aún grande | Fase 2: recortar o denormalizar contador de partes. |
| Tokens JWT en logs | No parte de este spec; evitar registrar query strings con token (revisión aparte). |

---

## 6. Criterios de éxito

- Memoria pico en el worker al listar proyectos con varios ítems grandes **mediblemente menor** (o ausencia de OOM en escenarios que antes fallaban).
- Lista de proyectos y flujo offline/backup **sin pérdida de contenido** generada por el nuevo merge.
- Pipeline de IA sin reducción de paralelismo respecto al estado actual del repositorio.
