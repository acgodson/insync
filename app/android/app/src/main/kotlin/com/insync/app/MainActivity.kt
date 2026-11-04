package com.insync.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.SystemClock
import android.util.Log
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.VideoFrame
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.DatResult
import com.meta.wearable.dat.core.types.Device
import com.meta.wearable.dat.core.types.DeviceSessionError
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.meta.wearable.dat.core.types.RegistrationState
import com.meta.wearable.dat.mockdevice.MockDeviceKit
import com.meta.wearable.dat.mockdevice.api.GlassesModel
import com.meta.wearable.dat.mockdevice.api.MockDeviceKitConfig
import com.meta.wearable.dat.mockdevice.api.camera.CameraFacing
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch

// Native bridge: Meta Wearables session + camera stream -> JPEG frames over an EventChannel
class MainActivity : FlutterFragmentActivity() {
  companion object {
    private const val TAG = "InSync"
    private const val FRAME_TAG = "InSyncFrame"
    private const val METHOD_CHANNEL = "insync/control"
    private const val EVENT_CHANNEL = "insync/frames"
    private const val FRAME_RATE = 24
    private val QUALITY = VideoQuality.MEDIUM
    // Latency debug (off by default)
    private const val LATENCY_DEBUG = false
    private val ANDROID_PERMISSIONS =
        arrayOf(Manifest.permission.BLUETOOTH, Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.INTERNET)
  }

  private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
  private val frameDispatcher = Executors.newSingleThreadExecutor().asCoroutineDispatcher()

  private var eventSink: EventChannel.EventSink? = null
  private var session: DeviceSession? = null
  private var camera: Camera? = null
  private val sessionJobs = mutableListOf<Job>()
  private val streamJobs = mutableListOf<Job>()
  private var initialized = false
  private var fallback = false       // true: use the Mock Device Kit (phone camera) when no glasses are found
  private var mockActive = false
  private var wantStream = false      // true between start() and stop(): a session ended by the device is retried
  private var retryJob: Job? = null
  private var deviceJob: Job? = null

  // Latency bookkeeping
  private data class Timing(val arrival: Long, val convert: Long, val sent: Long, val w: Int, val h: Int)
  private val pending = java.util.concurrent.ConcurrentHashMap<Int, Timing>()
  private var frameCount = 0

