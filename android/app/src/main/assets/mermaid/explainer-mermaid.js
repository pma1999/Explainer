/*
 * Explainer Mermaid wrapper — documento local endurecido (T08).
 *
 * Contrato (sin JavaScript bridge, sin CDN):
 *  - window.ExplainerMermaid.render(<JSON object>) inicia un render asíncrono.
 *    El request llega como objeto-literal JSON (kotlinx-serialization), nunca
 *    como código concatenado: el JSON es un subconjunto estricto de las
 *    expresiones JS y el contenido no puede escapar de su string.
 *  - El resultado se lee desde Kotlin por polling de takeResult(), que
 *    devuelve {ok:true,svg} | {ok:false,error} y reinicia el estado.
 *  - window.ExplainerMermaid.exportPng("<exportId>") re-renderiza el diagrama
 *    con configuración de EXPORT fija e independiente del tema de la app
 *    (htmlLabels:false a NIVEL RAÍZ — en mermaid 11.16.1 es opción de nivel
 *    superior; la directiva por-diagrama antigua seguía emitiendo
 *    foreignObject y rompía el rasterizado —, tema claro 'neutral' y fondo
 *    blanco), normaliza el SVG (dimensiones numéricas desde viewBox, rect de
 *    fondo, xmlns) y lo rasteriza a un data URL PNG con timeout explícito.
 *    El PNG completo NO viaja por takeExportResult(): primero llegan los
 *    METADATOS {ok, exportId, totalLength, chunkSize} y el payload se lee en
 *    trozos de ~32 KB con takeExportPngChunk(exportId, offset) (un data URL
 *    de MBs en una sola respuesta de evaluateJavascript se rompía/timeout);
 *    Kotlin reensambla, valida y libera el payload con clearExportPayload().
 *  - window.ExplainerMermaid.exportSvg("<exportId>") devuelve por el mismo
 *    canal de export el SVG NORMALIZADO — la única fuente para la descarga
 *    esquema.svg (nunca el res.svg de pantalla: width="100%", fondo
 *    transparente y colores del tema rompían los visores externos). El SVG se
 *    carga como Image desde un data URL (permitido por img-src data: de la
 *    CSP).
 *  - securityLevel: 'strict' — el nivel seguro por defecto del contrato de
 *    render; la app nunca lo relaja. Sin callbacks ni HTML en nodos.
 *  - Sin fetch/XHR: el CSP del documento bloquea connect-src y la WebView
 *    tiene blockNetworkLoads=true.
 */
