package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId

/**
 * Nombres estables del trabajo único de descarga
 * (global-constraints.md): `download:<ownerId>:<projectId>` con
 * `ExistingWorkPolicy.KEEP` (repetir tap nunca duplica trabajo). El nombre es
 * owner-scoped: el mismo proyecto de dos owners genera keys distintas.
 */
object DownloadWorkNames {

    fun forProject(ownerId: String, projectId: ProjectId): String =
        "download:$ownerId:${projectId.value}"

    /** Tag por owner (los tags no admiten comas; los UUIDs son seguros). */
    fun ownerTag(ownerId: String): String = "download:owner:$ownerId"

    /** Tag por proyecto (para observación/cancelación por tag). */
    fun projectTag(projectId: ProjectId): String = "download:project:${projectId.value}"
}
