# Spec: Garantía de cobertura de páginas en la segmentación PDF

**Fecha:** 2026-03-30
**Estado:** Aprobado
**Alcance:** Solo fuentes PDF (web y YouTube no tienen páginas; no se ven afectadas)

---

## Problema

El agente segmentador puede producir rangos de página (`pagina_inicio`/`pagina_fin`) que:

1. **Dejan páginas de contenido sin cubrir** — una página con material académico no queda dentro del rango de ninguna parte, por lo que ningún agente la explica jamás.
2. **Solapan páginas entre partes** — dos partes reciben el mismo intervalo de páginas, generando explicación duplicada.

Ambos problemas ocurren también a nivel de **subpartes** dentro de una parte (huecos o solapamientos entre subrangos).

La validación MECE de temas (`validate_tema_partition`) ya existe y funciona, pero opera sobre entidades semánticas (temas), no sobre rangos de página numéricos. Un tema puede quedar correctamente asignado a una parte aunque el rango de páginas de esa parte esté mal delimitado.

---

## Solución — Enfoque C

Arquitectura en cuatro capas nuevas + un loop de retry unificado:

1. **Clasificador de páginas** (`gemini-3-flash-preview`): identifica qué páginas son contenido sustantivo.
2. **Inyección de restricción** en el prompt del segmentador: el clasificador informa al segmentador qué páginas debe cubrir.
3. **Validación determinista en código** (`segmentation_page_coverage.py`): verifica rangos en dos niveles (partes y subpartes).
4. **Retry unificado**: temas y páginas se validan en el mismo loop, con mensajes de corrección precisos.

---

## Ficheros afectados

| Fichero | Tipo | Cambio |
|---|---|---|
| `backend/gemini_model_routing.py` | Modificado | + `MODEL_CLASSIFIER` |
| `backend/agents/page_classifier.py` | Nuevo | Agente clasificador de páginas |
| `backend/segmentation_page_coverage.py` | Nuevo | Validación de rangos + retry suffix |
| `backend/agents/segmentador.py` | Modificado | + PASO 8 en `thinking_protocol` del PDF |
| `main.py` | Modificado | Integración del clasificador + loop unificado |

Los agentes downstream (explainer, recorrido, resources) **no se modifican**: ya reciben instrucciones de scope correctas mediante `_pdf_scope_instructions`, que distingue explícitamente páginas núcleo (objetivo de estudio) de páginas buffer (solo contexto de continuidad).

---

## Detalle de implementación

### 1. `backend/gemini_model_routing.py`

Añadir al fichero existente:

```python
MODEL_CLASSIFIER = "gemini-3-flash-preview"
```

Posición: junto a `MODEL_SEGMENTADOR` y `MODEL_AGENTS`, con un comentario que explique su propósito:

```python
MODEL_CLASSIFIER = "gemini-3-flash-preview"   # Clasificador ligero de páginas de contenido vs. accesorias
```

---

### 2. `backend/agents/page_classifier.py` (nuevo)

#### Propósito
Recibir el PDF numerado (con marcas `— Página X / N —`) y devolver, en un único JSON, qué rangos de páginas contienen contenido sustantivo y cuáles son accesorios.

#### Modelo
`MODEL_CLASSIFIER = "gemini-3-flash-preview"`. Se importa desde `backend.gemini_model_routing`.

#### System instruction
Breve y directa. No necesita `thinking_level` alto. Puntos clave:

- Rol: "Eres un clasificador de páginas de documentos académicos. Tu única función es identificar qué páginas contienen contenido sustantivo que un estudiante debe aprender, y cuáles son páginas accesorias."
- Definición de **contenido sustantivo**: texto académico, técnico, jurídico o científico que forma el cuerpo principal del documento.
- Definición de **accesorios**: portada, contraportada, páginas en blanco, tabla de contenidos / índice, agradecimientos, dedicatoria, prólogo sin contenido del tema, bibliografía, referencias, notas finales, copyright, ISBN.
- Instrucción operativa: "Usa las marcas visibles `— Página X / N —` para identificar el número de cada página. Lee el documento completo y devuelve el resultado en el JSON estructurado indicado."
- Política de dudas: si una página tiene mezcla (p. ej. una introducción temática corta + bibliografía al final), clasifícala como contenido si contiene al menos un párrafo sustantivo.

