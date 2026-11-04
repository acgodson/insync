# InSync app

Flutter app: splash, then the InSync web UI in a WebView, bridged to native speech (TTS/STT),
the glasses camera stream (Meta Wearables DAT; Mock Device Kit phone camera when no glasses) and the
InSync service over WebSocket.

- `lib/home_screen.dart`: WebView, `window.insync` bridge, frame forwarding at 10 fps, debug strip.
- `lib/settings_screen.dart`: hidden settings (long-press the top bar): web UI source, service host.
- `lib/stream_screen.dart`, `lib/calibration_screen.dart`: glasses stream / Record mode and face calibration.
- `android/app/src/main/kotlin/com/insync/app/MainActivity.kt`: registration, session, camera stream,
  mock-device fallback, YUV to JPEG, EventChannel to Flutter.

## Build

Requires JDK 17 (set `org.gradle.java.home` in `~/.gradle/gradle.properties`), Android SDK 36,
and the Meta AI app on the phone with Developer Mode enabled (not needed for the mock camera).
`web/dist/index.html` is copied into `assets/web/` by Gradle before each build.

```
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```
