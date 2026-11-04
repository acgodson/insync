package com.insync.app

import android.app.Activity
import android.content.Intent
import android.os.Bundle

// Relaunch trampoline (runs in its own process): reopens MainActivity after the main process exits
class RestartActivity : Activity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
    finish()
    Runtime.getRuntime().exit(0)
  }
}
