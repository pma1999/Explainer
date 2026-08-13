# Third-party notices — Explainer Android

Lista de dependencias y assets de terceros incluidos en la app Android,
con su licencia. Verificación: 2026-08-08.

## multiplatform-markdown-renderer (com.mikepenz)

- Artefacto: `com.mikepenz:multiplatform-markdown-renderer-m3:0.41.0`
  (+ `multiplatform-markdown-renderer` / `-android` `0.41.0`).
- Licencia: Apache License 2.0 (véase el repositorio del proyecto).
- Uso: renderizado nativo de Markdown en Compose (T08). Versión fijada por
  baseline: sus AAR declaran `minCompileSdk=36`; `0.42.0`/`0.43.0` exigen 37.

## mermaid (bundle local)

- Paquete npm: `mermaid@11.16.1` (tarball oficial del registro npm).
- Licencia: MIT — texto completo en
  `android/app/src/main/assets/mermaid/LICENSE`.
- Integridad del tarball (declarada por npm, verificada localmente):
  `sha512-TQsq6u22fAn3rek5VOubrhKPo1g5hwC3FXUN9hiyupTckcYiGuuKGkNQrKYwGJkXUxZdojwRG46gsSCFZMDp4g==`
- Bundle `dist/mermaid.min.js` empaquetado en
  `android/app/src/main/assets/mermaid/mermaid.min.js` con su sha512 y
  versión registrados en `android/app/src/main/assets/mermaid/README.md`.
- Uso: única WebView de la app, endurecida (WebViewAssetLoader + CSP +
  `securityLevel:'strict'`), sin CDN (T08).

## Tipografías locales

- **Source Serif 4** — SIL Open Font License 1.1. Texto completo en
  `android/OFL-SOURCE-SERIF-4.txt`.
- **DM Sans** — SIL Open Font License 1.1. Texto completo en
  `android/OFL-DM-SANS.txt`.
- Uso: únicas dos familias del APK, empaquetadas en `res/font`, sin
  descarga en runtime (global-constraints UX).

## AndroidX / Jetpack / Kotlin (gestión de dependencias)

Las dependencias de AndroidX, Kotlin y Ktor se declaran en
`android/gradle/libs.versions.toml`; sus licencias corresponden a las de
sus proyectos (Apache 2.0 / licencias de Android Open Source Project).
