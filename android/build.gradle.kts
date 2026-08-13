// Root build.
// AGP 9 usa Kotlin built-in (no se aplica org.jetbrains.kotlin.android). Para
// fijar KGP 2.4.10 y KSP 2.3.11 (más altos que el runtime mínimo de AGP 9.0,
// KGP 2.2.10) se anclan aquí vía buildscript, según la guía oficial AGP 9.
buildscript {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
    dependencies {
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.10")
        classpath("com.google.devtools.ksp:symbol-processing-gradle-plugin:2.3.11")
    }
}

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.ksp) apply false
}
