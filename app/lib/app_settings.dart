import 'package:shared_preferences/shared_preferences.dart';

// App settings: web UI source, service host, debug strip (hidden settings screen)
enum WebUiSource { dev, asset, prod }

class AppSettings {
  static const defaultHost = '10.234.119.143:8000'; // TODO(phase2): laptop IP changes per network
  static const defaultDevUrl = 'http://10.234.119.143:5173';

  WebUiSource source = WebUiSource.asset;
  String devUrl = defaultDevUrl;
  String prodUrl = '';
  String serviceHost = defaultHost;
  bool debugStrip = false;

  String get serviceUrl => 'ws://$serviceHost/ws';

  static Future<AppSettings> load() async {
    final p = await SharedPreferences.getInstance();
    final s = AppSettings();
    s.source = WebUiSource.values[p.getInt('web_ui_source') ?? WebUiSource.asset.index];
    s.devUrl = p.getString('web_ui_dev_url') ?? defaultDevUrl;
    s.prodUrl = p.getString('web_ui_prod_url') ?? '';
    s.serviceHost = p.getString('service_host') ?? defaultHost;
    s.debugStrip = p.getBool('debug_strip') ?? false;
    return s;
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    await p.setInt('web_ui_source', source.index);
    await p.setString('web_ui_dev_url', devUrl);
    await p.setString('web_ui_prod_url', prodUrl);
    await p.setString('service_host', serviceHost);
    await p.setBool('debug_strip', debugStrip);
  }
}