#### `thinking_config`
`thinking_level="LOW"` — la tarea es simple y la velocidad importa.

#### Schema de respuesta (JSON estructurado)

```python
RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["total_paginas", "rangos_contenido", "rangos_no_contenido"],
    properties={
        "total_paginas": genai.types.Schema(
            type=genai.types.Type.INTEGER,
            description="Número total de páginas del documento (según las marcas visibles).",
        ),
        "rangos_contenido": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Rangos de páginas con contenido sustantivo. Deben ser contiguos y no solapantes.",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["inicio", "fin"],
                properties={
                    "inicio": genai.types.Schema(type=genai.types.Type.INTEGER),
                    "fin":    genai.types.Schema(type=genai.types.Type.INTEGER),
                },
            ),
        ),
        "rangos_no_contenido": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Rangos de páginas accesorias (portada, índice, bibliografía, páginas en blanco, etc.).",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["inicio", "fin", "razon"],
                properties={
                    "inicio": genai.types.Schema(type=genai.types.Type.INTEGER),
                    "fin":    genai.types.Schema(type=genai.types.Type.INTEGER),
                    "razon":  genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="Descripción breve: 'portada', 'tabla de contenidos', 'bibliografía', etc.",
                    ),
                },
            ),
        ),
    },
)
```

#### Función pública

```python
@gemini_retry(max_retries=5)
def run_page_classifier(
    api_key: str,
    file_uri: str,
    total_pages: int,
    model: str = MODEL_CLASSIFIER,
    mime_type: str = "application/pdf",
) -> frozenset[int]:
    """Classify PDF pages into content vs. non-content.

    Returns a frozenset of 1-indexed page numbers that contain substantive content.
    On any unrecoverable error the caller receives PageClassifierFallback.

    Args:
        total_pages: Expected total page count (from pypdf, used for sanity-check against
                     the model's own count). If they differ, logs a warning but trusts the
                     model's classification and proceeds.
    """
```

El decorador `@gemini_retry(max_retries=5)` ya existe en el proyecto y gestiona reintentos internos.

#### Fallback

Si `run_page_classifier` lanza excepción incluso tras todos los reintentos internos del decorador, el **caller en `main.py`** captura la excepción y procede con fallback conservador:

```python
content_page_set = frozenset(range(1, total_pages + 1))  # todas las páginas = contenido
logger.warning("[Process] Clasificador de páginas falló; se asume todas las páginas como contenido")
```

Esto garantiza que un fallo del clasificador nunca detiene el pipeline: simplemente se pierde la precision de distinguir páginas accesorias, pero la validación posterior sigue operando (solo overlaps serán detectables con certeza; gaps en accesorias no generarán falsos errores).

#### Construcción del `content_page_set`

A partir del JSON devuelto, `main.py` construye:

```python
content_page_set: frozenset[int] = frozenset(
    p
    for r in result["rangos_contenido"]
    for p in range(r["inicio"], r["fin"] + 1)
)
```

---

### 3. `backend/segmentation_page_coverage.py` (nuevo)

Módulo análogo a `segmentation_tema_coverage.py`. Contiene:

#### Constantes

```python
MAX_PAGE_COVERAGE_ATTEMPTS = 3  # intentos independientes del loop de temas
SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE = (
    "La segmentación no pudo asignar correctamente los rangos de página "
    "tras varios intentos. Revisa el documento o vuelve a intentar el procesamiento."
)
```

#### Dataclasses del informe

```python
@dataclass(frozen=True, slots=True)
class PartPageError:
    type: str  # "invalid_range" | "overlap" | "missing_content_pages"
    part_numero: int
    detail: str  # descripción legible del error

@dataclass(frozen=True, slots=True)
class SubpartPageError:
    type: str  # "invalid_range" | "gap" | "overlap" | "doesnt_start_at_part" | "doesnt_end_at_part"
    part_numero: int
    subpart_numero: int
    detail: str

@dataclass(frozen=True, slots=True)
class PageCoverageReport:
    is_valid: bool
    part_errors: tuple[PartPageError, ...]
    subpart_errors: tuple[SubpartPageError, ...]
```

