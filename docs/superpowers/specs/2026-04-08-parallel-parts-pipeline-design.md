# Spec: Paralelización de partes del pipeline (concurrencia acotada k = 5)

**Fecha:** 2026-04-08  
**Estado:** Aprobado  
**Alcance:** Fase de procesamiento por **parte** en `_process_project` (`main.py`) tras una segmentación válida — PDF, texto web y YouTube. No cambia el segmentador ni los contratos JSON de los agentes.

---

## 1. Problema

Hoy el pipeline recorre `segmentation["partes"]` con un bucle **`for` secuencial**. En cada iteración:

1. Prepara la fuente por parte (sub-PDF, segmento textual subido, o prompt YouTube).
2. Ejecuta en paralelo **dentro** de la parte: todos los explainers de subparte + recorrido + recursos (`asyncio.gather`).
3. Lanza el **formatter** como `asyncio.create_task` en segundo plano para no bloquear la siguiente parte.

Eso ya solapa el formatter de la parte *i* con los agentes de la parte *i+1*, pero **no** solapa los agentes de varias partes distintas. Si las partes son independientes una vez conocida la segmentación, el tiempo total queda inflado por la suma de las duraciones “agentes” de cada parte, salvo el solapamiento parcial con formatters.

**Objetivo:** Reducir la latencia end-to-end del proyecto manteniendo la semántica de resultados y acotando la presión sobre APIs y memoria.

---

## 2. Hipótesis de independencia (validada en código)

Tras el segmentador, cada parte consume:

- Su propio **alcance de fuente** (sub-PDF con buffer, rango de bloques web, o vídeo completo según el diseño actual).
- Un **handoff** derivado del JSON del segmentador y de datos globales ya fijos (`description`, `consideraciones_estudiante`).

La **continuidad textual entre parte N−1 y parte N** no depende del output del explainer de la parte anterior. La función `_continuity_block_from_previous_part` en `main.py` usa exclusivamente campos del **segmentador** sobre la parte previa (`titulo`, `contenido`, `temas_cubiertos`), documentado como *"Use segmentador summaries only (no explainer output required)."*

Por tanto **no existe dependencia de orden de finalización** entre partes para la corrección de los prompts aguas abajo. Paralelizar partes no rompe el contrato semántico actual.

**Matiz:** El orden de eventos SSE y de logs puede intercalarse entre `part_id`; el cliente debe seguir identificando eventos por `part_id` (comportamiento ya razonable para UI).

---

## 3. Solución elegida

### 3.1 Modelo de concurrencia

- Introducir una constante **`MAX_CONCURRENT_PARTS = 5`** (nombre exacto puede ajustarse al estilo del fichero, pero debe ser un único punto de configuración en el ámbito del pipeline de partes).
- Usar **`asyncio.Semaphore(MAX_CONCURRENT_PARTS)`** para limitar cuántas partes pueden estar simultáneamente en la fase **costosa** (preparación de fuente + ejecución de agentes + escritura en memoria de `partes_contenido` para esa parte).
- Sustituir el `for` secuencial por **una corrutina por parte** y **`await asyncio.gather(*tasks, return_exceptions=True)`** (o equivalente) sobre todas las partes, recogiendo excepciones por tarea sin tumbar el conjunto si el comportamiento actual por parte es tolerante a fallos parciales — **alinear con la política existente** del bucle: si hoy un fallo en una parte aborta todo el proceso, mantenerlo; si hoy se registra y continúa, mantenerlo).

### 3.2 Alcance del semáforo (crítico)

El semáforo debe **liberarse al terminar** la fase de agentes y haber actualizado en memoria el resultado de esa parte (explainer ensamblado, recorrido, recursos), **antes** de encolar el formatter en background.

Así:

- Como mucho **5** partes ejecutan agentes a la vez.
- Los **formatter** pueden seguir acumulándose en paralelo (como hoy con varias tareas en vuelo), sin consumir un slot del semáforo.

Esto preserva la propiedad actual de solapar **formatter(parte i)** con **agentes(parte j)** y maximiza el paralelismo útil.

### 3.3 Refactor estructural mínimo

- Extraer el cuerpo actual del bucle `for parte in partes_segmentadas` a una corrutina interna, por ejemplo **`_run_part_agents_pipeline(...)`** (nombre definitivo a criterio de implementación), con todos los parámetros necesarios ya disponibles en el closure de `_process_project` o pasados explícitamente (evitar variables mutables compartidas mal documentadas).
- La corrutina debe incluir:
  - Construcción de `continuidad_previa` / `handoff` como hoy (solo lectura de `partes_segmentadas`).
  - Preparación de fuente y prompts.
  - `asyncio.gather` de explainers + recorrido + recursos.
  - Ensamblado del explainer y asignación a `partes_contenido[str(part_id)]`.
  - `asyncio.create_task(_format_and_finalize_part(...))` y devolver la tarea (o añadirla a una lista compartida de forma segura).
- Envolver el núcleo “solo una parte a la vez respecto al semáforo” con:
  ```text
  async with semaphore:
      ...  # hasta justo antes de create_task(formatter)
  ```
  y **fuera** del `async with`, registrar el `formatter_task`.

### 3.4 Estado compartido y sincronización

