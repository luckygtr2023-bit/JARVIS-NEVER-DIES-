package com.brahma.connect.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.brahma.connect.BrahmaConnectForegroundService
import com.brahma.connect.core.AgentStateStore
import com.brahma.connect.core.ConnectionState
import com.brahma.connect.core.DeviceCredential
import com.brahma.connect.core.GatewayEndpoint
import com.brahma.connect.core.PairingOffer
import com.brahma.connect.network.BrahmaGatewayDiscovery
import com.brahma.connect.pairing.PairingPayloadParser
import com.brahma.connect.pairing.PairingStorage
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import kotlinx.coroutines.launch
import java.util.concurrent.Executors

import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.compose.ui.draw.clip
import kotlinx.coroutines.delay
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.material3.Icon
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send



@Composable
fun BrahmaConnectApp(
    onRequestCameraPermission: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    onStartService: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val discovery = remember { BrahmaGatewayDiscovery(context) }
    val storage = remember { PairingStorage(context) }
    val connectionState by AgentStateStore.connectionState.collectAsState()
    val gateway by AgentStateStore.gateway.collectAsState()
    val credential by AgentStateStore.credential.collectAsState()
    val pairingOffer by AgentStateStore.pairingOffer.collectAsState()
    val status by AgentStateStore.statusText.collectAsState()
    val lastError by AgentStateStore.lastError.collectAsState()
    val logs by AgentStateStore.logs.collectAsState()

    var showManual by rememberSaveable { mutableStateOf(false) }
    var manualHost by rememberSaveable { mutableStateOf("") }
    var manualPort by rememberSaveable { mutableStateOf("8765") }
    var scanError by rememberSaveable { mutableStateOf<String?>(null) }

    DisposableEffect(Unit) {
        onDispose { discovery.stop() }
    }

    val cameraGranted = remember { ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED }
    val notificationsGranted = remember { Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED }
    
    val setupMissing = listOfNotNull(
        if (!cameraGranted) "Camera" else null,
        if (!notificationsGranted) "Notifications" else null,
    )

    val navController = rememberNavController()

    // Determine start destination
    val startDest = when {
        setupMissing.isNotEmpty() -> "permissions"
        credential != null -> "home"
        else -> "welcome"
    }

    LaunchedEffect(credential) {
        if (credential != null && navController.currentDestination?.route != "home" && navController.currentDestination?.route != "connected_anim") {
            navController.navigate("connected_anim") {
                popUpTo(0)
            }
        }
    }

    Box(
        modifier = Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color(0xFF020305)),
    ) {
        // Minimal dark background: the live reactor + status cards are the focus.
        // UI Overlay
        NavHost(
            navController = navController, 
            startDestination = startDest,
            modifier = Modifier.fillMaxSize(),
            enterTransition = { fadeIn(tween(500)) },
            exitTransition = { fadeOut(tween(500)) }
        ) {
            composable("permissions") {
                StartupPermissionsScreen(
                    missingItems = setupMissing,
                    cameraGranted = cameraGranted,
                    notificationsGranted = notificationsGranted,
                    onRequestCameraPermission = onRequestCameraPermission,
                    onRequestNotificationPermission = onRequestNotificationPermission,
                    onContinue = { 
                        if (credential != null) navController.navigate("home") { popUpTo(0) }
                        else navController.navigate("welcome") { popUpTo(0) }
                    }
                )
            }
            composable("welcome") {
                WelcomeScreen(
                    onNext = { navController.navigate("about") }
                )
            }
            composable("about") {
                AboutScreen(
                    onNext = { navController.navigate("connect") }
                )
            }
            composable("connect") {
                // If they have an offer, jump to pairing
                if (pairingOffer != null) {
                    PairingPendingScreen(
                        offer = pairingOffer!!,
                        gateway = gateway,
                        state = connectionState,
                        status = status,
                        error = lastError,
                        onRequestPairing = onStartService,
                        onCancel = { AgentStateStore.setPairingOffer(null) },
                    )
                } else if (showManual) {
                    ManualConnectDialog(
                        host = manualHost, port = manualPort,
                        onHostChange = { manualHost = it }, onPortChange = { manualPort = it },
                        onDismiss = { showManual = false },
                        onConnect = {
                            val p = manualPort.toIntOrNull() ?: 8765
                            AgentStateStore.setGateway(GatewayEndpoint(name = "JARVIS PC", host = manualHost.trim(), port = p))
                            AgentStateStore.setStatus("Manual endpoint selected")
                            onStartService()
                            showManual = false
                            navController.navigate("connected_anim")
                        }
                    )
                } else {
                    ConnectChoiceScreen(
                        onScanQr = { 
                            if (!cameraGranted) onRequestCameraPermission()
                            navController.navigate("scanner") 
                        },
                        onEnterIp = { showManual = true },
                        onFindLocal = {
                            discovery.start(
                                onFound = {
                                    AgentStateStore.setGateway(it)
                                    AgentStateStore.setStatus("Gateway Online")
                                    onStartService()
                                    navController.navigate("connected_anim")
                                },
                                onError = { AgentStateStore.setError(it) }
                            )
                        }
                    )
                }
            }
            composable("scanner") {
                QrScannerScreen(
                    onBack = { navController.popBackStack() },
                    onRequestPermission = onRequestCameraPermission,
                    errorText = scanError,
                    onScanned = { raw ->
                        val offer = PairingPayloadParser.parse(raw)
                        if (offer == null) {
                            scanError = "That QR code does not look like a J.A.R.V.I.S. pairing code."
                            AgentStateStore.setError(scanError)
                        } else {
                            scanError = null
                            storage.saveGatewayHint(offer)
                            AgentStateStore.setPairingOffer(offer)
                            AgentStateStore.setGateway(GatewayEndpoint(name = "JARVIS PC", host = offer.host, port = offer.port))
                            AgentStateStore.setStatus("Pairing payload loaded")
                            navController.popBackStack()
                        }
                    }
                )
            }
            composable("connected_anim") {
                ConnectedAnimatedScreen(
                    onFinished = { navController.navigate("home") { popUpTo(0) } }
                )
            }
            composable("home") {
                if (credential != null) {
                    ConnectedScreen(
                        credential = credential!!,
                        gateway = gateway,
                        state = connectionState,
                        logs = logs,
                        status = status,
                        error = lastError,
                        onDisconnect = {
                            context.startService(Intent(context, BrahmaConnectForegroundService::class.java).apply {
                                action = BrahmaConnectForegroundService.ACTION_STOP
                            })
                            navController.navigate("welcome") { popUpTo(0) }
                        },
                        onOpenPermissions = {
                            val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                                data = Uri.fromParts("package", context.packageName, null)
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            context.startActivity(intent)
                        },
                        onOpenChat = { navController.navigate("chat") }
                    )
                }
            }
            composable("chat") {
                ChatScreen(
                    onBack = { navController.popBackStack() },
                    onSendMessage = { text ->
                        val intent = Intent(context, BrahmaConnectForegroundService::class.java).apply {
                            action = BrahmaConnectForegroundService.ACTION_SEND_CHAT
                            putExtra(BrahmaConnectForegroundService.EXTRA_CHAT_TEXT, text)
                        }
                        context.startService(intent)
                    }
                )
            }
        }
    }
}

