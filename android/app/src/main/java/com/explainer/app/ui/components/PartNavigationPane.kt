package com.explainer.app.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.ui.theme.ElevationTokens
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/**
 * Elemento del pane de navegación de partes.
 *
 * @param partId id de la parte (contrato wire de la web: entero positivo).
 * @param title título de la parte.
 * @param status estado opcional de la parte (p. ej. "Completada").
 */
data class PartNavItem(
    val partId: Int,
    val title: String,
    val status: String? = null,
)

/**
 * Pane de navegación de partes: lista con divisores (sin tarjetas) para
 * compact (dentro de sheet/drawer) y rail de dos paneles en
 * medium/expanded. El item completo es el target de la interacción
 * (>= [PartNavigationPaneDefaults.MinimumTargetSize]).
 *
 * Stateless: el host decide qué ocurre al seleccionar y cómo se obtienen los
 * datos de estado.
 *
 * @param items partes a mostrar.
 * @param selectedPartId parte seleccionada; null = ninguna.
 * @param onPartSelected callback con el id de la parte pulsada.
 * @param header título opcional del pane.
 */
@Composable
fun PartNavigationPane(
    items: List<PartNavItem>,
    selectedPartId: Int?,
    onPartSelected: (Int) -> Unit,
    modifier: Modifier = Modifier,
    header: String? = null,
) {
    val colors = MaterialTheme.explainerColors
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface,
        tonalElevation = ElevationTokens.Level0,
    ) {
        Column {
            if (header != null) {
                Text(
                    text = header,
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(
                        start = Spacing.Lg,
                        end = Spacing.Lg,
                        top = Spacing.Lg,
                        bottom = Spacing.Sm,
                    ),
                )
            }
            LazyColumn {
                items(items, key = { it.partId }) { item ->
                    val isSelected = item.partId == selectedPartId
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = PartNavigationPaneDefaults.MinimumTargetSize)
                            .clickable(
                                role = Role.RadioButton,
                                onClick = { onPartSelected(item.partId) },
                            )
                            .semantics { selected = isSelected }
                            .padding(horizontal = Spacing.Lg, vertical = Spacing.Md),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Spacing.Md),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = item.title,
                                style = if (isSelected) {
                                    MaterialTheme.typography.titleSmall
                                } else {
                                    MaterialTheme.typography.bodyMedium
                                },
                                color = if (isSelected) {
                                    colors.primary
                                } else {
                                    MaterialTheme.colorScheme.onSurface
                                },
                            )
                            if (item.status != null) {
                                Text(
                                    text = item.status,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        if (isSelected) {
                            // Marcador de selección sin color-only: icono + rol
                            // seleccionado en semántica (TalkBack lee el estado).
                            Icon(
                                imageVector = ExplainerIcons.Check,
                                contentDescription = stringResource(com.explainer.app.R.string.reader_part_status_completed),
                                tint = colors.primary,
                                modifier = Modifier.size(PartNavigationPaneDefaults.SelectedIconSize),
                            )
                        }
                    }
                    HorizontalDivider(
                        modifier = Modifier.padding(start = Spacing.Lg),
                        color = MaterialTheme.colorScheme.outlineVariant,
                    )
                }
            }
        }
    }
}

object PartNavigationPaneDefaults {
    /** Target táctil mínimo declarado por fila de parte. */
    val MinimumTargetSize: Dp = 48.dp
    val SelectedIconSize: Dp = 20.dp
}
