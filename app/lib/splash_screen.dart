import 'package:flutter/material.dart';

import 'home_screen.dart';

// Splash: 1.5 s, then the web UI
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});
  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    Future.delayed(const Duration(milliseconds: 1500), () {
      if (mounted) {
        Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const HomeScreen()));
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: Color(0xFF0F0F10),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image(image: AssetImage('assets/brand/insync-mark.png'), width: 120, height: 120),
            SizedBox(height: 12),
            Text('InSync', style: TextStyle(fontSize: 40, fontWeight: FontWeight.w600, color: Colors.white)),
            SizedBox(height: 8),
            Text('Connecting everyone.', style: TextStyle(fontSize: 16, color: Colors.white70)),
          ],
        ),
      ),
    );
  }
}
