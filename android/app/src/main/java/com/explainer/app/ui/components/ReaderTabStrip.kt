package com.explainer.app.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.AppBarMetrics
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/**
 * Especificación de una pestaña del lector: nombre wire (contrato con la web,
 * frontend/js/router.js `VALID_TABS`), etiqueta visible e icono decorativo.
 */
data class ReaderTabSpec(
    val wireName: String,
    val label: String,
    val icon: ImageVector,
)

/** Pestañas canónicas del lector en orden web. */
object ReaderTabNames {
    val CanonicalWireNames = listOf("explicacion", "recorrido", "recursos", "esquema", "repaso")
}

/** Etiquetas e iconos canónicos resueltos con la copia compartida. */
@Composable
fun canonicalReaderTabs(): List<ReaderTabSpec> = listOf(
    ReaderTabSpec("explicacion", stringResource(R.string.tab_explicacion), ExplainerIcons.MenuBook),
    ReaderTabSpec("recorrido", stringResource(R.string.tab_recorrido), ExplainerIcons.Map),
    ReaderTabSpec("recursos", stringResource(R.string.tab_recursos), ExplainerIcons.Link),
    ReaderTabSpec("esquema", stringResource(R.string.tab_esquema), ExplainerIcons.AccountTree),
    ReaderTabSpec("repaso", stringResource(R.string.tab_repaso), ExplainerIcons.Quiz),
)

/**
 * Tira de pestañas del lector, desplazable (compact a pantalla completa;
 * medium/expanded el host decide panel/rail). Selección por nombre wire;
 * valores desconocidos los normaliza el host (p. ej. a `explicacion`).
 *
 * Icono + etiqueta por pestaña (nunca solo icono ni solo color: el estado
 * seleccionado también viaja en la semántica). Los targets de pestaña
 * cumplen [ReaderTabStripDefaults.MinimumTargetSize] y cada `Tab` expone
 * rol/estado seleccionado a TalkBack.
 *
 * @param selectedTab nombre wire seleccionado.
 * @param onTabSelected callback con el nombre wire pulsado.
 * @param tabs especificaciones (por defecto las canónicas).
 */
@Composable
fun ReaderTabStrip(
    selectedTab: String,
    onTabSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
    tabs: List<ReaderTabSpec> = canonicalReaderTabs(),
) {
    val colors = MaterialTheme.explainerColors
    val selectedIndex = tabs.indexOfFirst { it.wireName == selectedTab }.coerceAtLeast(0)
    ScrollableTabRow(
        selectedTabIndex = selectedIndex,
        modifier = modifier.fillMaxWidth(),
        containerColor = MaterialTheme.colorScheme.surface,
        contentColor = colors.primary,
        edgePadding = 8.dp,
        indicator = { tabPositions ->
            TabRowDefaults.SecondaryIndicator(
                modifier = Modifier.tabIndicatorOffset(tabPositions[selectedIndex]),
                color = colors.primary,
            )
        },
        divider = {},
    ) {
        tabs.forEach { tab ->
            Tab(
                selected = tab.wireName == selectedTab,
                onClick = { onTabSelected(tab.wireName) },
                text = {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Icon(
                            imageVector = tab.icon,
                            contentDescription = null,
                            modifier = Modifier.size(ReaderTabStripDefaults.IconSize),
                        )
                        Spacer(Modifier.height(Spacing.Xs))
                        Text(
                            text = tab.label,
                            style = MaterialTheme.typography.labelLarge,
                            maxLines = 1,
                        )
                    }
                },
                selectedContentColor = colors.primary,
                unselectedContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.heightIn(min = ReaderTabStripDefaults.MinimumTargetSize),
            )
        }
    }
}

object ReaderTabStripDefaults {
    /** Target táctil mínimo declarado por pestaña. */
    val MinimumTargetSize: Dp = 48.dp
    val Height: Dp = AppBarMetrics.TabStripHeight
    val IconSize: Dp = 20.dp
}
