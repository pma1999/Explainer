package com.explainer.app.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.AppBarMetrics
import com.explainer.app.ui.theme.ElevationTokens

/**
 * Top bar común de la app (chrome mínimo, una línea de título y acciones).
 *
 * Stateless; el host decide navegación (botón atrás con icono y
 * contentDescription explícita) y acciones. Targets >=
 * [ExplainerTopBarDefaults.MinimumTargetSize].
 *
 * @param title título de la pantalla.
 * @param onNavigationClick opcional: habilita el botón "Volver" con icono.
 * @param navigationLabel etiqueta accesible del botón de navegación.
 * @param action composable opcional para la zona de acciones (derecha).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExplainerTopBar(
    title: String,
    modifier: Modifier = Modifier,
    onNavigationClick: (() -> Unit)? = null,
    navigationLabel: String = stringResource(R.string.action_back),
    action: (@Composable () -> Unit)? = null,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface,
        tonalElevation = ElevationTokens.Level1,
    ) {
        TopAppBar(
            title = {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleLarge,
                    maxLines = 1,
                )
            },
            navigationIcon = {
                if (onNavigationClick != null) {
                    IconButton(
                        onClick = onNavigationClick,
                        modifier = Modifier.heightIn(min = ExplainerTopBarDefaults.MinimumTargetSize),
                    ) {
                        Icon(
                            imageVector = ExplainerIcons.ArrowBack,
                            contentDescription = navigationLabel,
                        )
                    }
                }
            },
            actions = {
                if (action != null) {
                    action()
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(
                containerColor = MaterialTheme.colorScheme.surface,
                titleContentColor = MaterialTheme.colorScheme.onSurface,
                navigationIconContentColor = MaterialTheme.colorScheme.primary,
                actionIconContentColor = MaterialTheme.colorScheme.primary,
            ),
        )
    }
}

object ExplainerTopBarDefaults {
    /** Target táctil mínimo declarado (navegación y acciones). */
    val MinimumTargetSize: Dp = 48.dp
    val Height: Dp = AppBarMetrics.TopBarHeight
}
