import 'package:shared_preferences/shared_preferences.dart';

// App settings: web UI source, service host, debug strip (hidden settings screen)
enum WebUiSource { dev, asset, prod }

class AppSettings {
  static const defaultHost = 'https://insync.13-216-97-225.sslip.io'; // AWS; use http://<laptop-ip>:8000 for local
  static const defaultDevUrl = 'http://10.234.119.143:5173';

  WebUiSource source = WebUiSource.asset;
  String devUrl = defaultDevUrl;
  String prodUrl = '$defaultHost/app';
  String serviceHost = defaultHost;
  bool debugStrip = false;

  // serviceHost is a base URL (https://host or http://ip:port); older saved values were bare ip:port
  String get baseUrl => serviceHost.startsWith('http') ? serviceHost : 'http://$serviceHost';
  String get wsBase => baseUrl.replaceFirst('http', 'ws');

  static Future<AppSettings> load() async {
    final p = await SharedPreferences.getInstance();
    final s = AppSettings();
    s.source = WebUiSource.values[p.getInt('web_ui_source') ?? WebUiSource.asset.index];
    s.devUrl = p.getString('web_ui_dev_url') ?? defaultDevUrl;
    s.prodUrl = p.getString('web_ui_prod_url') ?? '$defaultHost/app';
    s.serviceHost = p.getString('service_host') ?? defaultHost;
    if (s.serviceHost == '10.234.119.143:8000') s.serviceHost = defaultHost; // old laptop default -> AWS
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
