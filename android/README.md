# Explainer — App Android (offline)

Aplicación nativa Android (Kotlin + Jetpack Compose, Material 3) del lector
offline de Explainer: autenticación contra Supabase GoTrue, listado/fijado de
proyectos desde la API FastAPI, descargas offline atómicas con WorkManager y
lector de las cinco secciones (`explicacion`, `recorrido`, `recursos`,
`esquema`, `repaso`) con progreso sincronizable.

Documentación de referencia: `plans/android-app/global-constraints.md`
(invariantes de baseline, seguridad y release).

## Requisitos del entorno

- JDK 17 (`export JAVA_HOME=~/jdk-17; export PATH="$JAVA_HOME/bin:$PATH"`).
- Android SDK con `platforms;android-36` y `build-tools;36.0.0`
  (`export ANDROID_HOME=~/android-sdk`).
- Gradle: se usa el wrapper del repo (`./gradlew`), Gradle 9.5.0, AGP 9.3.1,
  Kotlin 2.4.10 (built-in de AGP 9), KSP 2.3.11.

## Configuración pública de runtime (no secreta, tampoco versionada)

La app recibe solo tres valores públicos:

| Variable de entorno | Clave en `explainer.properties` | Contenido |
|---|---|---|
| `EXPLAINER_SUPABASE_URL` | `explainerSupabaseUrl` | URL HTTPS del proyecto Supabase |
| `EXPLAINER_SUPABASE_ANON_KEY` | `explainerSupabaseAnonKey` | anon/publishable key (pública) |
| `EXPLAINER_API_BASE_URL` | `explainerApiBaseUrl` | origen HTTPS de FastAPI, sin `/api` |

Precedencia: env vars > `android/explainer.properties` (ignorado por git) >
fallback `""`. Nunca se empaquetan `service_role`, JWT secret, claves BYOK ni
credenciales de prueba; el backend exige el JWT de sesión del usuario (aud
`authenticated`, ES256), la anon key no autoriza proyectos.

## Build debug

```bash
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Build release y firma

El release usa R8 (`isMinifyEnabled=true`), resource shrinking
(`isShrinkResources=true`), reglas mínimas en `app/proguard-rules.pro`,
cleartext desactivado y Auto Backup deshabilitado (manifest + reglas XML en
`app/src/main/res/xml/`).

La firma lee exclusivamente inputs externos, nunca versionados. Precedencia:

1. Env vars: `EXPLAINER_KEYSTORE_FILE`, `EXPLAINER_KEYSTORE_PASSWORD`,
   `EXPLAINER_KEY_ALIAS`, `EXPLAINER_KEY_PASSWORD`.
2. `android/keystore.properties` (ignorado por git):
   `keystoreFile=...`, `keystorePassword=...`, `keyAlias=...`,
   `keyPassword=...`.
3. `android/explainer.properties` con las mismas claves.

Sin los cuatro inputs, `assembleRelease`/`bundleRelease`/`packageRelease`
fallan con un mensaje accionable antes de empaquetar; el release **nunca** cae
silenciosamente a debug signing. `lintRelease` y `testReleaseUnitTest` no
empaquetan y no exigen keystore.

```bash
# Ejemplo (keystore EFÍMERA solo para verificación; NUNCA en el repo):
EXPLAINER_KEYSTORE_FILE=/ruta/externa/explainer.jks \
EXPLAINER_KEYSTORE_PASSWORD=... \
EXPLAINER_KEY_ALIAS=... \
EXPLAINER_KEY_PASSWORD=... \
./gradlew :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
# APK: app/build/outputs/apk/release/app-release.apk
```

### 🗝️ Custodia de la keystore (crítico)

El APK de distribución debe estar firmado siempre con **la misma keystore**:
los upgrades por sideload exigen que la firma coincida. Perder o cambiar la
keystore impide instalar versiones nuevas sobre las anteriores y obliga a
desinstalar (con pérdida de datos locales). La keystore es un secreto: se
guarda fuera del repositorio, con copia de seguridad segura, y nunca se
commitea (`.gitignore` cubre `*.jks`, `*.keystore`, `*.p12`, `*.pk8`,
`keystore.properties`, `signing.properties`).

## Verificación estática del APK release

`android/scripts/verify_release.sh` es un verificador determinista sin
secretos: apksigner verify, SHA-256/tamaño, permisos del merged manifest,
flags de seguridad, ausencia de PDF/node_modules, presencia de Mermaid
11.16.1/fuentes/licencias y escaneo de strings del dex (patrones prohibidos
ausentes, config pública presente).

```bash
ANDROID_HOME=~/android-sdk scripts/verify_release.sh \
  app/build/outputs/apk/release/app-release.apk
```

## Upgrade por sideload

1. Firma el nuevo APK con la misma keystore (ver arriba).
2. `adb install -r app-release.apk` (o copia del APK e instalación manual).
3. La instalación conserva el almacenamiento privado (snapshots, cola,
   sesión) porque Auto Backup está deshabilitado y no se usa almacenamiento
   compartido; el smoke manual correspondiente está en `RELEASE_CHECKLIST.md`.

## Notas de seguridad

- Único permiso declarado por la app: `INTERNET`. Los permisos no peligrosos
  del merged release los aportan AndroidX/WorkManager (`ACCESS_NETWORK_STATE`,
  `WAKE_LOCK`, `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE` y el permiso
  propio `DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` de AndroidX core); no hay
  storage/media, notification, location, camera, mic ni contacts, y la app no
  usa foreground workers.
- `usesCleartextTraffic=false`: toda URL de runtime es HTTPS.
- Auto Backup deshabilitado; app-private storage no es cifrado de base de
  datos (ver riesgos en `plans/android-app/plan.md`).
- Mermaid se sirve desde assets locales (sin CDN) en una WebView endurecida.
