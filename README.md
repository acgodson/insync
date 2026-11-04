# Almero

Flutter app that streams the live camera feed from Ray-Ban Meta glasses using the
Meta Wearables Device Access Toolkit (Android only for now).

- `android/app/src/main/kotlin/com/almero/app/MainActivity.kt`: registration, session,
  camera stream, YUV to JPEG conversion, EventChannel to Flutter.
- `lib/main.dart`: single portrait screen showing the feed.

## Build

Requires JDK 17 (set `org.gradle.java.home` in `~/.gradle/gradle.properties`), Android SDK 36,
and the Meta AI app on the phone with Developer Mode enabled.

```
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```