// --- NEW ONBOARDING SCREENS ---

@Composable
fun GlassCard(content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp),
        colors = CardDefaults.cardColors(
            containerColor = androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.55f)
        ),
        shape = RoundedCornerShape(24.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f))
    ) {
        Column(modifier = Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            content()
        }
    }
}

@Composable
fun WelcomeScreen(onNext: () -> Unit) {
    Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text("J.A.R.V.I.S.", style = MaterialTheme.typography.displayMedium, fontWeight = FontWeight.Black, color = MaterialTheme.colorScheme.primary)
        Text("MOBILE COMPANION", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Light, color = androidx.compose.ui.graphics.Color.White)
        Spacer(modifier = Modifier.height(6.dp))
        Text("Just A Rather Very Intelligent System", style = MaterialTheme.typography.bodySmall, color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.6f))
        Spacer(modifier = Modifier.height(52.dp))
        GlassCard {
            Text("Your private gateway to the J.A.R.V.I.S. system on your PC.", style = MaterialTheme.typography.bodyLarge, color = androidx.compose.ui.graphics.Color.White, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onNext, modifier = Modifier.fillMaxWidth()) {
                Text("Get Started")
            }
        }
    }
}

@Composable
fun AboutScreen(onNext: () -> Unit) {
    Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        GlassCard {
            Text("J.A.R.V.I.S.", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black, color = MaterialTheme.colorScheme.primary)
            Spacer(modifier = Modifier.height(6.dp))
            Text("Just A Rather Very Intelligent System", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold, color = androidx.compose.ui.graphics.Color.White, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            Spacer(modifier = Modifier.height(14.dp))
            Text("The secure mobile bridge between your Android device and the J.A.R.V.I.S. desktop system. Connection and AI routing (Ollama · OmniRoute · OpenRouter/Gemini) always stay on your PC gateway.", color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.82f), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            Spacer(modifier = Modifier.height(14.dp))
            Text("Owner: Lucky", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold, color = androidx.compose.ui.graphics.Color.White)
            Spacer(modifier = Modifier.height(4.dp))
            Text("Made by Lucky", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onNext, modifier = Modifier.fillMaxWidth()) {
                Text("Continue")
            }
        }
    }
}