  private val androidPermissionLauncher =
      registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if (result.values.all { it }) connectAndStream() else status("Bluetooth permission denied")
      }

  private val wearablePermissionLauncher =
      registerForActivityResult(Wearables.RequestPermissionContract()) { result ->
        if (result.getOrDefault(PermissionStatus.Denied) == PermissionStatus.Granted) beginStream()
        else status("Camera permission denied in Meta AI")
      }

  private val calibration = CalibrationBridge(this)
  private val recorder = Recorder(this)

  override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
    super.configureFlutterEngine(flutterEngine)
    calibration.register(flutterEngine)
    MethodChannel(flutterEngine.dartExecutor.binaryMessenger, METHOD_CHANNEL).setMethodCallHandler { call, result ->
      when (call.method) {
        "start" -> { fallback = call.argument<Boolean>("fallback") ?: false; start(); result.success(null) }
        "source" -> { switchSource(call.argument<String>("to") == "glasses"); result.success(null) }
        "stop" -> { stop(); result.success(null) }
        "record" -> {
          if (camera == null) { result.error("not_streaming", "Start the stream first", null); return@setMethodCallHandler }
          val path = recorder.start(call.argument<String>("label")) { dir, n ->
            runOnUiThread { eventSink?.success(mapOf("recording" to "done", "path" to dir, "frames" to n)) }
          }
          result.success(path)
        }
        "export" -> scope.launch(Dispatchers.IO) { val z = recorder.export(); runOnUiThread { result.success(z) } }
        "frameDrawn" -> { onFrameDrawn(call.argument<Int>("n")!!, call.argument<Long>("received")!!, call.argument<Long>("drawn")!!); result.success(null) }
        else -> result.notImplemented()
      }
    }
    EventChannel(flutterEngine.dartExecutor.binaryMessenger, EVENT_CHANNEL).setStreamHandler(
        object : EventChannel.StreamHandler {
          override fun onListen(args: Any?, sink: EventChannel.EventSink) { eventSink = sink; handleIntent(intent) }
          override fun onCancel(args: Any?) { eventSink = null }
        })
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    handleIntent(intent)
  }

  // adb control
  private fun handleIntent(intent: Intent?) {
    intent ?: return
    when (intent.getStringExtra("cmd")) { "start" -> start(); "stop" -> stop() }
    intent.removeExtra("cmd")
  }

  private fun status(msg: String) {
    Log.i(TAG, msg)
    runOnUiThread { eventSink?.success(msg) }
  }

  private fun start() {
    wantStream = true
    val needed = if (fallback) ANDROID_PERMISSIONS + Manifest.permission.CAMERA else ANDROID_PERMISSIONS
    val missing = needed.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
    if (missing.isNotEmpty()) androidPermissionLauncher.launch(missing.toTypedArray()) else connectAndStream()
  }

  private fun connectAndStream() {
    if (!initialized) {
      Wearables.initialize(this).onFailure { e, _ -> Log.w(TAG, "initialize: ${e.description}") }
      initialized = true
      monitorDevice()
    }
    scope.launch {
      if (mockActive) { startSession(); return@launch }
      // Glasses are the default and the only automatic source (same flow as Almero). The phone
      // camera (Mock Device Kit) is used only when the user chose it from the status line.
      if (preferredSource == "phone") { startMock(); return@launch }
      fallback = false
      if (Wearables.registrationState.value != RegistrationState.REGISTERED) {
        status("Registering with Meta AI: approve in the Meta AI app")
        Wearables.startRegistration(this@MainActivity)
        Wearables.registrationState.first { it == RegistrationState.REGISTERED }
      }
      status("Registered. Starting session (wear the glasses)")
      startSession()
    }
  }

  // Glasses state (battery, charging, thermal, worn)
  @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
  private fun monitorDevice() {
    deviceJob?.cancel()
    deviceJob = scope.launch {
      AutoDeviceSelector().activeDeviceFlow()
          .flatMapLatest { id -> Wearables.devicesMetadata[id] ?: flowOf<Device?>(null) }
          .collect { device -> sendDeviceState(device) }
    }
  }

  private fun sendDeviceState(device: Device?) {
    val state = if (device == null) mapOf("device" to null) else mapOf(
        "device" to device.name,
        "battery" to device.batteryLevel,
        "charging" to device.chargingState.name,
        "thermal" to device.thermalLevel.name,
        "worn" to device.donState.name,
        "link" to device.linkState.name,
    )
    Log.i(TAG, "Device: $state")
    runOnUiThread { eventSink?.success(state) }
  }

  // Session
  private suspend fun startSession() {
    if (session != null) { status("Already running"); return }
    val attempts = 20
    repeat(attempts) { attempt ->
      val result = Wearables.createSession(AutoDeviceSelector())
      if (result.fold(onSuccess = { true }, onFailure = { _, _ -> false })) {
        status(if (mockActive) "Source: mock (phone camera)" else "Source: glasses")
        openSession(result); return
      }
      if (attempt == 0) status("Waiting for glasses (wear them, keep Meta AI connected)")
      delay(1000)
    }
    status("Glasses not found yet: still looking (wear them, keep Meta AI connected)")
    if (!mockActive) scheduleRetry()   // keep looking every 3 s until the glasses appear
  }

  // Manual source switch (tap the status line in the app): glasses <-> phone camera.
  // The Mock Device Kit cannot be cleanly undone inside a running process, so the choice is
  // saved and the app restarts itself; start() reads it on the next launch.
  private fun switchSource(glasses: Boolean) {
    getSharedPreferences("insync", MODE_PRIVATE).edit().putString("source", if (glasses) "glasses" else "phone").apply()
    stop()
    if (glasses && mockActive) {
      // The mock kit cannot be undone inside a running process: relaunch and come back on the glasses
      startActivity(Intent(this, RestartActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
      Runtime.getRuntime().exit(0)
      return
    }
    scope.launch {
      repeat(30) { if (session == null) return@repeat; delay(100) }
      clearSession()
      wantStream = true
      if (glasses) connectAndStream() else if (mockActive) startSession() else startMock()
    }
  }

  private val preferredSource get() = getSharedPreferences("insync", MODE_PRIVATE).getString("source", "auto")

  // Mock Device Kit: simulated glasses fed by the phone's front camera (no real glasses needed)
  private suspend fun startMock() {
    status("No glasses: using phone camera")
    val kit = MockDeviceKit.getInstance(this)
    if (!kit.isEnabled) kit.enable(MockDeviceKitConfig(initiallyRegistered = true, initialPermissionsGranted = true))
    val glasses = kit.pairGlasses(GlassesModel.RAYBAN_META).getOrNull()
    if (glasses == null) { status("Mock device failed"); return }
    glasses.powerOn(); glasses.unfold(); glasses.don()
    glasses.services.camera.setCameraFeed(CameraFacing.FRONT)
    mockActive = true
    monitorDevice()
    startSession()
  }

  private fun openSession(result: DatResult<DeviceSession, DeviceSessionError>) {
    result.fold(
        onSuccess = { created ->
          session = created
          sessionJobs += scope.launch {
            created.state.collect { state ->
              status("Session: $state")
              if (state == DeviceSessionState.STARTED && camera == null) ensureCameraPermission()
              if (state == DeviceSessionState.STOPPED) {
                clearSession()
                if (wantStream && !mockActive) scheduleRetry()
              }
            }
          }
          sessionJobs += scope.launch { created.errors.collect { status("Session error: ${it.description}") } }
          created.start()
        },
        onFailure = { e, _ -> status("createSession failed: ${e.description}") },
    )
  }

  private fun ensureCameraPermission() {
    scope.launch {
      Wearables.checkPermissionStatus(Permission.CAMERA).fold(
          onSuccess = { s ->
            if (s == PermissionStatus.Granted) beginStream()
            else { status("Requesting camera permission in Meta AI"); wearablePermissionLauncher.launch(Permission.CAMERA) }
          },
          onFailure = { e, _ -> status("Permission check failed: ${e.description}") },
      )
    }
  }

  private fun beginStream() {
    val current = session ?: return
    if (camera != null) return
    current.addCamera(StreamConfiguration(videoQuality = QUALITY, frameRate = FRAME_RATE)).fold(
        onSuccess = { cam ->
          camera = cam
          val stream = cam.stream
          streamJobs += scope.launch(frameDispatcher) { stream.videoStream.collect { onFrame(it) } }
          streamJobs += scope.launch { stream.state.collect { status("Stream: $it") } }
          streamJobs += scope.launch { stream.errorStream.collect { status("Stream error: ${it.description}") } }
          stream.start().onFailure { e, _ -> status("stream.start failed: ${e.description}") }
        },
        onFailure = { e, _ -> status("addCamera failed: ${e.description}") },
    )
  }

  // Frame conversion (I420 -> NV21 -> JPEG)
  private fun onFrame(frame: VideoFrame) {
    if (frame.isCompressed) return
    val arrival = System.currentTimeMillis()
    val t0 = SystemClock.elapsedRealtimeNanos()
    val w = frame.width
    val h = frame.height
    val buf = frame.buffer.duplicate().apply { rewind() }
    val ySize = w * h
    val cSize = ySize / 4
    if (buf.remaining() < ySize + 2 * cSize) { Log.w(TAG, "Unexpected frame size ${buf.remaining()} for ${w}x$h"); return }
    val nv21 = ByteArray(ySize + 2 * cSize)
    buf.get(nv21, 0, ySize)
    val u = ByteArray(cSize).also { buf.get(it) }
    val v = ByteArray(cSize).also { buf.get(it) }
    var o = ySize
    for (i in 0 until cSize) { nv21[o++] = v[i]; nv21[o++] = u[i] }
    val out = ByteArrayOutputStream()
    YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 70, out)
    val jpeg = out.toByteArray()
    recorder.onFrame(jpeg)
    val convertMs = (SystemClock.elapsedRealtimeNanos() - t0) / 1_000_000
    val n = ++frameCount
    if (n == 1) Log.i(TAG, "First frame ${w}x$h (${if (h > w) "portrait" else "landscape"}), ${buf.capacity()} bytes, quality=$QUALITY")
    runOnUiThread {
      if (!LATENCY_DEBUG) { eventSink?.success(jpeg); return@runOnUiThread }
      val sent = System.currentTimeMillis()
      pending[n] = Timing(arrival, convertMs, sent, w, h)
      if (pending.size > 200) pending.keys.filter { it < n - 200 }.forEach { pending.remove(it) }
      eventSink?.success(mapOf("n" to n, "jpeg" to jpeg, "w" to w, "h" to h,
          "arrival" to arrival, "convert" to convertMs, "sent" to sent))
    }
  }

  private fun onFrameDrawn(n: Int, received: Long, drawn: Long) {
    val t = pending.remove(n) ?: return
    Log.i(FRAME_TAG, "n=$n ${t.w}x${t.h} arrival=${t.arrival} convert=${t.convert} channel=${received - t.sent} draw=${drawn - received} total=${drawn - t.arrival}")
  }

  // Glasses dropped the session (not worn, idle, Meta AI reconnecting): try again every 3 s
  private fun scheduleRetry() {
    retryJob?.cancel()
    retryJob = scope.launch {
      delay(3000)
      if (wantStream && session == null) { status("Reconnecting to glasses"); startSession() }
    }
  }

  private fun stop() {
    wantStream = false
    retryJob?.cancel()
    recorder.finish()
    frameCount = 0
    pending.clear()
    camera?.stop()
    session?.stop()
    camera = null
  }

  private fun clearSession() {
    (sessionJobs + streamJobs).forEach { it.cancel() }
    sessionJobs.clear(); streamJobs.clear()
    camera = null
    session = null
  }

  override fun onDestroy() {
    deviceJob?.cancel()
    stop()
    super.onDestroy()
  }
}
