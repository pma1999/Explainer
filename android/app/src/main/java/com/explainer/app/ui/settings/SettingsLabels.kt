package com.explainer.app.ui.settings

import com.explainer.app.R
import com.explainer.app.core.model.ProjectId
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.ui.theme.ThemeMode

/**
 * Labels y copy de Ajustes (T11): tema y confirmaciones destructivas.
 * Copy en `strings_settings.xml`; los bytes lógicos se formatean con
 * `LibraryFormat.formatBytes`.
 */
object SettingsLabels {

    fun themeModeLabelRes(mode: ThemeMode): Int = when (mode) {
        ThemeMode.SYSTEM -> R.string.settings_theme_system
        ThemeMode.LIGHT -> R.string.settings_theme_light
        ThemeMode.DARK -> R.string.settings_theme_dark
    }

    /** Título del sheet de confirmación según la acción pendiente. */
    fun confirmationTitleRes(confirmation: SettingsConfirmation): Int = when (confirmation) {
        SettingsConfirmation.SignOut -> R.string.settings_sign_out_confirm_title
        SettingsConfirmation.DeleteAll -> R.string.settings_delete_all_confirm_title
        is SettingsConfirmation.DeleteProject -> R.string.settings_delete_project_confirm_title
    }

    /**
     * Título del sheet con el argumento de formato (R-T11-07): el recurso de
     * borrado de proyecto exige `%1$s`, así que el nombre del proyecto se
     * transporta como argumento para `stringResource(res, arg)`. Sin nombre
     * (fila ausente) o para SignOut/DeleteAll no hay argumento.
     */
    fun confirmationTitle(
        confirmation: SettingsConfirmation,
        projectName: String?,
    ): FormattedTitle = when (confirmation) {
        SettingsConfirmation.SignOut -> FormattedTitle(R.string.settings_sign_out_confirm_title, null)
        SettingsConfirmation.DeleteAll -> FormattedTitle(R.string.settings_delete_all_confirm_title, null)
        is SettingsConfirmation.DeleteProject ->
            FormattedTitle(R.string.settings_delete_project_confirm_title, projectName)
    }

    fun confirmationMessageRes(confirmation: SettingsConfirmation): Int = when (confirmation) {
        SettingsConfirmation.SignOut -> R.string.settings_sign_out_confirm_message
        SettingsConfirmation.DeleteAll -> R.string.settings_delete_all_confirm_message
        is SettingsConfirmation.DeleteProject -> R.string.settings_delete_project_confirm_message
    }

    fun confirmationLabelRes(confirmation: SettingsConfirmation): Int = when (confirmation) {
        SettingsConfirmation.SignOut -> R.string.settings_sign_out_confirm_label
        SettingsConfirmation.DeleteAll -> R.string.settings_delete_all_confirm_label
        is SettingsConfirmation.DeleteProject -> R.string.settings_delete_confirm_label
    }

    /** Nombre del proyecto para el sheet de borrado de una copia. */
    fun projectNameFor(items: List<ProjectListItem>, projectId: ProjectId): String? =
        items.firstOrNull { it.projectId == projectId }?.name
}

/**
 * Recurso + argumento de formato de un título (R-T11-07): la pantalla hace
 * `stringResource(res, arg)` solo cuando [arg] no es null (los títulos sin
 * placeholder no reciben argumentos).
 */
data class FormattedTitle(
    val res: Int,
    val arg: String?,
)
