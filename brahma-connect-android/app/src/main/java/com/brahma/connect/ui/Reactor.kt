package com.brahma.connect.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.brahma.connect.core.ConnectionState
import kotlin.math.min

/**
 * Reactor state labels mirror the desktop J.A.R.V.I.S. HUD states so the
 * mobile companion shows the same vocabulary:
 * INITIALISING / READY / LISTENING / THINKING / PROCESSING / SPEAKING /
 * ERROR / OFFLINE.
 */
fun reactorStateLabel(state: ConnectionState, hasError: Boolean): String {
    if (hasError) return "ERROR"
    return when (state) {
        ConnectionState.CONNECTING -> "INITIALISING"
        ConnectionState.CONNECTED -> "READY"
        ConnectionState.RECONNECTING -> "RECONNECTING"
        ConnectionState.DISCONNECTED -> "OFFLINE"
    }
}

internal fun reactorAccent(stateLabel: String): Color = when (stateLabel) {
    "LISTENING" -> Color(0xFF457FFF)
    "THINKING" -> Color(0xFFFFB960)
    "PROCESSING", "EXECUTING" -> Color(0xFFFFB300)
    "SPEAKING" -> Color(0xFFFFB300)
    "ERROR" -> Color(0xFFFF4040)
    "OFFLINE", "DISCONNECTED" -> Color(0xFF6E7682)
    "READY", "STANDBY" -> Color(0xFF78DCA9)
    else -> Color(0xFFFFB300)
}

/**
 * Live animated J.A.R.V.I.S. arc-reactor for the Android companion.
 * The core is drawn every frame with Compose Canvas + an infinite
 * animation — it is never a static image. The background is kept minimal:
 * two thin rings, one rotating segmented energy ring and a restrained glow.
 */
@Composable
fun JarvisReactor(
    state: String,
    modifier: Modifier = Modifier,
) {
    val accent = reactorAccent(state)
    val transition = rememberInfiniteTransition(label = "reactor")
    val angle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(5200, easing = LinearEasing), RepeatMode.Restart),
        label = "reactorSpin",
    )
    val counterAngle by transition.animateFloat(
        initialValue = 0f,
        targetValue = -360f,
        animationSpec = infiniteRepeatable(tween(7800, easing = LinearEasing), RepeatMode.Restart),
        label = "reactorCounterSpin",
    )
    val breath by transition.animateFloat(
        initialValue = 0.0f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(tween(2600, easing = LinearEasing), RepeatMode.Reverse),
        label = "reactorBreath",
    )

    val glowAlpha = (34 + breath * 40).toInt().coerceIn(0, 90)
    val ringAlpha = (60 + breath * 55).toInt().coerceIn(0, 150)

    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val side = min(size.width, size.height)
            val c = Offset(size.width / 2f, size.height / 2f)
            val coreR = side * 0.205f

            // Restrained ambient glow behind the core
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        accent.copy(alpha = glowAlpha / 255f),
                        accent.copy(alpha = 0f),
                    ),
                    center = c,
                    radius = coreR * 2.3f,
                ),
                radius = coreR * 2.3f,
                center = c,
            )

            // Two thin faint HUD rings
            drawCircle(color = accent.copy(alpha = 0.16f), radius = side * 0.42f, center = c, style = Stroke(width = 1.2f))
            drawCircle(color = accent.copy(alpha = 0.10f), radius = side * 0.375f, center = c, style = Stroke(width = 1.0f))

            // Rotating segmented energy ring
            val seg = side * 0.42f
            drawArc(
                color = accent.copy(alpha = ringAlpha / 255f),
                startAngle = angle,
                sweepAngle = 108f,
                useCenter = false,
                topLeft = Offset(c.x - seg, c.y - seg),
                size = Size(seg * 2f, seg * 2f),
                style = Stroke(width = 2.4f, cap = StrokeCap.Round),
            )
            drawArc(
                color = accent.copy(alpha = (ringAlpha * 0.72f).toInt() / 255f),
                startAngle = counterAngle,
                sweepAngle = 76f,
                useCenter = false,
                topLeft = Offset(c.x - seg, c.y - seg),
                size = Size(seg * 2f, seg * 2f),
                style = Stroke(width = 1.8f, cap = StrokeCap.Round),
            )

            // Outer tick ring (thin, sparse)
            val tickR = side * 0.462f
            for (i in 0 until 36) {
                if (i % 3 == 0) continue
                val a = Math.toRadians(i * 10.0)
                val x0 = c.x + kotlin.math.cos(a).toFloat() * tickR
                val y0 = c.y + kotlin.math.sin(a).toFloat() * tickR
                val x1 = c.x + kotlin.math.cos(a).toFloat() * (tickR - side * 0.008f)
                val y1 = c.y + kotlin.math.sin(a).toFloat() * (tickR - side * 0.008f)
                val tickAlpha = if (i % 2 == 0) 0.17f else 0.09f
                drawLine(
                    color = Color(0xFFEBF0F8).copy(alpha = tickAlpha),
                    start = Offset(x0, y0),
                    end = Offset(x1, y1),
                    strokeWidth = 1f,
                )
            }

            // Dark reactor dish
            drawCircle(color = Color(0xFF07090D), radius = coreR * 1.06f, center = c)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        accent.copy(alpha = 0.5f + breath * 0.22f),
                        Color(0xFF0B0E13),
                        Color(0xFF020305),
                    ),
                    center = c,
                    radius = coreR * 1.06f,
                ),
                radius = coreR * 1.06f,
                center = c,
            )
            drawCircle(
                color = accent.copy(alpha = (ringAlpha * 0.9f).toInt() / 255f),
                radius = coreR * 1.02f,
                center = c,
                style = Stroke(width = 1.6f),
            )

            // Inner energy core
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        Color(0xFFFFF2D6),
                        accent.copy(alpha = 0.95f),
                        accent.copy(alpha = 0.05f),
                    ),
                    center = c,
                    radius = coreR * 0.72f,
                ),
                radius = coreR * 0.72f,
                center = c,
            )
        }

        // Deterministic Latin wordmark rendered by the UI text system.
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "J.A.R.V.I.S.",
                color = Color.White,
                fontSize = 13.sp,
                fontWeight = FontWeight.Black,
                letterSpacing = 0.6.sp,
            )
            Text(
                text = state,
                color = accent,
                fontSize = 8.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.2.sp,
                modifier = Modifier.padding(top = 2.dp),
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
