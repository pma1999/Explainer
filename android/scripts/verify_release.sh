#!/usr/bin/env bash
# Verificador determinista del APK release de Explainer (T12).
# Sin secretos: no lee keystores ni credenciales, solo inspecciona el APK.
#
# Uso:
#   ANDROID_HOME=~/android-sdk scripts/verify_release.sh <app-release.apk>
#
# Dependencias: ANDROID_HOME con build-tools/36.0.0 (aapt2, apksigner),
# java en PATH (apksigner), unzip, sha256sum, strings, grep.
# Exit code 0 = todas las comprobaciones PASS; 1 = alguna FAIL.
set -u

APK="${1:?uso: verify_release.sh <ruta-al-apk-release>}"
[ -f "$APK" ] || { echo "FAIL: no existe el APK: $APK"; exit 1; }

SDK="${ANDROID_HOME:?ANDROID_HOME no definido}"
BT="$SDK/build-tools/36.0.0"
AAPT2="$BT/aapt2"
APKSIGNER="$BT/apksigner"
for tool in "$AAPT2" "$APKSIGNER"; do
    [ -x "$tool" ] || { echo "FAIL: falta herramienta: $tool"; exit 1; }
done

fail=0
step() { printf '%-62s' "$1"; }
pass() { echo "PASS"; }
fail_() { echo "FAIL"; fail=1; }

# --- 1. Firma (apksigner verify) ---
step "apksigner verify --verbose"
if "$APKSIGNER" verify --verbose "$APK" >/tmp/verify_release_signer.out 2>&1; then
    pass
else
    fail_
    cat /tmp/verify_release_signer.out
fi

# --- 2. Tamaño y SHA-256 (se imprimen; el reporte los registra) ---
SIZE=$(stat -c %s "$APK")
SHA=$(sha256sum "$APK" | awk '{print $1}')
echo "INFO: size=$SIZE bytes"
echo "INFO: sha256=$SHA"

# --- 3. Permisos y SDK (merged manifest via badging) ---
BADGING=$(mktemp)
"$AAPT2" dump badging "$APK" > "$BADGING" 2>&1
step "package/applicationId y SDKs"
if grep -q "package: name='com.explainer.app'" "$BADGING" &&
    grep -q "compileSdkVersion='36'" "$BADGING" &&
    grep -q "targetSdkVersion:'36'" "$BADGING" &&
    grep -q "minSdkVersion:'26'" "$BADGING"; then
    pass
else
    fail_
    grep -E "package:|sdkVersion" "$BADGING"
fi

step "permisos: INTERNET presente (app-owned)"
grep -q "uses-permission: name='android.permission.INTERNET'" "$BADGING" && pass || fail_

step "permisos peligrosos ausentes (storage/media/notif/loc/cam/mic/contacts)"
if grep -qE "uses-permission: name='android.permission.(READ|WRITE)_EXTERNAL_STORAGE|READ_MEDIA|POST_NOTIFICATIONS|ACCESS_FINE_LOCATION|ACCESS_COARSE_LOCATION|CAMERA|RECORD_AUDIO|READ_CONTACTS" "$BADGING"; then
    fail_
else
    pass
fi

echo "--- permisos del merged release manifest (para el reporte) ---"
grep "uses-permission: name=" "$BADGING" | sed "s/^/    /"

# --- 4. Flags de la aplicacion (xmltree) ---
XMLTREE=$(mktemp)
"$AAPT2" dump xmltree --file AndroidManifest.xml "$APK" > "$XMLTREE" 2>&1
step "usesCleartextTraffic=false"
grep -q "usesCleartextTraffic(0x010104ec)=false" "$XMLTREE" && pass || fail_
step "allowBackup=false"
grep -q "allowBackup(0x01010280)=false" "$XMLTREE" && pass || fail_
step "dataExtractionRules presente"
grep -q "dataExtractionRules(0x0101063e)=" "$XMLTREE" && pass || fail_
step "fullBackupContent presente"
grep -q "fullBackupContent(0x010104eb)=" "$XMLTREE" && pass || fail_
step "MainActivity exported=true (launcher)"
grep -q 'exported(0x01010010)=true' "$XMLTREE" && pass || fail_

# --- 5. Contenido del zip: prohibidos ausentes, assets presentes ---
LISTING=$(mktemp)
unzip -l "$APK" > "$LISTING" 2>&1

step "sin PDF ni node_modules en el APK"
if grep -qicE "\.pdf$|node_modules" "$LISTING"; then
    fail_
else
    pass
fi

step "assets Mermaid presentes (mermaid.min.js, index.html, LICENSE)"
if grep -q "assets/mermaid/mermaid.min.js" "$LISTING" &&
    grep -q "assets/mermaid/index.html" "$LISTING" &&
    grep -q "assets/mermaid/explainer-mermaid.js" "$LISTING" &&
    grep -q "assets/mermaid/LICENSE" "$LISTING"; then
    pass