#### `validate_page_coverage`

```python
def validate_page_coverage(
    segmentation: dict[str, Any],
    content_page_set: frozenset[int],
) -> PageCoverageReport:
```

**Algoritmo — Nivel 1 (partes):**

1. Extraer `partes` del segmentation dict. Si no es lista → error estructural.
2. Para cada parte, extraer `pagina_inicio` y `pagina_fin` como enteros. Si alguno falta o no es entero → `PartPageError(type="invalid_range", ...)`.
3. Ordenar partes por `pagina_inicio`.
4. Para partes consecutivas `(i, i+1)`: si `partes[i].pagina_fin >= partes[i+1].pagina_inicio` → `PartPageError(type="overlap", detail=f"Parte {a} (hasta pág. {x}) y Parte {b} (desde pág. {y}) se solapan")`.
5. Construir `covered_pages = frozenset(p for parte in partes for p in range(pi, pf+1))`.
6. `missing = content_page_set - covered_pages`. Si `missing` no vacío → `PartPageError(type="missing_content_pages", detail=f"Páginas de contenido sin cubrir: {sorted(missing)}")`.

**Algoritmo — Nivel 2 (subpartes, solo si nivel 1 sin errores para esa parte):**

Para cada parte sin errores de rango:

1. Si `subpartes` está vacío o ausente: no hay nada que validar (es válido; el procesador usa la parte completa como subparte única).
2. Extraer `pagina_inicio`/`pagina_fin` de cada subparte. Si falta → `SubpartPageError(type="invalid_range", ...)`.
3. Ordenar subpartes por `pagina_inicio`.
4. Verificar que `subpartes[0].pagina_inicio == parte.pagina_inicio`. Si no → `SubpartPageError(type="doesnt_start_at_part", detail=f"La primera subparte empieza en pág. {x} pero la parte empieza en pág. {y}")`.
5. Verificar que `subpartes[-1].pagina_fin == parte.pagina_fin`. Si no → `SubpartPageError(type="doesnt_end_at_part", ...)`.
6. Para subpartes consecutivas `(j, j+1)`:
   - Si `subpartes[j].pagina_fin + 1 < subpartes[j+1].pagina_inicio` → `SubpartPageError(type="gap", detail=f"Hueco entre subparte {a} (hasta pág. {x}) y subparte {b} (desde pág. {y})")`.
   - Si `subpartes[j].pagina_fin >= subpartes[j+1].pagina_inicio` → `SubpartPageError(type="overlap", ...)`.

**Resultado:** `is_valid = not part_errors and not subpart_errors`.

#### `build_page_coverage_retry_suffix`

```python
def build_page_coverage_retry_suffix(
    *,
    attempt: int,
    segmentation: dict[str, Any],
    report: PageCoverageReport,
    content_page_set: frozenset[int],
) -> str:
```

Genera un bloque `<correccion_rangos_pagina>` con:

```
<correccion_rangos_pagina>
Intento de corrección: N. Los rangos de página de la respuesta anterior no son correctos.

PÁGINAS DE CONTENIDO QUE DEBEN CUBRIRSE (referencia):
  [lista compacta de rangos, ej: 3-112]

ERRORES EN RANGOS DE PARTES:
  [solo si los hay]
  - Parte X: rango inválido — [detail]
  - Partes X y Y se solapan en páginas Z-W
  - Páginas de contenido sin cubrir por ninguna parte: [lista]

ERRORES EN RANGOS DE SUBPARTES:
  [solo si los hay, agrupados por parte]
  Parte X:
    - Subparte Y: [detail del error]

REQUISITOS PARA LA CORRECCIÓN:
  - pagina_inicio y pagina_fin de cada parte deben ser enteros positivos con pagina_inicio ≤ pagina_fin.
  - Los rangos de las partes no deben solaperse (parte_i.pagina_fin < parte_{i+1}.pagina_inicio).
  - Todas las páginas de contenido deben quedar dentro del rango de exactamente una parte.
  - Las subpartes de cada parte deben ser contiguas (subparte_j.pagina_fin + 1 == subparte_{j+1}.pagina_inicio).
  - La primera subparte de cada parte debe empezar en pagina_inicio de la parte.
  - La última subparte de cada parte debe terminar en pagina_fin de la parte.

RESPUESTA ANTERIOR (referencia mínima — corrige y devuelve el JSON completo válido):
[resumen compacto de rangos de la segmentación anterior]
</correccion_rangos_pagina>
```

