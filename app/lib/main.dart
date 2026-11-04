import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'splash_screen.dart';

// InSync: splash -> web UI (WebView) backed by the glasses/mock camera and the service
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  runApp(MaterialApp(
    title: 'InSync',
    theme: ThemeData.dark(useMaterial3: true),
    home: const SplashScreen(),
  ));
}