else
    fail_
fi

step "Mermaid 11.16.1 en el bundle"
MMD=$(mktemp)
unzip -p "$APK" assets/mermaid/mermaid.min.js > "$MMD" 2>/dev/null
grep -q "11.16.1" "$MMD" && pass || fail_

step "seis fuentes locales empaquetadas (res/*.ttf)"
FONT_COUNT=$(grep -cE "res/[A-Za-z0-9]+\.ttf" "$LISTING")
[ "$FONT_COUNT" -ge 6 ] && pass || fail_
echo "INFO: fonts=$FONT_COUNT (DM Sans x3 + Source Serif 4 x3 tras shrinking)"

# --- 5b. Icono launcher (RC-03): adaptive + monochrome dentro del APK ---
# El resource shrinking de AGP 9 renombra los ficheros fisicos res/ en
# release (p.ej. res/0K.xml), asi que la comprobacion usa la resource table
# (nombres canonicos que cargan el launcher) + el contenido fisico del APK.
RESTABLE=$(mktemp)
"$AAPT2" dump resources "$APK" > "$RESTABLE" 2>&1

step "icono: manifest declara icon y roundIcon (xmltree)"
grep -q "icon(0x01010002)=" "$XMLTREE" &&
    grep -q "roundIcon(0x0101052c)=" "$XMLTREE" && pass || fail_

step "icono: mipmap/ic_launcher + ic_launcher_round en la resource table"
if grep -q "mipmap/ic_launcher\b" "$RESTABLE" &&
    grep -q "mipmap/ic_launcher_round\b" "$RESTABLE"; then
    pass
else
    fail_
fi

step "icono: foreground + monochrome + background en la resource table"
if grep -q "drawable/ic_launcher_foreground" "$RESTABLE" &&
    grep -q "drawable/ic_launcher_monochrome" "$RESTABLE" &&
    grep -q "color/ic_launcher_background" "$RESTABLE"; then
    pass
else
    fail_
fi

step "icono: adaptive-icon con background+foreground+monochrome (contenido)"
ICXML=$(mktemp)
ICOK=1
for f in $(grep -oE "res/[A-Za-z0-9]+\.xml" "$LISTING" | sort -u); do
    "$AAPT2" dump xmltree --file "$f" "$APK" > "$ICXML" 2>/dev/null || continue
    if grep -q "E: adaptive-icon" "$ICXML"; then
        if grep -q "E: background" "$ICXML" &&
            grep -q "E: foreground" "$ICXML" &&
            grep -q "E: monochrome" "$ICXML"; then
            ICOK=0
            break
        fi
    fi
done
if [ "$ICOK" -eq 0 ]; then pass; else fail_; fi

step "icono: glyph del libro (pathData) en los drawables del APK"
STRINGS=$(mktemp)
for f in $(grep -oE "res/[A-Za-z0-9]+\.xml" "$LISTING" | sort -u); do
    unzip -p "$APK" "$f" 2>/dev/null | strings >> "$STRINGS"
done
# Página izquierda y derecha del foreground + el path unico del monochrome
if grep -q "M54,38 C44,34" "$STRINGS" &&
    grep -q "M54,38 C64,34" "$STRINGS" &&
    grep -q "Z M54,38" "$STRINGS"; then
    pass
else
    fail_
fi

# --- 6. Strings del dex: secretos prohibidos ausentes, config publica presente ---
DEXDIR=$(mktemp -d)
unzip -p "$APK" "classes*.dex" > "$DEXDIR/all.dex" 2>/dev/null
# unzip -p con comodines extrae la concatenacion en orden de entrada del zip
strings "$DEXDIR/all.dex" > "$DEXDIR/all.str"

step "sin service_role/JWT secret/BYOK/test creds/CDN en dex"
if grep -qiE "service_role|service-role|SUPABASE_JWT_SECRET|APP_ENCRYPTION_KEY|byok|jsdelivr|cdnjs|password123|test1234|changeme|testpassword" "$DEXDIR/all.str"; then
    fail_
else
    pass
fi

step "config publica presente (API_BASE_URL + Supabase)"
grep -q "koyeb.app" "$DEXDIR/all.str" && grep -q "supabase.co" "$DEXDIR/all.str" && pass || fail_

step "marcadores de serializacion supervivientes (R8)"
grep -q "partes_contenido" "$DEXDIR/all.str" && grep -q "mermaid_code" "$DEXDIR/all.str" && pass || fail_

# --- Limpieza y resumen ---
rm -f /tmp/verify_release_signer.out "$BADGING" "$XMLTREE" "$LISTING" "$MMD" "$ICXML" "$RESTABLE" "$STRINGS"
rm -rf "$DEXDIR"

if [ "$fail" -eq 0 ]; then
    echo "RESULTADO: TODAS LAS COMPROBACIONES PASS"
    exit 0
else
    echo "RESULTADO: HAY COMPROBACIONES FAIL"
    exit 1
fi