La sección "RESPUESTA ANTERIOR" usa una función auxiliar análoga a `_compact_previous_assignment_json` que extrae solo `numero`, `titulo`, `pagina_inicio`, `pagina_fin` de partes y subpartes (no el texto completo, para no exceder contexto).

---

### 4. `backend/agents/segmentador.py` — PASO 8 en `thinking_protocol` (PDF)

Al final de la sección `<thinking_protocol>` del `SYSTEM_INSTRUCTION` del PDF (no del texto/web), añadir:

```
**PASO 8 — VERIFICACIÓN EXPLÍCITA DE COBERTURA DE PÁGINAS:**
Si tu input incluye una sección `<paginas_contenido_verificado>`, ejecuta este paso obligatoriamente:

1. Copia la lista de páginas de contenido del bloque `<paginas_contenido_verificado>`.
2. Para cada página de contenido, confirma en qué parte (número) y subparte (número) queda asignada.
   Construye mentalmente una tabla: página → parte → subparte.
3. Verifica que ninguna página de contenido queda sin asignación (faltaría en la tabla).
4. Verifica que ninguna página de contenido aparece en más de una parte (duplicado en la tabla).
5. Para cada parte, verifica que sus subpartes cubren exactamente el rango [pagina_inicio, pagina_fin]:
   - La primera subparte empieza en pagina_inicio de la parte.
   - La última subparte termina en pagina_fin de la parte.
   - No hay huecos entre subpartes consecutivas (subparte_j.pagina_fin + 1 == subparte_{j+1}.pagina_inicio).
   - No hay solapamientos entre subpartes consecutivas.
6. Si detectas algún error, corrígelo antes de generar el output.

Solo tras completar este paso sin errores, genera tu output estructurado.
```

---

### 5. `main.py` — Integración completa

#### 5.1 Imports nuevos

```python
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_SEGMENTADOR, MODEL_CLASSIFIER
from backend.agents.page_classifier import run_page_classifier
from backend.segmentation_page_coverage import (
    MAX_PAGE_COVERAGE_ATTEMPTS,
    SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE,
    build_page_coverage_retry_suffix,
    validate_page_coverage,
)
```

#### 5.2 Obtención del `total_pages` del PDF numerado

Después de `add_page_numbers(pdf_path)` ya se tiene `numbered_pdf_path`. El número total de páginas se obtiene con `pypdf.PdfReader`:

```python
from pypdf import PdfReader
# ... tras crear numbered_pdf_path:
pdf_total_pages = len(PdfReader(numbered_pdf_path).pages)
```

#### 5.3 Llamada al clasificador (antes del loop de segmentación)

```python
content_page_set: frozenset[int] = frozenset()
if is_pdf_source and numbered_pdf_path:
    await send_event(project_id, {"type": "classifying_pages"})
    try:
        content_page_set = await asyncio.to_thread(
            run_page_classifier,
            api_key,
            file_uri,          # URI del PDF numerado ya subido a Gemini
            pdf_total_pages,
            MODEL_CLASSIFIER,
        )
        logger.info(
            f"[Process] Clasificador: {len(content_page_set)} páginas de contenido de {pdf_total_pages}",
            extra={"content_pages_count": len(content_page_set), "total_pages": pdf_total_pages},
        )
    except Exception as clf_err:
        content_page_set = frozenset(range(1, pdf_total_pages + 1))
        logger.warning(
            f"[Process] Clasificador de páginas falló, asumiendo todas como contenido: {clf_err}",
            extra={"error_type": type(clf_err).__name__},
        )
```

> **Nota sobre el `file_uri`:** el PDF numerado ya está subido a Gemini en este punto del pipeline (se sube antes de la segmentación). Se reutiliza el mismo `file_uri`. No hay upload adicional.

#### 5.4 Inyección del mapa de contenido en el prompt del segmentador

Función auxiliar a añadir en `main.py`:

