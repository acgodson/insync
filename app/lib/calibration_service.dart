import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

// Calibration profile storage: profile.json in app documents + "remember" flag in shared_preferences
class CalibrationService {
  static const profileVersion = 1;
  static const _rememberKey = 'calibration_remember';

  Future<File> _file() async =>
      File('${(await getApplicationDocumentsDirectory()).path}/profile.json');

  Future<Map<String, dynamic>?> load() async {
    final f = await _file();
    if (!await f.exists()) return null;
    try {
      final data = jsonDecode(await f.readAsString()) as Map<String, dynamic>;
      return data['version'] == profileVersion ? data : null;
    } catch (_) {
      return null;
    }
  }

  Future<void> save(Map<String, dynamic> profile, {required bool remember}) async {
    profile['version'] = profileVersion;
    await (await _file()).writeAsString(jsonEncode(profile));
    await setRemember(remember);
  }

  Future<void> clear() async {
    final f = await _file();
    if (await f.exists()) await f.delete();
    await setRemember(false);
  }

  Future<bool> remember() async =>
      (await SharedPreferences.getInstance()).getBool(_rememberKey) ?? true;

  Future<void> setRemember(bool value) async =>
      (await SharedPreferences.getInstance()).setBool(_rememberKey, value);
}
