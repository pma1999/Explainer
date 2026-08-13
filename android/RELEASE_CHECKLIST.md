# RELEASE_CHECKLIST — Smoke manual en dispositivo físico

> **Estado: PENDING — NO ejecutado.** Este gate es un pase manual con un
> dispositivo físico y credenciales reales de Supabase/FastAPI, fuera del
> alcance automatizable del repositorio (no hay emulador ni CI en el repo, y
> la evidencia de build/lint/tests no demuestra instalación, UI, WebView ni
> login reales). Marcar cada casilla solo después de ejecutarla de verdad.
> APK de prueba: `app/build/outputs/apk/release/app-release.apk` (firmado,
> instalable por sideload con `adb install` o copia manual).

## Preparación

- [ ] Instalar el APK release en un dispositivo físico (Android 8–16; ideal
      probar al menos un dispositivo Android 8/9 y uno Android 13+).
- [ ] Confirmar que la app abre con el launcher y que el icono y nombre son
      correctos. (RC-03: los assets del icono —adaptive tinta/gold
      `mipmap/ic_launcher` + `ic_launcher_round` con monochrome— ya existen y
      `scripts/verify_release.sh` los comprueba dentro del APK; lo que queda
      para este gate manual es la confirmación VISUAL en dispositivo, incluido
      el icono temático Android 13+.)
- [ ] Disponer de una cuenta real de Explainer (email/password) y de red.

## Auth

- [ ] Login fresco con credenciales correctas entra a la biblioteca.
- [ ] Login con contraseña incorrecta muestra el error accionable y NO deja
      estado roto (poder reintentar).
- [ ] Tras cerrar sesión, la biblioteca no muestra contenido del owner
      anterior; volver a entrar con el mismo owner restaura sus descargas.

## Biblioteca y descargas

- [ ] La lista remota de proyectos carga y refresca (pull/swipe y botón).
- [ ] Descargar un proyecto: progreso visible (estimado → exacto), estado
      final "descargado" y lectura offline disponible.
- [ ] Cancelar una descarga en curso: estado "cancelado", sin descarga
      parcial y sin romper la versión anterior si existía.
- [ ] Actualizar un proyecto con versión remota más nueva: reemplaza el
      contenido y conserva el progreso de lectura.
- [ ] Borrar un proyecto: elimina índice, cola y generaciones; no borra el
      proyecto remoto.
- [ ] Estado "actualización disponible" aparece cuando el remoto es más nuevo
      y desaparece tras descargar.

## Offline y red

- [ ] Con la descarga completa, activar modo avión y relanzar la app: el
      lector abre las secciones descargadas sin red.
- [ ] Con modo avión, el panel/aviso offline es explícito y la app no crashea.
- [ ] Reconectar tras modo avión: el refresh de token ocurre una sola vez y
      las operaciones pendientes se sincronizan (progreso local llega al
      remoto).
- [ ] Fallo de red durante una descarga: reintento con backoff, mensaje
      accionable, sin bucles ni pérdida de la versión anterior.

## Lector (cinco secciones y contenido)

- [ ] Las cinco pestañas canónicas existen y abren en orden:
      `explicacion`, `recorrido`, `recursos`, `esquema`, `repaso`.
- [ ] Markdown renderizado nativo (títulos, listas, código, enlaces) con
      degradación a texto/código seleccionable si algo falla.
- [ ] Diagrama Mermaid renderizado en la WebView local (sin red); un diagrama
      inválido degrada a código con error accesible.
- [ ] Recursos externos (`http`/`https`) abren en app externa; ningún esquema
      de URL del contenido se ejecuta dentro de la app.
- [ ] Esquema/repaso ausentes muestran "Genéralo en la web y actualiza la
      descarga" (no prometer generación on-demand).
- [ ] Progreso de lectura: avanza, persiste tras relanzar y llega al remoto
      al reconectar (marcar subsecciones, uniones y tombstones).

## Temas, accesibilidad y diseño

- [ ] Tema claro, oscuro y sistema (DataStore) funcionan y persisten.
- [ ] Texto escalable al 200 % sin cortes en biblioteca y lector.
- [ ] TalkBack: orden semántico correcto en lista, lector y acciones
      (login, descargar, cancelar, borrar, cerrar sesión).
- [ ] Rotación y pantallas compact/medium/expanded (incluido modo
      multi-ventana) sin cortes ni pérdida de estado de lectura.
- [ ] Transiciones cortas y haptics solo en confirmación/lectura/cancelación/
      fin; nada depende exclusivamente de movimiento o color.

## Almacenamiento y upgrade

- [ ] Espacio libre insuficiente (por debajo de `2 * esperado + 32 MiB`):
      mensaje explícito de bajo almacenamiento y la versión anterior se
      conserva.
- [ ] Upgrade por sideload (`adb install -r` con el mismo keystore): los
      snapshots descargados y el progreso se conservan tras la actualización.
- [ ] (Negativo) Un APK firmado con OTRA keystore NO instala sobre el
      anterior sin desinstalar (confirma que la firma protege el upgrade).

## Registro de ejecución

| Fecha | Dispositivo / Android | Resultado | Incidencias |
|---|---|---|---|
| (pendiente) | | | |

Después de pasar el gate completo, marcar la sección "Estado" como `PASSED`
con la fecha, dispositivo y quién lo ejecutó.