```python
def _build_content_pages_prefix(content_page_set: frozenset[int], total_pages: int) -> str:
    """Build the <paginas_contenido_verificado> block injected into the segmentador prompt."""
    if not content_page_set:
        return ""
    sorted_pages = sorted(content_page_set)
    # Compactar en rangos legibles: [1,2,3,5,6] → "1-3, 5-6"
    ranges = []
    start = prev = sorted_pages[0]
    for p in sorted_pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    content_str = ", ".join(ranges)

    non_content = sorted(set(range(1, total_pages + 1)) - content_page_set)
    if non_content:
        nc_ranges = []
        s = pr = non_content[0]
        for p in non_content[1:]:
            if p == pr + 1:
                pr = p
            else:
                nc_ranges.append(f"{s}-{pr}" if s != pr else str(s))
                s = pr = p
        nc_ranges.append(f"{s}-{pr}" if s != pr else str(s))
        non_content_str = f"\nPáginas sin contenido (accesorias, pueden excluirse): {', '.join(nc_ranges)}"
    else:
        non_content_str = ""

    return (
        "<paginas_contenido_verificado>\n"
        f"Páginas con contenido sustantivo (DEBEN cubrirse): {content_str}{non_content_str}\n"
        "RESTRICCIÓN OBLIGATORIA: Los rangos pagina_inicio/pagina_fin de las partes deben cubrir "
        "colectivamente TODAS las páginas de contenido, sin huecos ni solapamientos entre partes. "
        "Las subpartes de cada parte deben ser contiguas y cubrir exactamente el rango de su parte padre.\n"
        "</paginas_contenido_verificado>\n\n"
    )
```

#### 5.5 Loop de retry unificado

Reemplaza el loop actual de `MAX_SEGMENTATION_COVERAGE_ATTEMPTS` por:

```python
# Máximo de intentos = max de ambos límites (el loop unifica ambas validaciones)
MAX_COMBINED_ATTEMPTS = max(MAX_SEGMENTATION_COVERAGE_ATTEMPTS, MAX_PAGE_COVERAGE_ATTEMPTS)

segmentation: dict | None = None
tema_report = None
page_report = None
content_pages_prefix = (
    _build_content_pages_prefix(content_page_set, pdf_total_pages)
    if is_pdf_source and content_page_set
    else ""
)

for seg_attempt in range(MAX_COMBINED_ATTEMPTS):
    # Construir descripción con sufijos de corrección si aplica
    base_desc = (project["description"].strip() or DEFAULT_DESCRIPTION)

    if seg_attempt == 0:
        seg_description = content_pages_prefix + base_desc
    else:
        assert segmentation is not None
        correction_parts = []
        if tema_report is not None and not tema_report.is_valid:
            correction_parts.append(
                build_tema_coverage_retry_suffix(
                    attempt=seg_attempt,
                    segmentation=segmentation,
                    report=tema_report,
                )
            )
        if page_report is not None and not page_report.is_valid and is_pdf_source:
            correction_parts.append(
                build_page_coverage_retry_suffix(
                    attempt=seg_attempt,
                    segmentation=segmentation,
                    report=page_report,
                    content_page_set=content_page_set,
                )
            )
        correction_suffix = "\n\n".join(correction_parts)
        seg_description = content_pages_prefix + base_desc + "\n\n" + correction_suffix

    segmentation, usage_meta = await asyncio.to_thread(
        run_segmentador,
        api_key,
        file_uri,
        seg_description,
        MODEL_SEGMENTADOR,
        source_mime_type,
        source_kind,
    )
    phase = "segmentation" if seg_attempt == 0 else f"segmentation_retry_{seg_attempt}"
    _update_usage(usage_meta, phase=phase, cost_model=MODEL_SEGMENTADOR)
    await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

    tema_report = validate_tema_partition(segmentation)
    page_report = (
        validate_page_coverage(segmentation, content_page_set)
        if is_pdf_source
        else None  # No-PDF sources: page validation not applicable
    )

    both_valid = tema_report.is_valid and (page_report is None or page_report.is_valid)

    if both_valid:
        if seg_attempt > 0:
            logger.info(
                "[Process] Segmentación corregida tras reintento (temas + páginas)",
                extra={"project_id": project_id, "seg_attempt": seg_attempt},
            )
        break

    # Log del fallo
    logger.warning(
        "[Process] Validación fallida; se reintentará el segmentador si quedan intentos",
        extra={
            "seg_attempt": seg_attempt,
            "tema_valid": tema_report.is_valid,
            "page_valid": page_report.is_valid if page_report else True,
            "tema_missing": len(tema_report.missing),
            "tema_duplicates": len(tema_report.duplicates),
            "page_part_errors": len(page_report.part_errors) if page_report else 0,
            "page_subpart_errors": len(page_report.subpart_errors) if page_report else 0,
        },
    )
else:
    # Agotados los intentos: error
    assert segmentation is not None
    error_bits = []
    if tema_report and not tema_report.is_valid:
        if tema_report.missing:
            error_bits.append(f"{len(tema_report.missing)} tema(s) sin asignar")
        if tema_report.duplicates:
            error_bits.append(f"{len(tema_report.duplicates)} tema(s) duplicados")
    if page_report and not page_report.is_valid:
        if page_report.part_errors:
            error_bits.append(f"{len(page_report.part_errors)} error(es) de rango en partes")
        if page_report.subpart_errors:
            error_bits.append(f"{len(page_report.subpart_errors)} error(es) de rango en subpartes")
    detail = "; ".join(error_bits) if error_bits else "inconsistencias en segmentación"
    logger.error(
        "[Process] Segmentación abortada tras agotar reintentos",
        extra={"attempts": MAX_COMBINED_ATTEMPTS, "detail": detail},
    )
    # Persistir estado de error y notificar (igual que en el código actual)
    # Reutilizar el mensaje genérico existente: el usuario no necesita distinguir el tipo de error
    user_message = SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE
    update_project(project_id, user_id, {
        "segmentation": segmentation,
        "partes_contenido": {},
        "status": "error",
        "error_message": user_message,
    })
    await send_event(project_id, {"type": "error", "message": user_message})
    return
```