| Recurso | Riesgo actual si se paraleliza | Mitigación |
|--------|---------------------------------|------------|
| `cumulative_usage` y `_update_usage` | Mutación concurrente del dict + `update_project` + condiciones de carrera en contadores | Introducir **`usage_lock = asyncio.Lock()`**. Toda actualización de uso y los `send_event` asociados a `usage_update` que dependan de un estado coherente deben ejecutarse **bajo** `async with usage_lock:` (mínimo: serializar `_update_usage` y el envío inmediato posterior si aplica). |
| `partes_contenido` | Claves distintas por `part_id`; escritura concurrente en la misma clave no debe ocurrir | Cada tarea solo modifica `partes_contenido[str(part_id)]`. Mantener esta invariante. |
| `update_project(..., {"partes_contenido": partes_contenido})` | Varias llamadas concurrentes serializan el JSON completo desde el mismo dict en memoria | Válido si el dict es la única fuente de verdad y cada parte solo toca su entrada. No introducir lecturas desde BD que reemplacen el dict intermedio sin merge. |
| `segment_pdf_paths` / `temp_paths` (y similares) | `list.append` concurrente | Evitar append concurrente: devolver rutas desde la corrutina de parte y **fusionar** en listas maestras en el hilo principal tras `gather`, o usar un `asyncio.Lock` dedicado para esas listas (preferible acumular retornos y extender una vez). |
| Logs `LogContext` | Debe seguir anotando `part_id` correctamente | Mantener `with LogContext(..., part_id=part_id)` por parte. |

### 3.5 Espera final de formatters

Conservar el patrón actual:

- Acumular `formatter_tasks`.
- Tras completar **todas** las corrutinas de parte (agentes), ejecutar **`await asyncio.gather(*formatter_tasks, return_exceptions=True)`**.
- Agregar costes de formatter desde `partes_contenido` como hoy (tras garantizar que no hay carreras en la agregación — hoy se asume que el dict está estable tras terminar los formatters).

### 3.6 Constantes y configuración futura

- `MAX_CONCURRENT_PARTS = 5` es el valor aprobado; la implementación puede preparar el terreno para leerlo de variable de entorno **opcional** en un paso posterior, pero **no es requisito** de esta spec salvo que se decida explícitamente en la misma PR (YAGNI: solo constante si no hay necesidad inmediata).

---

## 4. Comportamiento observable

- **Logs:** Mensajes existentes por parte deben conservarse; puede añadirse un log de inicio/fin de lote o de adquisición del semáforo a nivel debug si ayuda a diagnóstico.
- **SSE:** Eventos `part_started`, `agent_completed`, `part_completed`, `usage_update` pueden llegar en orden distinto al índice de parte; debe documentarse en comentario de implementación si el frontend asume orden estricto (no requerido por esta spec).

---

## 5. Ficheros afectados

| Fichero | Cambio previsto |
|---------|------------------|
| `main.py` | Semáforo, lock de uso, refactor a corrutina por parte, `gather` de tareas de parte, fusión segura de listas de temporales, constante `MAX_CONCURRENT_PARTS`. |

No se requieren cambios en `backend/agents/*` ni en el segmentador para cumplir esta spec.

---

## 6. Pruebas y verificación

1. **Regresión:** Proyecto con **una** parte — comportamiento equivalente al actual (salvo variación menor de orden de eventos).
2. **Varias partes:** Resultado funcional equivalente al procesamiento secuencial (mismas claves en `partes_contenido`, mismos campos por agente), permitiendo diferencias solo en orden de SSE.
3. **Concurrencia:** Prueba o instrumentación que verifique que no más de **5** ejecuciones “agentes” de partes distintas se solapan en el tiempo (p. ej. contador bajo semáforo en modo test, o mock que registra solapamiento).
4. **Uso acumulado:** Tras el pipeline, `usage` debe ser la **suma coherente** de todas las fases; sin valores negativos ni doble conteo por carreras (validar con lock).

---

## 7. Criterios de éxito

1. Hasta **5** partes pueden tener la fase de agentes en curso **simultáneamente** (preparación + `gather` intra-parte incluidos en el slot).
2. El formatter **no** consume un slot del semáforo de partes.
3. No hay regresiones de datos en `partes_contenido` ni en `usage` atribuibles a condiciones de carrera.
4. La semántica de prompts y handoff coincide con la versión secuencial previa.

---

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Picos de llamadas a APIs (Gemini / OpenRouter) | k = 5 acota el grado de paralelismo de agentes; monitorizar 429 y valorar bajar k o backoff en iteraciones futuras. |
| Memoria (varios sub-PDFs / segmentos en paralelo) | Mismo acotamiento; documentar para operaciones. |
| Errores intermitentes difíciles de reproducir por orden | Tests de concurrencia y lock en uso; logs claros por `part_id`. |

---

## 9. Fuera de alcance

- Cambiar el número de llamadas a los modelos por parte.
- Reordenar o fusionar partes en el segmentador.
- Garantizar orden total de eventos SSE por tiempo.
- Paralelizar otras fases globales (segmentación, clasificador de páginas, etc.).

---

## 10. Referencias en código (estado al redactar esta spec)

- Bucle secuencial y `formatter_tasks`: comentarios en `main.py` alrededor de `# Procesar cada parte` y del `create_task` del formatter.
- Continuidad sin explainer previo: `_continuity_block_from_previous_part` y docstring asociado.
- Persistencia por parte en formatter: `_format_and_finalize_part`.

---

## 11. Próximo paso tras esta spec

Generar un plan de implementación detallado (skill `writing-plans`): orden de edición, puntos de verificación manual y comandos de test a ejecutar antes de merge.
