package com.explainer.app.feature.catalog

import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.ProjectId
import kotlinx.coroutines.flow.Flow

/**
 * Puerto del catálogo (T07, consumido por T09/T10): combina resúmenes
 * remotos, snapshots owner-scoped y estado de descarga; el contenido
 * offline se lee de T03 sin red ni token. `updated_at` resuelve el merge
 * del índice; el contenido nunca se reemplaza silenciosamente.
 */
interface ProjectCatalogRepository {
    /** Lista combinada summary ∪ snapshot ∪ download, por `updated_at` desc. */
    fun observeProjects(ownerId: String): Flow<List<ProjectListItem>>

    /** `GET /api/projects` persistido por owner; nunca borra en fallo. */
    suspend fun refresh(ownerId: String): RefreshOutcome

    /** Manifest del snapshot activo + progreso mezclado; null sin snapshot. */
    fun observeReaderProject(ownerId: String, projectId: ProjectId): Flow<ReaderProject?>

    /** Parte de la generación activa (T03), sin red; null si no existe. */
    suspend fun loadPart(ownerId: String, projectId: ProjectId, partId: Int): PartContentDocument?
}