@Composable
fun ConnectChoiceScreen(onScanQr: () -> Unit, onEnterIp: () -> Unit, onFindLocal: () -> Unit) {
    Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        GlassCard {
            Text("Pair Device", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onScanQr, modifier = Modifier.fillMaxWidth()) { Text("Scan QR Code") }
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedButton(onClick = onFindLocal, modifier = Modifier.fillMaxWidth()) { Text("Auto Discover") }
            Spacer(modifier = Modifier.height(12.dp))
            TextButton(onClick = onEnterIp) { Text("Enter IP Manually", color = androidx.compose.ui.graphics.Color.White) }
        }
    }
}

@Composable
fun ConnectedAnimatedScreen(onFinished: () -> Unit) {
    LaunchedEffect(Unit) {
        delay(2000)
        onFinished()
    }
    Column(
        modifier = Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color(0xFF020305)),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        JarvisReactor(state = "INITIALISING", modifier = Modifier.fillMaxWidth().height(240.dp))
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            "Establishing secure link with your J.A.R.V.I.S. gateway...",
            style = MaterialTheme.typography.bodyMedium,
            color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.8f),
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            modifier = Modifier.padding(horizontal = 32.dp),
        )
    }
}


@Composable
private fun StartupPermissionsScreen(
    missingItems: List<String>,
    cameraGranted: Boolean,
    notificationsGranted: Boolean,
    onRequestCameraPermission: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    onContinue: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp).background(androidx.compose.ui.graphics.Color.Transparent).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("SETUP REQUIRED", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Black)
        Spacer(Modifier.height(8.dp))
        Text("Enable the permissions the J.A.R.V.I.S. companion needs to control your phone reliably.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(20.dp))
        Card(colors = CardDefaults.cardColors(containerColor = androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.55f), contentColor = androidx.compose.ui.graphics.Color.White), border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f))) {
            Column(Modifier.padding(18.dp)) {
                Text("Missing permissions", fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))
                PermissionRow("Camera", cameraGranted)
                PermissionRow("Notifications", notificationsGranted)
            }
        }
        Spacer(Modifier.height(20.dp))
        if (!cameraGranted) {
            Button(onClick = onRequestCameraPermission, modifier = Modifier.fillMaxWidth()) { Text("Allow Camera") }
            Spacer(Modifier.height(10.dp))
        }
        if (!notificationsGranted) {
            Button(onClick = onRequestNotificationPermission, modifier = Modifier.fillMaxWidth()) { Text("Allow Notifications") }
            Spacer(Modifier.height(10.dp))
        }
        Button(
            onClick = onContinue,
            enabled = missingItems.isEmpty(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (missingItems.isEmpty()) "Continue" else "Finish Setup First")
        }
    }
}