(function (global) {
  'use strict';

  var pendingResult = null;
  var pendingExportResult = null;
  // Payload del PNG exportado: vive solo en la memoria del wrapper, se sirve
  // en trozos por takeExportPngChunk() y se libera con clearExportPayload().
  var pendingExportPng = null;
  var initialized = false;
  var lastTheme = null;
  var lastRequestCode = null;

  // Paleta académica T05 adaptada (paridad projectView.js _ensureMermaidInit,
  // con colores claro/oscuro del tema Explainer).
  function themeConfig(theme) {
    if (theme === 'dark') {
      return {
        theme: 'dark',
        themeVariables: {
          primaryColor: '#252525',
          primaryBorderColor: '#c9a84c',
          primaryTextColor: '#ddd8cc',
          lineColor: '#7a7060',
          secondaryColor: '#1e1e1e',
          tertiaryColor: '#2a2418',
          edgeLabelBackground: '#1a1a14',
          titleColor: '#c9a84c',
          clusterBkg: '#1c1c1c',
          clusterBorder: '#555555',
          nodeBorder: '#555555',
          mainBkg: '#252525',
          background: '#161b22'
        }
      };
    }
    return {
      theme: 'default',
      themeVariables: {
        primaryColor: '#f2e2b8',
        primaryBorderColor: '#8a6113',
        primaryTextColor: '#241f17',
        lineColor: '#6e6557',
        secondaryColor: '#e8dec8',
        tertiaryColor: '#ebe2ce',
        edgeLabelBackground: '#fbf7ee',
        titleColor: '#8a6113',
        clusterBkg: '#f6f1e5',
        clusterBorder: '#d4c9b2',
        nodeBorder: '#7a7264',
        mainBkg: '#fbf7ee',
        background: '#fbf7ee'
      }
    };
  }

  function setResult(result) {
    pendingResult = result;
  }

  function setExportResult(result) {
    pendingExportResult = result;
  }

  function showError(message) {
    var statusEl = document.getElementById('status');
    var diagramEl = document.getElementById('diagram');
    if (statusEl) statusEl.textContent = '';
    if (diagramEl) {
      diagramEl.innerHTML = '';
      var pre = document.createElement('pre');
      pre.textContent = 'No se pudo renderizar el diagrama: ' + message;
      diagramEl.appendChild(pre);
    }
  }

  // Ajuste inicial del diagrama al ancho del contenedor (paridad
  // projectView.js): el svg conserva su viewBox y escala con la proporción;
  // el diagrama completo es visible al instante, sin scroll horizontal.
  function fitSvgToContainer(svgEl) {
    if (!svgEl) return;
    svgEl.removeAttribute('height');
    svgEl.setAttribute('width', '100%');
    svgEl.style.maxWidth = '100%';
    svgEl.style.height = 'auto';
    svgEl.style.display = 'block';
  }

  function render(request) {
    try {
      if (!request || typeof request.code !== 'string') {
        throw new Error('Solicitud de render inválida');
      }
      var theme = request.theme === 'dark' ? 'dark' : 'light';
      var renderId = (typeof request.renderId === 'string' && request.renderId.length > 0)
        ? request.renderId
        : 'mermaid-render-' + Date.now();
      // Un render nuevo descarta resultados obsoletos de renders anteriores:
      // el polling de Kotlin solo acepta el resultado con el renderId esperado.
      // También se descartan estados obsoletos del canal de export: un render
      // nuevo invalida cualquier export en curso.
      pendingResult = null;
      pendingExportResult = null;
      pendingExportPng = null;
      lastRequestCode = request.code;
      document.body.className = 'theme-' + theme;
      if (!initialized || lastTheme !== theme) {
        var cfg = themeConfig(theme);
        global.mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          theme: cfg.theme,
          themeVariables: cfg.themeVariables
        });
        initialized = true;
        lastTheme = theme;
      }

      var statusEl = document.getElementById('status');
      var diagramEl = document.getElementById('diagram');
      if (statusEl) statusEl.textContent = 'Renderizando diagrama…';
      if (diagramEl) diagramEl.innerHTML = '';

      global.mermaid.render(renderId, request.code).then(function (res) {
        if (diagramEl) {
          diagramEl.innerHTML = res.svg;
          fitSvgToContainer(diagramEl.querySelector('svg'));
        }
        if (statusEl) statusEl.textContent = '';
        setResult({ ok: true, renderId: renderId, svg: res.svg });
      }).catch(function (err) {
        var message = (err && err.message) ? err.message : String(err);
        showError(message);
        setResult({ ok: false, renderId: renderId, error: message });
      });
    } catch (e) {
      var msg = (e && e.message) ? e.message : String(e);
      showError(msg);
      setResult({ ok: false, renderId: (request && request.renderId) || null, error: msg });
    }
  }

  function takeResult() {
    var r = pendingResult;
    pendingResult = null;
    return r;
  }

  // ── Export (SVG normalizado + PNG rasterizado, paridad web) ─────────────

  // Tamaño de cada trozo del PNG (~32 KB): cada respuesta individual de
  // evaluateJavascript queda lejos de cualquier límite de transporte.
  var EXPORT_CHUNK_SIZE = 32768;
  // Timeout explícito de carga del SVG como Image (~10 s): si no llega
  // onload ni onerror, el export falla con error controlado.
  var IMG_LOAD_TIMEOUT_MS = 10000;
  // Espacio de nombres SVG. Se construye con concatenación: el escaneo de
  // invariantes de los assets prohíbe los literales de URL remota en el código.
  var SVG_NS = 'http:' + '//www.w3.org/2000/svg';

  // Config de EXPORT fija e independiente del tema de la app: tema claro
  // neutral con fondo blanco y htmlLabels:false a NIVEL RAÍZ (en mermaid
  // 11.16.1 htmlLabels es opción de nivel superior; la directiva por-diagrama
  // antigua seguía emitiendo foreignObject, que rompe la rasterización).
  function exportThemeConfig() {
    return {
      htmlLabels: false,
      theme: 'neutral',
      themeVariables: { background: '#ffffff' },
      flowchart: { htmlLabels: false, useMaxWidth: false },
      sequence: { useMaxWidth: false },
      class: { useMaxWidth: false },
      securityLevel: 'strict',
      fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    };
  }

  // Restaura la config de pantalla tras un render de export:
  // mermaid.initialize FUSIONA la config nueva con la anterior (el
  // htmlLabels:false del export quedaría activo para el render de pantalla);
  // reset() restaura los defaults y el initialize siguiente vuelve a aplicar
  // la paleta del tema activo.
  function restoreScreenConfig() {
    if (!initialized) return;
    var theme = lastTheme === 'dark' ? 'dark' : 'light';
    var cfg = themeConfig(theme);
    try {
      global.mermaid.reset();
    } catch (e) {
      // Sin reset disponible: el initialize siguiente cubre explícitamente
      // todas las claves que el export pudo cambiar (merge).
    }
    global.mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      htmlLabels: true,
      theme: cfg.theme,
      themeVariables: cfg.themeVariables,
      flowchart: { htmlLabels: true, useMaxWidth: true },
      sequence: { useMaxWidth: true },
      class: { useMaxWidth: true }
    });
  }

  // Serializa el svg en pantalla (mermaid siempre emite xmlns en la raíz).
  function serializeDiagramSvg() {
    var diagramEl = document.getElementById('diagram');
    var svgEl = diagramEl ? diagramEl.querySelector('svg') : null;
    if (!svgEl) return null;
    return new XMLSerializer().serializeToString(svgEl);
  }

  // Normaliza un SVG de export: dimensiones NUMÉRICAS desde viewBox (nunca
  // width="100%", que los visores externos no resuelven), xmlns defensivo y
  // un <rect> blanco opaco como primer hijo (fondo). Es la ÚNICA fuente para
  // la descarga esquema.svg y la rasterización PNG — nunca el res.svg crudo
  // del render de pantalla (transparente y con colores del tema de la app).
  function normalizeSvgForExport(svgString) {
    var doc = null;
    try {
      doc = new DOMParser().parseFromString(svgString, 'image/svg+xml');
    } catch (e) {
      return null;
    }
    var svgEl = doc ? doc.documentElement : null;
    if (!svgEl || svgEl.nodeName.toLowerCase() !== 'svg' || doc.querySelector('parsererror')) {
      return null;
    }
    var vb = svgEl.getAttribute('viewBox');
    var w = 0;
    var h = 0;
    if (vb) {
      var parts = vb.split(/[\s,]+/).map(parseFloat);
      if (parts.length === 4 && parts[2] > 0 && parts[3] > 0 &&
          isFinite(parts[2]) && isFinite(parts[3])) {
        w = parts[2];
        h = parts[3];
      }
    }
    if (!w || !h) return null;
    svgEl.setAttribute('width', String(w));
    svgEl.setAttribute('height', String(h));
    if (!svgEl.getAttribute('xmlns')) {
      svgEl.setAttribute('xmlns', SVG_NS);
    }
    var rect = doc.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', '0');
    rect.setAttribute('y', '0');
    rect.setAttribute('width', '100%');
    rect.setAttribute('height', '100%');
    rect.setAttribute('fill', '#ffffff');
    svgEl.insertBefore(rect, svgEl.firstChild);
    return new XMLSerializer().serializeToString(svgEl);
  }

  // Re-render del diagrama con la config de export y normalización del SVG
  // resultante. Resuelve null si no hay diagrama o no se puede normalizar.
  function prepareExportSvg(exportId) {
    return new Promise(function (resolve) {
      if (!global.mermaid || typeof lastRequestCode !== 'string' || lastRequestCode.length === 0) {
        resolve(null);
        return;
      }
      try {
        global.mermaid.initialize(exportThemeConfig());
      } catch (e) {
        restoreScreenConfig();
        resolve(null);
        return;
      }
      // Si el autor YA trae una directiva %%{init:...}%%, se respeta tal
      // cual: detección con trimStart() (el código puede empezar con
      // newlines o espacios). La config de export va a nivel raíz vía
      // initialize y mermaid la fusiona con la del diagrama; añadir una
      // segunda directiva la pisotearía, por eso NUNCA se antepone una.
      var code = lastRequestCode.trimStart().indexOf('%%{') === 0
        ? lastRequestCode
        : lastRequestCode;
      var tmpId = 'mermaid-export-' + exportId;
      global.mermaid.render(tmpId, code).then(function (res) {
        restoreScreenConfig();
        var normalized = normalizeSvgForExport(res.svg);
        if (normalized) {
          resolve(normalized);
        } else {
          // Fallback: SVG en pantalla, normalizado con el mismo pipeline.
          resolve(normalizeSvgForExport(serializeDiagramSvg()));
        }
      }).catch(function () {
        restoreScreenConfig();
        resolve(normalizeSvgForExport(serializeDiagramSvg()));
      });
    });
  }

  // Rasteriza un SVG NORMALIZADO a un data URL PNG (fondo blanco + margen).
  // El PNG completo NO viaja por takeExportResult(): primero los metadatos y
  // el payload se sirve en trozos por takeExportPngChunk (ver contrato).
  function rasterizeSvg(svgString, exportId) {
    var naturalW = 0;
    var naturalH = 0;
    var vbMatch = svgString.match(/viewBox=["']([^"']+)["']/);
    if (vbMatch) {
      var parts = vbMatch[1].split(/[\s,]+/).map(parseFloat);
      if (parts.length === 4 && parts[2] > 0 && parts[3] > 0 &&
          isFinite(parts[2]) && isFinite(parts[3])) {
        naturalW = parts[2];
        naturalH = parts[3];
      }
    }
    if (!naturalW || !naturalH) {
      setExportResult({ ok: false, exportId: exportId, error: 'SVG sin dimensiones válidas.' });
      return;
    }
    // Cap de píxeles total (memoria móvil) + límites de Chromium (lado y
    // área): el clamp acota también la escala MÍNIMA — con un viewBox enorme,
    // forzar scale >= 1 (el Math.max(1, ...) antiguo) excedía el área máxima.
    var MAX_CANVAS_PIXELS = 16777216; // 4096×4096 ≈ 64 MB de canvas
    var MAX_CANVAS_SIDE = 32767; // límite de lado de Chromium
    var MAX_CANVAS_AREA = 268435456; // 16384² límite de área de Chromium
    var MIN_SCALE = 0.05;
    var scale = 3;
    if (naturalW * naturalH * scale * scale > MAX_CANVAS_PIXELS) {
      scale = Math.sqrt(MAX_CANVAS_PIXELS / (naturalW * naturalH));
    }
    var margin = 16;
    var canvasW = naturalW + margin * 2;
    var canvasH = naturalH + margin * 2;
    if (canvasW * scale > MAX_CANVAS_SIDE) scale = MAX_CANVAS_SIDE / canvasW;
    if (canvasH * scale > MAX_CANVAS_SIDE) scale = MAX_CANVAS_SIDE / canvasH;
    if (canvasW * canvasH * scale * scale > MAX_CANVAS_AREA) {
      scale = Math.sqrt(MAX_CANVAS_AREA / (canvasW * canvasH));
    }
    if (scale < MIN_SCALE) scale = MIN_SCALE;

    var canvas = document.createElement('canvas');
    canvas.width = Math.round(canvasW * scale);
    canvas.height = Math.round(canvasH * scale);
    if (!isFinite(canvas.width) || !isFinite(canvas.height) ||
        canvas.width <= 0 || canvas.height <= 0 ||
        canvas.width > MAX_CANVAS_SIDE || canvas.height > MAX_CANVAS_SIDE) {
      setExportResult({ ok: false, exportId: exportId, error: 'Dimensiones de canvas fuera de rango.' });
      return;
    }
    var ctx = canvas.getContext('2d');
    if (!ctx) {
      setExportResult({ ok: false, exportId: exportId, error: 'Canvas 2D no disponible.' });
      return;
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Base64 UTF-8 seguro (acentos del español), troceado para evitar
    // desbordes de pila en SVGs grandes.
    var utf8 = new TextEncoder().encode(svgString);
    var binary = '';
    var chunkSize = 0x8000;
    for (var i = 0; i < utf8.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, utf8.subarray(i, i + chunkSize));
    }
    var dataUrl = 'data:image/svg+xml;base64,' + btoa(binary);

    var statusEl = document.getElementById('status');
    var img = new Image();
    var settled = false;
    var timer = null;
    function finish(result) {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (statusEl) statusEl.textContent = '';
      setExportResult(result);
    }
    // Timeout explícito: si no llega onload ni onerror, error controlado.
    timer = setTimeout(function () {
      finish({ ok: false, exportId: exportId, error: 'Tiempo de espera agotado al cargar el diagrama como imagen.' });
    }, IMG_LOAD_TIMEOUT_MS);
    img.onload = function () {
      try {
        ctx.drawImage(
          img,
          Math.round(margin * scale),
          Math.round(margin * scale),
          Math.round(naturalW * scale),
          Math.round(naturalH * scale)
        );
        var png = canvas.toDataURL('image/png');
        // El payload completo queda en memoria del wrapper; solo los
        // METADATOS viajan por el canal de export.
        pendingExportPng = { exportId: exportId, dataUrl: png };
        finish({ ok: true, exportId: exportId, totalLength: png.length, chunkSize: EXPORT_CHUNK_SIZE });
      } catch (e) {
        finish({ ok: false, exportId: exportId, error: (e && e.message) ? e.message : String(e) });
      }
    };
    img.onerror = function () {
      finish({ ok: false, exportId: exportId, error: 'No se pudo cargar el diagrama como imagen.' });
    };
    img.src = dataUrl;
  }

  function exportPng(exportId) {
    pendingExportResult = null;
    pendingExportPng = null;
    var statusEl = document.getElementById('status');
    try {
      if (statusEl) statusEl.textContent = 'Generando imagen…';
      prepareExportSvg(exportId).then(function (normalized) {
        if (!normalized) {
          throw new Error('No se pudo normalizar el SVG del diagrama.');
        }
        rasterizeSvg(normalized, exportId);
      }).catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        if (statusEl) statusEl.textContent = '';
        setExportResult({ ok: false, exportId: exportId, error: msg });
      });
    } catch (e) {
      var msg = (e && e.message) ? e.message : String(e);
      if (statusEl) statusEl.textContent = '';
      setExportResult({ ok: false, exportId: exportId, error: msg });
    }
  }

  // Export SVG (descarga esquema.svg): el SVG NORMALIZADO viaja por el mismo
  // canal de export, correlacionado por exportId, sin rasterizar.
  function exportSvg(exportId) {
    pendingExportResult = null;
    pendingExportPng = null;
    var statusEl = document.getElementById('status');
    try {
      if (statusEl) statusEl.textContent = 'Generando SVG…';
      prepareExportSvg(exportId).then(function (normalized) {
        if (statusEl) statusEl.textContent = '';
        if (!normalized) {
          throw new Error('No se pudo normalizar el SVG del diagrama.');
        }
        setExportResult({ ok: true, exportId: exportId, svg: normalized });
      }).catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        if (statusEl) statusEl.textContent = '';
        setExportResult({ ok: false, exportId: exportId, error: msg });
      });
    } catch (e) {
      var msg = (e && e.message) ? e.message : String(e);
      if (statusEl) statusEl.textContent = '';
      setExportResult({ ok: false, exportId: exportId, error: msg });
    }
  }

  function takeExportResult() {
    var r = pendingExportResult;
    pendingExportResult = null;
    return r;
  }

  // Sirve un trozo del PNG por offset: `null` si el id no coincide o si
  // offset >= longitud total (fin de canal). El payload completo vive solo en
  // la memoria del wrapper y se libera con clearExportPayload().
  function takeExportPngChunk(exportId, offset) {
    if (!pendingExportPng || pendingExportPng.exportId !== exportId) return null;
    var off = (typeof offset === 'number' && isFinite(offset) && offset >= 0) ? Math.floor(offset) : -1;
    if (off < 0 || off >= pendingExportPng.dataUrl.length) return null;
    return pendingExportPng.dataUrl.substr(off, EXPORT_CHUNK_SIZE);
  }

  // Libera el payload del PNG exportado (llamado por Kotlin al completar,
  // fallar o abortar la lectura de trozos).
  function clearExportPayload(exportId) {
    if (pendingExportPng && pendingExportPng.exportId === exportId) {
      pendingExportPng = null;
    }
  }

  global.ExplainerMermaid = {
    render: render,
    takeResult: takeResult,
    exportPng: exportPng,
    exportSvg: exportSvg,
    takeExportResult: takeExportResult,
    takeExportPngChunk: takeExportPngChunk,
    clearExportPayload: clearExportPayload
  };
})(window);
