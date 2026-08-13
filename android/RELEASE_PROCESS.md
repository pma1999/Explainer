# Proceso de release — App Android Explainer

Guía operativa para generar una **nueva versión del APK de distribución**.
**LÉELO COMPLETO antes de reconstruir un APK** — el orquestador debe leerlo siempre
que una sesión futura necesite generar una versión nueva. Ubicación operativa:
`android/RELEASE_PROCESS.md`.

Estado de referencia: versionCode 1 / versionName 0.1.0 (APK v2 entregado, 2026-08-09,
SHA-256 `34bf3c73d82142c39605a8b4864833340321deb737a7e88b5aca4583d675dd3c`).

---

## 1. Entorno de build (WSL)

El build se hace en WSL con un toolchain propio (NO usar el SDK de Windows — binarios .exe).

```bash
export JAVA_HOME="$HOME/jdk-17"          # Temurin 17 (openjdk 17.0.20)
export ANDROID_HOME="$HOME/android-sdk"  # cmdline-tools + platforms;android-36 + build-tools;36.0.0
export PATH="$JAVA_HOME/bin:$PATH"
```

⚠️ **GOTCHA CRÍTICO (verificado en sesión):** NO exportar varias variables en una sola
sentencia (`export A=1 B=2 PATH="$A/bin:$PATH"` expande las RHS antes de aplicar las
asignaciones y deja `PATH` sin el JDK → apksigner falla con `exec: java: not found`).
**Usar SIEMPRE una sentencia `export` por variable.**

Verificación rápida:
```bash
command -v java   # debe imprimir /home/pablomiar/jdk-17/bin/java
```

## 2. Firma (keystore del usuario)

- Keystore: `~/explainer-release.keystore` (alias `explainer`, RSA 2048, PKCS12) — FUERA del repo.
- Credenciales: `android/keystore.properties` (ignorada por git, chmod 600).
  Claves: `keystoreFile`, `keystorePassword`, `keyAlias`, `keyPassword`.
- El signing de `app/build.gradle.kts` lee esas properties (o las env vars
  `EXPLAINER_KEYSTORE_FILE/PASSWORD/ALIAS/KEY_PASSWORD`).
- El gate de release FALLA deliberadamente si no hay keystore externo: nunca se firma con debug.
- **NUNCA** commitees la keystore ni `keystore.properties`/`explainer.properties`
  (ambos en `.gitignore`).

## 3. Subir versión (obligatorio antes de cada release)

En `android/app/build.gradle.kts`:

```kotlin
defaultConfig {
    versionCode = 2        // +1 por cada release
    versionName = "0.2.0"  // bump semántico
}
```

Misma firma + versionCode mayor → la instalación sobre la versión anterior conserva los datos.

## 4. Construir

```bash
cd /mnt/c/Users/PcVIP/documents/stuff/explainer/android
./gradlew :app:assembleRelease
# APK resultante: app/build/outputs/apk/release/app-release.apk
```

Si hubo cambios de código, antes conviene el gate completo:
```bash
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

## 5. Verificar (obligatorio, no opcional)

```bash
bash scripts/verify_release.sh app/build/outputs/apk/release/app-release.apk
# Debe terminar en: RESULTADO: TODAS LAS COMPROBACIONES PASS (25 checks)
```

El script necesita `ANDROID_HOME` y `java` en PATH (ver §1). Comprobaciones: firma apksigner
v2, permisos (solo INTERNET + transitivos justificados), cleartext/backup off, sin secretos
(service_role/JWT/BYOK/credenciales de prueba) ni PDF/CDN, Mermaid 11.16.1 y fuentes
empaquetadas, icono launcher (adaptive + monochrome + glyph), config pública.

Además, registrar la huella:
```bash
sha256sum app/build/outputs/apk/release/app-release.apk
```

## 6. Entregar

1. Copiar el APK al dispositivo del usuario (USB/Drive/lo que use).
2. Comunicar: ruta, tamaño, SHA-256 y QUÉ cambió respecto a la versión anterior.
3. Instalación sobre versión previa: misma firma → conserva datos y descargas.
4. Si el usuario cambia de móvil o la firma cambia: desinstalar primero (se pierden
   descargas/progreso local; los datos del backend no se ven afectados).

## 7. Gate manual de dispositivo (RC-04 — sigue PENDIENTE)

El checklist completo está en `android/RELEASE_CHECKLIST.md`. Smoke mínimo tras instalar:
login real → descargar un proyecto → modo avión + reiniciar app → leer las 5 pestañas
(incluido Mermaid) → progreso local → salir de modo avión → sync → tema claro/oscuro/sistema.

Los tests JVM (726) NO sustituyen este gate: el comportamiento físico en dispositivo
(WebView real, refresh real, modo avión en frío) sigue sin certificar.

## 8. Estado Git (contexto para futuras sesiones)

- `android/` y `plans/android-app/` están **sin trackear** en git (árbol nuevo, nunca commiteado).
- Cambios preexistentes ajenos: `frontend/js/api.js` (modificado), `.opencode/` (untracked).
- `android/explainer.properties` contiene la config pública real (Supabase URL + anon key +
  API base `https://criminal-leoline-pma00-1cbf79ad.koyeb.app`) — ignorada por git.

## 9. No-nos

- No cambiar versiones del baseline (Gradle 9.5.0, AGP 9.3.1, Kotlin 2.4.10, KSP 2.3.11,
  Room3 3.0.1, Compose BOM 2026.06.01, Lifecycle estricto 2.10.0, Markdown estricto 0.41.0,
  Supabase 3.7.0, Ktor 3.5.1) sin decisión del plan owner.
- No tocar `frontend/`, `backend/`, `main.py`, `supabase/` (fuera de alcance).
- No ejecutar builds Gradle en paralelo sobre el mismo `android/` (colisionan en `app/build`):
  una sola lane activa a la vez.
- No usar `explainer.properties` con valores de otro entorno.