@Composable
private fun PermissionRow(label: String, granted: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label)
        Text(if (granted) "Granted" else "Needed", color = if (granted) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
    }
}

@Composable
private fun DiscoveryScreen(
    gateway: GatewayEndpoint?,
    status: String,
    error: String?,
    onConnect: (() -> Unit)?,
    onFindGateway: () -> Unit,
    onScanQr: () -> Unit,
    onEnterIp: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp).background(androidx.compose.ui.graphics.Color.Transparent).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("J.A.R.V.I.S. CONNECT", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Black, color = androidx.compose.ui.graphics.Color.White)
        Spacer(Modifier.height(8.dp))
        Text("Connect this device to J.A.R.V.I.S.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(24.dp))
        Card(colors = CardDefaults.cardColors(containerColor = androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.55f), contentColor = androidx.compose.ui.graphics.Color.White), border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f))) {
            Column(Modifier.padding(20.dp)) {
                Text("Connection", fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text(gateway?.let { "${it.name} · ${it.host}:${it.port}" } ?: "No gateway selected")
                Spacer(Modifier.height(4.dp))
                Text(status, color = MaterialTheme.colorScheme.onSurfaceVariant)
                error?.let {
                    Spacer(Modifier.height(6.dp))
                    Text(it, color = MaterialTheme.colorScheme.error)
                }
            }
        }
        Spacer(Modifier.height(20.dp))
        if (gateway != null && onConnect != null) {
            Button(onClick = onConnect, modifier = Modifier.fillMaxWidth()) { Text("Connect") }
            Spacer(Modifier.height(12.dp))
        }
        Button(onClick = onFindGateway, modifier = Modifier.fillMaxWidth()) { Text("Find J.A.R.V.I.S.") }
        Spacer(Modifier.height(12.dp))
        FilledTonalButton(onClick = onScanQr, modifier = Modifier.fillMaxWidth()) { Text("Scan QR") }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onEnterIp, modifier = Modifier.fillMaxWidth()) { Text("Enter IP") }
    }
}

@Composable
private fun PairingPendingScreen(
    offer: PairingOffer,
    gateway: GatewayEndpoint?,
    state: ConnectionState,
    status: String,
    error: String?,
    onRequestPairing: () -> Unit,
    onCancel: () -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text("CONNECT TO J.A.R.V.I.S.?", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black)
        Spacer(Modifier.height(8.dp))
        Text("${gateway?.name ?: "JARVIS PC"}\n${gateway?.host ?: offer.host}:${offer.port}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(20.dp))
        Card(colors = CardDefaults.cardColors(containerColor = androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.55f), contentColor = androidx.compose.ui.graphics.Color.White), border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f))) {
            Column(Modifier.padding(16.dp)) {
                Text("Pair this device?")
                Text("Code ${offer.pairingCode}", fontWeight = FontWeight.Bold)
                Text("State: $state")
                Text("Status: $status")
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        }
        Spacer(Modifier.height(20.dp))
        Button(onClick = onRequestPairing, modifier = Modifier.fillMaxWidth()) { Text("Request Pairing") }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text("Cancel") }
    }
}

