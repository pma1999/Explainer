package com.explainer.app.ui.components

import androidx.compose.ui.unit.dp
import com.explainer.app.ui.theme.AppBreakpoints
import com.explainer.app.ui.theme.AppBarMetrics
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.WindowSize
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tamaños mínimos de target declarados por componente (WCAG 2.5.8 / Material:
 * >= 48dp) y umbrales de breakpoint estables. Los componentes son stateless:
 * estos contratos los consume T09/T10.
 */
class ComponentTargetsTest {

    @Test
    fun allComponentsDeclareAtLeast48dpTargets() {
        val targets = listOf(
            "ExplainerTopBar" to ExplainerTopBarDefaults.MinimumTargetSize,
            "StatusIndicator" to StatusIndicatorDefaults.MinimumTargetSize,
            "OfflineBanner" to OfflineBannerDefaults.MinimumHeight,
            "OperationStatePanel" to OperationStatePanelDefaults.MinimumActionHeight,
            "DownloadProgressRow" to DownloadProgressRowDefaults.MinimumTargetSize,
            "ConfirmActionSheet" to ConfirmActionSheetDefaults.MinimumTargetSize,
            "ReaderTabStrip" to ReaderTabStripDefaults.MinimumTargetSize,
            "PartNavigationPane" to PartNavigationPaneDefaults.MinimumTargetSize,
        )
        targets.forEach { (name, size) ->
            assertTrue("$name target $size < 48dp", size >= 48.dp)
        }
    }

    @Test
    fun universalMinimumTargets_areAtLeast48dp() {
        assertTrue(MinimumTargets.Touch >= 48.dp)
        assertTrue(MinimumTargets.Row >= 48.dp)
        assertTrue(MinimumTargets.ActionButton >= 48.dp)
    }

    @Test
    fun chromeHeights_doNotShrinkBelow48dp() {
        assertTrue(AppBarMetrics.TopBarHeight >= 48.dp)
        assertTrue(AppBarMetrics.TabStripHeight >= 48.dp)
    }

    @Test
    fun breakpointThresholds_areStableAndOrdered() {
        assertTrue(AppBreakpoints.CompactMaxWidthDp < AppBreakpoints.MediumMaxWidthDp)
        assertTrue(AppBreakpoints.MediumMaxWidthDp < AppBreakpoints.ExpandedMinWidthDp)
        assertEquals(599, AppBreakpoints.CompactMaxWidthDp)
        assertEquals(839, AppBreakpoints.MediumMaxWidthDp)
        assertEquals(840, AppBreakpoints.ExpandedMinWidthDp)
    }

    @Test
    fun windowSize_enum_coversThreeModes() {
        assertEquals(listOf("COMPACT", "MEDIUM", "EXPANDED"), WindowSize.entries.map { it.name })
    }

    @Test
    fun statusTone_enum_coversSemanticStates() {
        assertEquals(
            listOf("SUCCESS", "WARNING", "ERROR", "OFFLINE", "NEUTRAL"),
            StatusTone.entries.map { it.name },
        )
    }

    @Test
    fun operationState_enum_coversOperationalStates() {
        assertEquals(
            listOf("LOADING", "EMPTY", "ERROR", "OFFLINE"),
            OperationState.entries.map { it.name },
        )
    }
}
