package com.explainer.app.di

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.DownloadStateDao
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.db.SnapshotDao
import com.explainer.app.data.local.snapshot.SnapshotOwnerValidator
import com.explainer.app.data.local.snapshot.SnapshotStoreException
import kotlinx.coroutines.flow.first

/**
 * Borrado total de datos locales de UN owner (T11): enumera las filas del
 * owner activo (summary ∪ snapshot ∪ download) y delega el borrado
 * proyecto a proyecto en [deleteProject] — en producción, el
 * `deleteLocal` del coordinador T06, que exige igualdad ESTRICTA con el
 * owner de sesión, de modo que "borrar todo" nunca toca datos de otro
 * owner ni del remoto. Al final ejecuta un checkpoint best-effort.
 *
 * Acción separada del logout: no toca sesión ni flag de acceso.
 */
class LocalDataDeleter(
    private val summaryDao: ProjectSummaryDao,
    private val snapshotDao: SnapshotDao,
    private val downloadDao: DownloadStateDao,
    private val deleteProject: suspend (ownerId: String, projectId: ProjectId) -> Unit,
    private val checkpoint: suspend () -> Unit,
) {
    suspend fun deleteAllLocal(ownerId: String) {
        val owner = try {
            SnapshotOwnerValidator.requireValidOwner(ownerId)
        } catch (_: SnapshotStoreException) {
            return
        }
        val ids = (
            summaryDao.observeSummaries(owner).first().map { it.projectId } +
                snapshotDao.observeSnapshots(owner).first().map { it.projectId } +
                downloadDao.observeProjectIds(owner).first()
            ).distinct()

        ids.forEach { id ->
            ProjectId.parse(id)?.let { deleteProject(owner, it) }
        }
        checkpoint()
    }
}
