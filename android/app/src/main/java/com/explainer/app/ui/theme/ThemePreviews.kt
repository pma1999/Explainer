package com.explainer.app.ui.theme

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

/**
 * Previews deterministas del tema: claro/oscuro explícitos (sin depender del
 * sistema), compact (360dp) y expanded (840dp). Ninguna preview inicia red,
 * Room ni WorkManager: solo composición de tokens.
 */

@Preview(
    name = "Theme surface (light)",
    widthDp = 360,
    showBackground = true,
)
@Composable
private fun ThemeLightSurfacePreview() {
    ThemeSurfaceSample(mode = ThemeMode.LIGHT, widthDp = 360)
}

@Preview(
    name = "Theme surface (dark)",
    widthDp = 360,
    showBackground = true,
)
@Composable
private fun ThemeDarkSurfacePreview() {
    ThemeSurfaceSample(mode = ThemeMode.DARK, widthDp = 360)
}

@Preview(
    name = "Theme surface (expanded dark)",
    widthDp = 840,
    showBackground = true,
)
@Composable
private fun ThemeExpandedDarkSurfacePreview() {
    ThemeSurfaceSample(mode = ThemeMode.DARK, widthDp = 840)
}

@Composable
private fun ThemeSurfaceSample(mode: ThemeMode, widthDp: Int) {
    ExplainerTheme(mode = mode) {
        val colors = if (mode == ThemeMode.DARK) ExplainerColors.Dark else ExplainerColors.Light
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
        ) {
            Column(
                modifier = Modifier
                    .padding(24.dp)
                    .width(640.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text("Fondo de papel", style = MaterialTheme.typography.titleMedium)
                Text(
                    "Superficie ${colors.surface} · Acento ${colors.primary}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                Surface(color = MaterialTheme.colorScheme.surface) {
                    Text(
                        "Lista con divisores, sin tarjetas: chrome mínimo.",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(16.dp),
                    )
                }
            }
        }
    }
}

@Preview(
    name = "Typography (light)",
    widthDp = 360,
    showBackground = true,
)
@Composable
private fun TypographyPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(24.dp),
            ) {
                Text("Display small", style = MaterialTheme.typography.displaySmall)
                Text("Headline large", style = MaterialTheme.typography.headlineLarge)
                Text("Headline medium", style = MaterialTheme.typography.headlineMedium)
                Text("Headline small", style = MaterialTheme.typography.headlineSmall)
                Text("Title large", style = MaterialTheme.typography.titleLarge)
                Text("Title medium", style = MaterialTheme.typography.titleMedium)
                Text("Title small", style = MaterialTheme.typography.titleSmall)
                Text("Body large", style = MaterialTheme.typography.bodyLarge)
                Text("Body medium", style = MaterialTheme.typography.bodyMedium)
                Text("Body small", style = MaterialTheme.typography.bodySmall)
                Text("Label large", style = MaterialTheme.typography.labelLarge)
                Text("Label medium", style = MaterialTheme.typography.labelMedium)
                Text("Label small", style = MaterialTheme.typography.labelSmall)
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Text("Claro", style = MaterialTheme.typography.labelMedium)
                    Spacer(Modifier.width(8.dp))
                    Text("Oscuro", style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

@Preview(
    name = "Reading typography (expanded, dark)",
    widthDp = 840,
    showBackground = true,
)
@Composable
private fun ReadingTypographyPreview() {
    ExplainerTheme(mode = ThemeMode.DARK) {
        Surface(color = MaterialTheme.colorScheme.background) {
            val reading = DefaultReadingTypography
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(24.dp)
                    .verticalScroll(rememberScrollState()),
            ) {
                Text("Título de lectura", style = reading.heading1)
                Text("Sección", style = reading.heading2)
                Text("Subsección", style = reading.heading3)
                Text(
                    "Cuerpo de lectura: la explicación se compone en Source Serif 4 " +
                        "con un factor de línea de 1.65 y un ancho máximo de 640dp, " +
                        "para una lectura serena incluso a escala de fuente alta.",
                    style = reading.body,
                )
                Text(
                    "— Una cita en itálica, como conviene al texto académico.",
                    style = reading.quote,
                )
                Text("código o fragmento técnico", style = reading.code)
                Text("Nota al pie de la lectura.", style = reading.caption)
            }
        }
    }
}
