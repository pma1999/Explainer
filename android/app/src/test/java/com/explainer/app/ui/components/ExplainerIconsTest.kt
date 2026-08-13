package com.explainer.app.ui.components

import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathNode
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.graphics.vector.VectorGroup
import androidx.compose.ui.graphics.vector.VectorPath
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Iconoteca propia (T14): todos los trazados SVG de [ExplainerIcons] deben
 * parsear sin error y producir al menos un nodo de dibujo (un trazado vacío
 * sería un icono invisible sin aviso). El relleno es siempre negro porque el
 * tinte lo aplica el host (`Icon(tint = …)`).
 */
class ExplainerIconsTest {

    /** Todos los nodos de dibujo de un [ImageVector], recorriendo grupos. */
    private fun ImageVector.pathNodes(): List<PathNode> {
        val nodes = mutableListOf<PathNode>()
        fun walk(group: VectorGroup) {
            group.forEach { node ->
                when (node) {
                    is VectorGroup -> walk(node)
                    is VectorPath -> nodes.addAll(node.pathData)
                }
            }
        }
        walk(root)
        return nodes
    }

    @Test
    fun todosLosIconosParseanConNodosDeDibujo() {
        // Las propiedades del object son lazy delegates: se enumeran los
        // getters (getArrowBack…), no los campos.
        val getters = ExplainerIcons::class.java.methods
            .filter { it.parameterCount == 0 && it.returnType == ImageVector::class.java }
        assertTrue("la iconoteca no debe estar vacía", getters.isNotEmpty())
        getters.forEach { getter ->
            val vector = getter.invoke(ExplainerIcons) as ImageVector
            val nodes = vector.pathNodes()
            assertTrue("el icono ${getter.name} no tiene trazado", nodes.isNotEmpty())
        }
    }

    @Test
    fun losTrazadosMaestrosParseanSinExcepcion() {
        // El parseo de los path strings maestros es determinista: un trazado
        // malformado fallaría aquí en lugar de en runtime.
        listOf(
            "ArrowBack", "Refresh", "Check", "Close", "Add", "Delete", "Settings",
            "Download", "Warning", "Error", "Info", "KeyboardArrowDown", "KeyboardArrowUp",
            "KeyboardArrowLeft", "KeyboardArrowRight", "Visibility", "VisibilityOff",
            "OpenInNew", "ContentCopy", "Email", "Lock", "CloudOff", "FolderOpen",
            "Storage", "Logout", "MenuBook", "Map", "Link", "AccountTree", "Quiz",
            "OpenInFull", "Inbox", "Done",
        ).forEach { iconName ->
            val getter = ExplainerIcons::class.java.getMethod("get$iconName")
            val vector = getter.invoke(ExplainerIcons) as ImageVector
            assertTrue("el icono $iconName no tiene paths", vector.pathNodes().isNotEmpty())
        }
    }

    @Test
    fun PathParser_parseaTrazadosMaterialSinExcepcion() {
        val sample = "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"
        val nodes = PathParser().parsePathString(sample).toNodes()
        assertTrue(nodes.isNotEmpty())
    }

    @Test
    fun losNodosRelativosSeConservanEnElVectorConstruido() {
        // Regresión (bug de iconos rotos): un walker manual reemitía los
        // nodos por el DSL y descartaba los comandos relativos (h/v/c/s/q…
        // en minúscula), que dominan los trazados Material → la mayoría de
        // los iconos se dibujaban incompletos. El vector construido debe
        // conservar esos nodos: el renderer nativo los resuelve. Close es el
        // único trazado de la iconoteca 100 % absoluto.
        val getters = ExplainerIcons::class.java.methods
            .filter { it.parameterCount == 0 && it.returnType == ImageVector::class.java }
        getters.forEach { getter ->
            if (getter.name == "getClose") return@forEach
            val vector = getter.invoke(ExplainerIcons) as ImageVector
            val hasRelativeNodes = vector.pathNodes().any { it.isRelative() }
            assertTrue(
                "el icono ${getter.name} perdió sus nodos relativos al construirse",
                hasRelativeNodes,
            )
        }
    }

    private fun PathNode.isRelative(): Boolean = when (this) {
        is PathNode.RelativeMoveTo,
        is PathNode.RelativeLineTo,
        is PathNode.RelativeHorizontalTo,
        is PathNode.RelativeVerticalTo,
        is PathNode.RelativeCurveTo,
        is PathNode.RelativeReflectiveCurveTo,
        is PathNode.RelativeQuadTo,
        is PathNode.RelativeReflectiveQuadTo,
        is PathNode.RelativeArcTo,
        -> true

        else -> false
    }
}