@Composable
private fun ConnectedScreen(
    credential: DeviceCredential,
    gateway: GatewayEndpoint?,
    state: ConnectionState,
    logs: List<String>,
    status: String,
    error: String?,
    onDisconnect: () -> Unit,
    onOpenPermissions: () -> Unit,
    onOpenChat: () -> Unit,
) {
    var showAbout by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }
    val healthy = state == ConnectionState.CONNECTED
    val reactorState = if (healthy) "READY" else reactorStateLabel(state, error != null)
    val white = androidx.compose.ui.graphics.Color.White
    val online = state == ConnectionState.CONNECTED

    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp, vertical = 18.dp)
            .background(androidx.compose.ui.graphics.Color.Transparent)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text("J.A.R.V.I.S.", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black, color = white)
                Text("Just A Rather Very Intelligent System", style = MaterialTheme.typography.labelSmall, color = white.copy(alpha = 0.55f))
            }
            Text(
                if (online) "\u25CF ONLINE" else "\u25CF $reactorState",
                fontWeight = FontWeight.Bold,
                fontSize = 12.sp,
                color = if (online) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(6.dp))

        // Live animated reactor (never a static image)
        JarvisReactor(state = reactorState, modifier = Modifier.fillMaxWidth().height(232.dp))
        Spacer(Modifier.height(4.dp))
        Text(
            if (online) "Connected to ${gateway?.name ?: "JARVIS PC"}" else status.ifBlank { reactorState },
            style = MaterialTheme.typography.labelMedium,
            color = white.copy(alpha = 0.7f),
        )
        Spacer(Modifier.height(12.dp))

        Card(
            colors = CardDefaults.cardColors(
                containerColor = androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.55f),
                contentColor = white,
            ),
            border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f)),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text("SYSTEM STATUS", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.height(8.dp))
                StatusRow("Device", credential.deviceName)
                StatusRow("Gateway", gateway?.let { "${it.name} \u00b7 ${it.host}:${it.port}" } ?: "Not selected")
                StatusRow("Connection", state.toString())
                StatusRow("Trust", "Paired (encrypted credential)")
                StatusRow("Detail", status)
                if (error != null && !healthy) {
                    Spacer(Modifier.height(6.dp))
                    Text(error, color = MaterialTheme.colorScheme.error, fontSize = 12.sp)
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "AI routing stays on your PC gateway: Ollama \u2192 OmniRoute \u2192 OpenRouter/Gemini. "
                        + "The companion never receives provider API keys.",
                    fontSize = 11.sp,
                    color = white.copy(alpha = 0.6f),
                )
            }
        }
        Spacer(Modifier.height(12.dp))

        Card(
            onClick = onOpenChat,
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.1f),
                contentColor = MaterialTheme.colorScheme.primary,
            ),
            border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.4f)),
        ) {
            Row(
                modifier = Modifier.padding(16.dp).fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text("J.A.R.V.I.S. Chat", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Text("Synchronized with your PC", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary.copy(alpha = 0.8f))
                }
                Icon(
                    imageVector = androidx.compose.material.icons.Icons.Default.Send,
                    contentDescription = "Open Chat",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
        Spacer(Modifier.height(12.dp))

        Row(Modifier.fillMaxWidth()) {
            OutlinedButton(onClick = { showAbout = true }, modifier = Modifier.weight(1f)) { Text("About") }
            Spacer(Modifier.width(10.dp))
            OutlinedButton(onClick = { showSettings = true }, modifier = Modifier.weight(1f)) { Text("Settings") }
        }
        Spacer(Modifier.height(10.dp))
        Button(onClick = onDisconnect, modifier = Modifier.fillMaxWidth()) { Text("Disconnect") }
        Spacer(Modifier.height(10.dp))
        OutlinedButton(
            onClick = onOpenPermissions,
            modifier = Modifier.fillMaxWidth(),
            colors = androidx.compose.material3.ButtonDefaults.outlinedButtonColors(
                containerColor = androidx.compose.ui.graphics.Color.Black.copy(alpha = 0.5f),
                contentColor = white,
            ),
        ) {
            Text("Permissions", color = white)
        }

        Spacer(Modifier.height(18.dp))
        Text("Recent Logs", fontWeight = FontWeight.Bold, color = white, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(6.dp))
        logs.takeLast(6).forEach { line ->
            Text(line, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 11.sp)
        }
        Spacer(Modifier.height(14.dp))
        Text("Made by Lucky", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(6.dp))
    }

    if (showAbout) {
        AlertDialog(
            onDismissRequest = { showAbout = false },
            title = { Text("J.A.R.V.I.S.") },
            text = {
                Column {
                    Text("Just A Rather Very Intelligent System", fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(10.dp))
                    Text("Private mobile companion for the J.A.R.V.I.S. desktop system.")
                    Spacer(Modifier.height(10.dp))
                    Text("Owner: Lucky")
                    Spacer(Modifier.height(4.dp))
                    Text("Made by Lucky", color = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "Private, personal use companion. The upstream LICENSE and "
                            + "TRADEMARK notices ship with this project.",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = { TextButton(onClick = { showAbout = false }) { Text("Done") } },
        )
    }

    if (showSettings) {
        AlertDialog(
            onDismissRequest = { showSettings = false },
            title = { Text("Settings & Status") },
            text = {
                Column {
                    StatusRow("Connection", state.toString())
                    StatusRow("Gateway", gateway?.let { "${it.name} \u00b7 ${it.host}:${it.port}" } ?: "Not selected")
                    StatusRow("Device", credential.deviceName)
                    StatusRow("Notifications", "Foreground service")
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "OmniRoute / Ollama / cloud providers are configured on the J.A.R.V.I.S. PC gateway. "
                            + "This app connects over the trusted device link only.",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = { TextButton(onClick = { showSettings = false }) { Text("Done") } },
            dismissButton = {
                TextButton(onClick = {
                    showSettings = false
                    onOpenPermissions()
                }) { Text("Permissions") }
            },
        )
    }
}

@Composable
private fun StatusRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
        Spacer(Modifier.width(8.dp))
        Text(value, color = androidx.compose.ui.graphics.Color.White, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun ManualConnectDialog(
    host: String,
    port: String,
    onHostChange: (String) -> Unit,
    onPortChange: (String) -> Unit,
    onDismiss: () -> Unit,
    onConnect: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Enter IP") },
        text = {
            Column {
                OutlinedTextField(value = host, onValueChange = onHostChange, label = { Text("Host") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = port, onValueChange = onPortChange, label = { Text("Port") }, singleLine = true)
            }
        },
        confirmButton = { TextButton(onClick = onConnect) { Text("Connect") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun QrScannerScreen(
    onBack: () -> Unit,
    onRequestPermission: () -> Unit,
    errorText: String?,
    onScanned: (String) -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var previewReady by remember { mutableStateOf(false) }
    var scanHandled by remember { mutableStateOf(false) }
    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }

    DisposableEffect(Unit) {
        onDispose {
            cameraExecutor.shutdown()
        }
    }

    Column(Modifier.fillMaxSize().padding(24.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = onBack) { Text("Back") }
            Text("Scan QR", fontWeight = FontWeight.Bold)
            Spacer(Modifier.size(48.dp))
        }
        Spacer(Modifier.height(16.dp))
        Card(modifier = Modifier.fillMaxWidth().height(420.dp), shape = RoundedCornerShape(20.dp)) {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { viewContext ->
                    PreviewView(viewContext).also { previewView ->
                        val cameraProviderFuture = ProcessCameraProvider.getInstance(viewContext)
                        cameraProviderFuture.addListener({
                            val cameraProvider = cameraProviderFuture.get()
                            val preview = Preview.Builder().build()
                            val imageAnalysis = ImageAnalysis.Builder()
                                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                                .build()
                            val scanner = BarcodeScanning.getClient(
                                BarcodeScannerOptions.Builder()
                                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                                    .build(),
                            )
                            imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                                val mediaImage = imageProxy.image
                                if (mediaImage != null) {
                                    val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
                                    scanner.process(image)
                                        .addOnSuccessListener { codes ->
                                            if (!scanHandled) {
                                                codes.firstOrNull()?.rawValue?.let { raw ->
                                                    scanHandled = true
                                                    onScanned(raw)
                                                }
                                            }
                                        }
                                        .addOnCompleteListener {
                                            imageProxy.close()
                                        }
                                } else {
                                    imageProxy.close()
                                }
                            }
                            cameraProvider.unbindAll()
                            cameraProvider.bindToLifecycle(
                                lifecycleOwner,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview,
                                imageAnalysis,
                            )
                            preview.setSurfaceProvider(previewView.surfaceProvider)
                            previewReady = true
                        }, ContextCompat.getMainExecutor(viewContext))
                    }
                }
            )
        }
        if (!previewReady) {
            Spacer(Modifier.height(12.dp))
            Text("Camera is preparing.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (!errorText.isNullOrBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(errorText, color = MaterialTheme.colorScheme.error)
        }
    }
}
