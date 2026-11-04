package com.insync.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

// Record mode: writes streamed JPEG frames to <external files>/recordings/<label_>yyyyMMdd_HHmmss/
class Recorder(private val context: Context) {
  companion object {
    private const val TAG = "InSyncRecord"
    const val DURATION_MS = 10_000L
  }

  private val io = Executors.newSingleThreadExecutor()
  private val main = Handler(Looper.getMainLooper())
  @Volatile private var dir: File? = null
  private var startedAt = 0L
  private var count = 0
  private var onDone: ((String, Int) -> Unit)? = null

  val active get() = dir != null

  fun start(label: String?, onDone: (String, Int) -> Unit): String {
    val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
    val clean = label?.trim()?.replace(Regex("[^A-Za-z0-9_-]+"), "_")?.trim('_').orEmpty()
    val name = if (clean.isEmpty()) stamp else "${clean}_$stamp"
    val d = File(root(), name).apply { mkdirs() }
    dir = d; startedAt = System.currentTimeMillis(); count = 0; this.onDone = onDone
    main.postDelayed({ finish() }, DURATION_MS + 250)  // ends the clip even if frames stop arriving
    Log.i(TAG, "Recording to ${d.absolutePath}")
    return d.absolutePath
  }

  // Called on the frame thread for every streamed JPEG
  fun onFrame(jpeg: ByteArray) {
    val d = dir ?: return
    val now = System.currentTimeMillis()
    if (now - startedAt >= DURATION_MS) { finish(); return }
    count++
    io.execute { FileOutputStream(File(d, "frame_$now.jpg")).use { it.write(jpeg) } }
  }

  fun finish() {
    val d = dir ?: return
    val n = count
    val cb = onDone
    dir = null; onDone = null
    io.execute {
      Log.i(TAG, "Recorded $n frames to ${d.absolutePath}")
      cb?.invoke(d.absolutePath, n)
    }
  }

  // Zips every recording folder into <external files>/recordings_<stamp>.zip
  fun export(): String {
    val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
    val zip = File(context.getExternalFilesDir(null), "recordings_$stamp.zip")
    ZipOutputStream(FileOutputStream(zip).buffered()).use { out ->
      root().walkTopDown().filter { it.isFile }.forEach { f ->
        out.putNextEntry(ZipEntry(f.relativeTo(root()).path))
        f.inputStream().use { it.copyTo(out) }
        out.closeEntry()
      }
    }
    Log.i(TAG, "Exported ${zip.absolutePath} (${zip.length()} bytes)")
    return zip.absolutePath
  }

  private fun root() = File(context.getExternalFilesDir(null), "recordings").apply { mkdirs() }
}