---

## Instrucciones de scope en agentes downstream — sin cambios

El sistema ya cuenta con `_pdf_scope_instructions` que, en modo `subpdf_buffered`, distingue explícitamente:

- **Páginas NÚCLEO** (`pagina_inicio`–`pagina_fin` de la subparte): objetivo de estudio.
- **Páginas CONTEXTO (buffer)**: solo para recuperar enunciados partidos; no se desarrollan como bloques didácticos independientes, no se les asigna peso comparable al núcleo.

Este comportamiento cubre correctamente el requisito de que los agentes no expliquen contenido fuera de su fragmento asignado. No se realizan cambios en `explainer.py`, `recorrido.py` ni `resources.py`.

---

## Flujo completo del pipeline PDF (con los cambios)

```
PDF upload
  → add_page_numbers()                   [PDF numerado]
  → upload to Gemini                     [file_uri]
  → run_page_classifier()                [content_page_set]  ← NUEVO
  ↓
  for seg_attempt in range(MAX):
    → run_segmentador(desc + prefix + corrections)           ← MODIFICADO
    → validate_tema_partition()          [tema_report]
    → validate_page_coverage()           [page_report]       ← NUEVO
    → if both valid: break
    → else: build combined correction suffix
  ↓
  → for each parte:
      → extract_page_range(buffer=1)     [sub-PDF]
      → upload sub-PDF
      → asyncio.gather(
          run_subpart_explainer × N,
          run_recorrido,
          run_resources,
        )
  ↓
  → format + persist + SSE
```

---

## Criterios de éxito

1. Para cualquier PDF, tras la segmentación, toda página en `content_page_set` aparece en el rango de exactamente una parte.
2. Para cualquier parte, sus subpartes cubren exactamente `[pagina_inicio, pagina_fin]` de la parte sin huecos ni solapamientos.
3. Si el clasificador falla (5 reintentos agotados), el pipeline continúa con fallback conservador y log de warning, sin error de usuario.
4. El número total de llamadas al segmentador no supera `MAX_COMBINED_ATTEMPTS` por proyecto.
5. Los agentes downstream (explainer, recorrido, resources) no sufren cambios de comportamiento: siguen recibiendo el sub-PDF con buffer y las instrucciones de scope ya existentes.
