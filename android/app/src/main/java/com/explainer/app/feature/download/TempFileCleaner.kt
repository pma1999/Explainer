package com.explainer.app.feature.download

import java.io.File

/**
 * Limpieza VERIFICABLE y SCOPED de temporales de descarga (R-T06-06):
 * `File.delete()` es best-effort (devuelve un booleano que la mayoría del
 * código ignora), así que aquí el borrado se verifica, se reintenta una vez y,
 * si el filesystem sigue negándose, el temporal queda REGISTRADO como orphan
 * (contador [orphansPending] + nombre con namespace) para un [sweepOrphans]
 * posterior (al arrancar una descarga o tras cancel/delete).
 *
 * El sweep es SCOPED por owner/proyecto (ronda 2 de R-T06-06): los temporales
 * se nombran `download-<owner>-<project>-<uuid>.json` — owner y project ya
 * validados antes de entrar aquí (`SnapshotOwnerValidator` y `ProjectId`:
 * ambos seguros para filesystem y sin `..`) — de modo que el sweep de una
 * descarga SOLO ve los huérfanos de SU propiedad y jamás toca el temporal
 * ACTIVO de otro proyecto/owner que comparta el cacheDir. Un proyecto/owner
 * tiene a lo sumo un download activo (unique work + CAS de workId), así que
 * dentro del propio namespace el sweep solo encuentra huérfanos de corridas
 * previas. Nunca se borra nada fuera de cacheDir.
 */
class TempFileCleaner(
    private val tempDirProvider: () -> File,
    private val deleteFile: (File) -> Boolean = File::delete,
) {

    /** Temporales que el FS no dejó borrar y quedan pendientes de sweep. */
    var orphansPending: Int = 0
        private set

    /**
     * Borrado verificado con reintento. Devuelve `true` si el fichero ya no
     * existe (borrado o nunca creado); `false` solo si el FS lo impide y el
     * temporal queda registrado como orphan.
     */
    fun deleteVerified(file: File?): Boolean {
        if (file == null) return true
        // `File(path)` no crea el fichero; delete() sobre uno inexistente
        // devuelve false y NO es un orphan (nunca llegó a existir).
        if (!file.exists()) return true
        if (deleteFile(file)) return true
        // Reintento inmediato: locks transitorios (antivirus/WAL/Windows).
        if (deleteFile(file)) return true
        orphansPending++
        return !file.exists()
    }

    /**
     * Elimina SOLO los temporales huérfanos de este owner/proyecto (prefijo
     * con namespace estable). Los temporales de OTROS proyectos/owners —
     * incluidos los ACTIVOS — nunca se tocan (R-T06-06). Devuelve cuántos
     * ficheros borró.
     */
    fun sweepOrphans(ownerId: String, projectId: String): Int {
        val dir = tempDirProvider()
        if (!dir.isDirectory) return 0
        val prefix = prefixFor(ownerId, projectId)
        return dir.listFiles()?.count { f ->
            f.isFile && f.name.startsWith(prefix) && f.name.endsWith(TEMP_FILE_SUFFIX) &&
                deleteFile(f)
        } ?: 0
    }

    /**
     * Nombre estable de temporal con namespace owner/proyecto + UUID generado
     * localmente (brief: "Los temporales se nombran con UUID generado
     * localmente bajo cache; validar project/owner").
     */
    fun tempFileName(ownerId: String, projectId: String, uuid: String): String =
        prefixFor(ownerId, projectId) + uuid + TEMP_FILE_SUFFIX

    companion object {
        const val TEMP_FILE_PREFIX = "download-"
        const val TEMP_FILE_SUFFIX = ".json"

        /**
         * Prefijo con namespace `download-<owner>-<project>-`. Es inyectivo
         * para pares (owner, project) válidos (owner `[A-Za-z0-9._-]` sin
         * `..`, project UUID de 36 chars): un fichero solo puede matchear el
         * prefijo de su propio par, nunca el de otro proyecto/owner.
         */
        fun prefixFor(ownerId: String, projectId: String): String =
            TEMP_FILE_PREFIX + ownerId + "-" + projectId + "-"
    }
}
