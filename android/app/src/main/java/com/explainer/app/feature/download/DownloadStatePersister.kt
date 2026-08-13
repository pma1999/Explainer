package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.DownloadStateDao

/**
 * Escritor durable del estado emitido por el motor (progreso en
 * `DownloadStateEntity`; WorkInfo progress solo complementa). Una escritura
 * por emisión — y las emisiones ya van throttled — por lo que nunca hay una
 * transacción Room por chunk de red.
 *
 * Anti-resurrección (R-T06-01): cada transición es un COMPARE-AND-SET
 * atómico ([DownloadStateDao.casUpdate]) condicionado por owner/project,
 * workId y estado NO terminal. La lectura previa solo deriva campos no
 * emitidos (bytes de Preparing/Committing); la escritura en sí no puede
 * sobrescribir una fila que mientras tanto fue:
 * - borrada (deleteLocal) → 0 filas afectadas, no se inserta nada;
 * - marcada terminal (cancel) → 0 filas afectadas;
 * - reclamada por otro workId → 0 filas afectadas.
 */
class DownloadStatePersister(
    private val dao: DownloadStateDao,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) {

    suspend fun persist(
        ownerId: String,
        projectId: ProjectId,
        workId: String,
        state: DownloadState,
    ) {
        val current = dao.row(ownerId, projectId.value) ?: return
        if (current.workId != workId) return
        val updated = current.withState(state, nowMillis())
        dao.casUpdate(
            ownerId = ownerId,
            projectId = projectId.value,
            expectedWorkId = workId,
            newWorkId = workId,
            state = updated.state,
            downloadedBytes = updated.downloadedBytes,
            totalBytes = updated.totalBytes,
            errorCategory = updated.errorCategory,
            finishedAt = updated.finishedAt,
        ) // 0 filas: fila borrada o terminal → el estado stale no se escribe.
    }
}
