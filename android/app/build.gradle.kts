import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    // Kotlin built-in de AGP 9: org.jetbrains.kotlin.android NO se aplica.
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
}

// Config pública de runtime (no secreta pero tampoco se versiona):
// 1) env vars EXPLAINER_SUPABASE_URL / EXPLAINER_SUPABASE_ANON_KEY / EXPLAINER_API_BASE_URL
// 2) android/explainer.properties (ignorado por git)
// 3) fallback "" — el build nunca exige credenciales reales.
val explainerLocalProps = Properties().apply {
    val f = rootProject.file("explainer.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

// Firma release (T12): SOLO inputs externos, nunca versionados. Precedencia:
// 1) env vars EXPLAINER_KEYSTORE_FILE / EXPLAINER_KEYSTORE_PASSWORD /
//    EXPLAINER_KEY_ALIAS / EXPLAINER_KEY_PASSWORD (nombres exactos del brief T12)
// 2) android/keystore.properties (ignorado por git; claves keystoreFile/
//    keystorePassword/keyAlias/keyPassword)
// 3) android/explainer.properties (ignorado por git; mismas claves)
// Sin inputs, las tareas de empaquetado release fallan con mensaje accionable
// (gate abajo); el release NUNCA cae silenciosamente a debug signing.
val signingLocalProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

fun signingInput(envName: String, propName: String): String {
    System.getenv(envName)?.takeIf { it.isNotBlank() }?.let { return it.trim() }
    (signingLocalProps.getProperty(propName)
        ?: explainerLocalProps.getProperty(propName))
        ?.takeIf { it.isNotBlank() }?.let { return it.trim() }
    return ""
}

fun publicConfig(envName: String, propName: String): String {
    val raw = System.getenv(envName) ?: explainerLocalProps.getProperty(propName) ?: ""
    // Escapado por si un valor contuviera comillas o backslashes.
    return raw.replace("\\", "\\\\").replace("\"", "\\\"")
}

android {
    namespace = "com.explainer.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.explainer.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "0.2.0"

        // Config pública de runtime (ver publicConfig() arriba): env vars o
        // android/explainer.properties (ignorado), con fallback "".
        buildConfigField("String", "EXPLAINER_SUPABASE_URL", "\"${publicConfig("EXPLAINER_SUPABASE_URL", "explainerSupabaseUrl")}\"")
        buildConfigField("String", "EXPLAINER_SUPABASE_ANON_KEY", "\"${publicConfig("EXPLAINER_SUPABASE_ANON_KEY", "explainerSupabaseAnonKey")}\"")
        buildConfigField("String", "EXPLAINER_API_BASE_URL", "\"${publicConfig("EXPLAINER_API_BASE_URL", "explainerApiBaseUrl")}\"")
    }

    signingConfigs {
        create("release") {
            // Keystore/alias/passwords EXTERNOS (env o properties ignoradas por
            // git). Si falta cualquiera, storeFile queda null y el gate de
            // empaquetado release falla con mensaje accionable.
            val filePath = signingInput("EXPLAINER_KEYSTORE_FILE", "keystoreFile")
            val storePwd = signingInput("EXPLAINER_KEYSTORE_PASSWORD", "keystorePassword")
            val alias = signingInput("EXPLAINER_KEY_ALIAS", "keyAlias")
            val keyPwd = signingInput("EXPLAINER_KEY_PASSWORD", "keyPassword")
            if (filePath.isNotEmpty() && storePwd.isNotEmpty() && alias.isNotEmpty() && keyPwd.isNotEmpty()) {
                storeFile = file(filePath)
                storePassword = storePwd
                keyAlias = alias
                keyPassword = keyPwd
            }
        }
    }

    buildTypes {
        release {
            // T12: R8 (minify) + resource shrinking. Sin keystore externo, el
            // APK release NO se firma (gate abajo); nunca debug signing.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
                .takeIf { it.storeFile != null }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

// Gate T12: el empaquetado release exige firma con keystore externo. Sin los
// cuatro inputs, assembleRelease/bundleRelease/packageRelease fallan ANTES de
// producir APK con un mensaje accionable. lintRelease y testReleaseUnitTest
// NO empaquetan y siguen funcionando sin keystore.
gradle.taskGraph.whenReady {
    val packagingRelease = allTasks.any { task ->
        task.project == project &&
            (task.name == "assembleRelease" || task.name == "bundleRelease" ||
                task.name == "packageRelease")
    }
    if (packagingRelease &&
        android.signingConfigs.getByName("release").storeFile == null
    ) {
        throw GradleException(
            "Firma release no configurada. Proporciona EXPLAINER_KEYSTORE_FILE, " +
                "EXPLAINER_KEYSTORE_PASSWORD, EXPLAINER_KEY_ALIAS y " +
                "EXPLAINER_KEY_PASSWORD (env) o android/keystore.properties " +
                "(keystoreFile/keystorePassword/keyAlias/keyPassword; ignorado por git). " +
                "El APK release nunca se firma con el keystore de debug."
        )
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

// Room3 exporta el schema v1 a android/app/schemas/ (brief T03: schema
// versionado; exportSchema=true exige room.schemaLocation). Solo este arg;
// no se tocan versiones del baseline.
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    implementation(libs.androidx.core.ktx)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime.ktx)

    // Lifecycle 2.10.0 (override estricto, decisión de baseline): los tres
    // artefactos se declaran directamente para alinear el grupo atómico
    // androidx.lifecycle (material3 los arrastra transitivamente). Ver
    // libs.versions.toml [versions] lifecycle.
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)

    implementation(libs.androidx.room3.runtime)
    ksp(libs.androidx.room3.compiler)

    implementation(platform(libs.supabase.bom))
    implementation(libs.supabase.auth.kt)

    implementation(libs.ktor.client.android)
    implementation(libs.ktor.client.content.negotiation)
    implementation(libs.ktor.serialization.kotlinx.json)
    implementation(libs.kotlinx.serialization.json)

    // Markdown Renderer M3 0.41.0 (strictly, compileSdk 36) — renderizado
    // nativo de explicaciones; sin image transformer (sin descargas implícitas).
    implementation(libs.markdown.renderer.m3)
    // WebKit para WebViewAssetLoader: la única WebView de la app es Mermaid
    // (assets locales bajo https://appassets.androidplatform.net).
    implementation(libs.androidx.webkit)

    debugImplementation(libs.androidx.compose.ui.tooling)

    testImplementation(libs.junit)
    // work-testing (misma versión del baseline) para tests JVM de la custom
    // WorkerFactory (T11): construye WorkerParameters sin Robolectric.
    testImplementation(libs.androidx.work.testing)
    // MockEngine (receta integration-supabase-kt.md, sección Testing setup):
    // misma versión Ktor 3.5.1 del catálogo; solo dependency test, el
    // catálogo de versiones no se toca.
    testImplementation("io.ktor:ktor-client-mock:${libs.versions.ktor.get()}")
}
