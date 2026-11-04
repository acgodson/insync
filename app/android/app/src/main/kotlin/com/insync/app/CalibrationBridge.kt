package com.insync.app

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.os.SystemClock
import android.util.Log
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

// Calibration bridge: front camera -> MediaPipe Face Landmarker -> Flutter
//
// MethodChannel "insync/calibration":
//   start            opens the front camera (asks for CAMERA permission first)
//   stop             closes the camera and releases the landmarker
//   edges            returns the face tessellation as a flat [a0,b0,a1,b1,...] Int list
// EventChannel "insync/calibration_frames", one Map per analysed frame:
//   jpeg (bytes, upright, not mirrored), w, h, ts (ms),
//   brightness (0-255 mean luma),
//   landmarks (478*3 floats, normalised x,y,z) or absent when no face,
//   matrix (16 floats, column-major facial transformation) or absent.
// Frames are never written to disk.
class CalibrationBridge(private val activity: FlutterFragmentActivity) {
  companion object {
    private const val TAG = "InSyncCalib"
    private const val METHOD_CHANNEL = "insync/calibration"
    private const val EVENT_CHANNEL = "insync/calibration_frames"
    private const val JPEG_QUALITY = 60
  }

  private var eventSink: EventChannel.EventSink? = null
  private var landmarker: FaceLandmarker? = null
  private var cameraProvider: ProcessCameraProvider? = null
  private var analysisExecutor: ExecutorService? = null
  private val permissionLauncher: ActivityResultLauncher<String> =
      activity.registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) openCamera() else eventSink?.success(mapOf("error" to "Camera permission denied"))
      }

  fun register(engine: FlutterEngine) {
    MethodChannel(engine.dartExecutor.binaryMessenger, METHOD_CHANNEL).setMethodCallHandler { call, result ->
      when (call.method) {
        "start" -> { start(); result.success(null) }
        "stop" -> { stop(); result.success(null) }
        "edges" -> result.success(FaceLandmarker.FACE_LANDMARKS_TESSELATION.flatMap { listOf(it.start(), it.end()) })
        else -> result.notImplemented()
      }
    }
    EventChannel(engine.dartExecutor.binaryMessenger, EVENT_CHANNEL).setStreamHandler(
        object : EventChannel.StreamHandler {
          override fun onListen(args: Any?, sink: EventChannel.EventSink) { eventSink = sink }
          override fun onCancel(args: Any?) { eventSink = null }
        })
  }

  // Camera
  private fun start() {
    if (ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) openCamera()
    else permissionLauncher.launch(Manifest.permission.CAMERA)
  }

  private fun openCamera() {
    if (cameraProvider != null) return
    ensureLandmarker()
    val future = ProcessCameraProvider.getInstance(activity)
    future.addListener({
      val provider = future.get()
      cameraProvider = provider
      val analysis = ImageAnalysis.Builder()
          .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
          .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
          .build()
      analysisExecutor = Executors.newSingleThreadExecutor().also { ex -> analysis.setAnalyzer(ex) { analyse(it) } }
      provider.unbindAll()
      provider.bindToLifecycle(activity, CameraSelector.DEFAULT_FRONT_CAMERA, analysis)
      Log.i(TAG, "Front camera started")
    }, ContextCompat.getMainExecutor(activity))
  }

  private fun stop() {
    cameraProvider?.unbindAll()
    cameraProvider = null
    analysisExecutor?.shutdown()
    analysisExecutor = null
    landmarker?.close()
    landmarker = null
    Log.i(TAG, "Camera stopped")
  }

  private fun ensureLandmarker() {
    if (landmarker != null) return
    val options = FaceLandmarker.FaceLandmarkerOptions.builder()
        .setBaseOptions(BaseOptions.builder().setModelAssetPath("face_landmarker.task").build())
        .setRunningMode(RunningMode.VIDEO)
        .setNumFaces(1)
        .setOutputFacialTransformationMatrixes(true)
        .build()
    landmarker = FaceLandmarker.createFromOptions(activity, options)
  }

  // Per-frame analysis (camera thread)
  private fun analyse(image: ImageProxy) {
    try {
      val lm = landmarker ?: return
      val bitmap = upright(image)
      val ts = SystemClock.uptimeMillis()
      val result = lm.detectForVideo(BitmapImageBuilder(bitmap).build(), ts)
      val out = ByteArrayOutputStream()
      bitmap.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
      val payload = mutableMapOf<String, Any>(
          "jpeg" to out.toByteArray(), "w" to bitmap.width, "h" to bitmap.height, "ts" to ts,
          "brightness" to brightness(bitmap))
      val faces = result.faceLandmarks()
      if (faces.isNotEmpty()) {
        val pts = faces[0]
        val arr = FloatArray(pts.size * 3)
        pts.forEachIndexed { i, p -> arr[i * 3] = p.x(); arr[i * 3 + 1] = p.y(); arr[i * 3 + 2] = p.z() }
        payload["landmarks"] = arr
        result.facialTransformationMatrixes().orElse(null)?.firstOrNull()?.let { payload["matrix"] = it }
      }
      activity.runOnUiThread { eventSink?.success(payload) }
    } catch (e: Exception) {
      Log.w(TAG, "analyse failed", e)
    } finally {
      image.close()
    }
  }

  private fun upright(image: ImageProxy): Bitmap {
    val bmp = image.toBitmap()
    val rotation = image.imageInfo.rotationDegrees
    if (rotation == 0) return bmp
    val m = Matrix().apply { postRotate(rotation.toFloat()) }
    return Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, true)
  }

  private fun brightness(bmp: Bitmap): Int {
    var sum = 0L; var n = 0
    val step = 16
    var y = 0
    while (y < bmp.height) {
      var x = 0
      while (x < bmp.width) {
        val c = bmp.getPixel(x, y)
        sum += ((c shr 16 and 0xff) * 299 + (c shr 8 and 0xff) * 587 + (c and 0xff) * 114) / 1000
        n++; x += step
      }
      y += step
    }
    return if (n == 0) 0 else (sum / n).toInt()
  }
}
