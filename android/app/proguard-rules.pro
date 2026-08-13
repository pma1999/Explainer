# Reglas R8 del módulo :app — release hardening (T12).
# R8 activo con isMinifyEnabled=true + isShrinkResources=true (build.gradle.kts).
# Principio: reglas mínimas y con evidencia; cada bloque cita su necesidad.
# NO duplicar reglas ya aportadas por consumer rules de dependencias:
#   - WorkManager (work-runtime proguard.txt): -keepnames de ListenableWorker/
#     InputMerger + WorkerParameters.
#   - Room 3 (room3-runtime proguard.txt): -keep de subclases RoomDatabase,
#     -dontwarn androidx.room3.paging.** / androidx.lifecycle.LiveData.
#   - Ktor/WebKit/Compose/coroutines: sus AARs publican consumer rules propias.

# --- kotlinx.serialization (clases propias de la app) ---
# Reglas oficiales de kotlinx.serialization (docs Kotlin, sección R8/ProGuard),
# acotadas a com.explainer.app.**: los serializers generados ($$serializer) y
# sus descriptors se instancian por reflection al serializar los DTOs de red
# (ProjectDetailDto/ProjectSummaryDto/...), rutas de navegación @Serializable
# y MermaidRenderRequest (todos bajo com.explainer.app.**).
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

-keep,includedescriptorclasses class com.explainer.app.**$$serializer { *; }
-keepclassmembers class com.explainer.app.** {
    *** Companion;
}
-keepclasseswithmembers class com.explainer.app.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# --- kotlinx.serialization-json ---
# Regla oficial del proyecto (evita NoClassDefFoundError de
# kotlinx.serialization.json.JsonObjectSerializer si se usa por reflection).
-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Nota T12: supabase-kt (io.github.jan.supabase.**) no publica consumer rules;
# sus DTOs @Serializable se usan desde su propio código con referencias
# directas a los serializers generados (Session/UserInfo), por lo que R8 los
# conserva sin reglas adicionales. Si un release real revelara un
# MissingClass/NoSuchMethod, se añadiría la regla mínima con esa evidencia.
