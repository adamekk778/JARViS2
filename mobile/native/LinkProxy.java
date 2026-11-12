package cz.adamekk.jarvis;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.List;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * 3.12 JARVIS Link on the phone – our own Tailscale. A tiny proxy on 127.0.0.1 inside the app: the app (and the
 * background link) talk plain HTTP to it, and it carries every connection to the PC encrypted (TLS) – home Wi-Fi,
 * the home router's open port, the home's IPv6 or, when nothing else works (mobile data behind any router), your own
 * relay server. The PC's certificate must match the fingerprint learnt at home, so nobody in between can read or
 * change anything – not the mobile network, not the relay.
 */
final class LinkProxy {
    private LinkProxy() {}

    static final int PORT = 47651;
    private static volatile ServerSocket server;
    private static volatile String lastGood = "";
    static volatile String lastRoute = "";

    static String base() { return "http://127.0.0.1:" + PORT; }

    static JSONObject info(Context c) {
        try {
            String s = JarvisLink.prefs(c).getString("link_info", "");
            if (s.isEmpty()) return null;
            JSONObject o = new JSONObject(s);
            return o.optBoolean("enabled") && o.optString("fp").length() == 64 ? o : null;
        } catch (Exception e) {
            return null;
        }
    }

    static boolean configured(Context c) { return info(c) != null; }

    /** Start listening on 127.0.0.1 (once per app process). */
    static synchronized boolean start(Context c) {
        if (server != null && !server.isClosed()) return true;
        if (!configured(c)) return false;
        final Context app = c.getApplicationContext();
        try {
            ServerSocket ss = new ServerSocket(PORT, 50, InetAddress.getByName("127.0.0.1"));
            server = ss;
            Thread t = new Thread(() -> {
                while (!ss.isClosed()) {
                    try {
                        Socket client = ss.accept();
                        new Thread(() -> serve(app, client), "jarvis-link-conn").start();
                    } catch (Exception e) {
                        if (ss.isClosed()) break;
                    }
                }
            }, "jarvis-link-proxy");
            t.setDaemon(true);
            t.start();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static synchronized void stop() {
        try { if (server != null) server.close(); } catch (Exception ignored) { }
        server = null;
    }

    private static void serve(Context c, Socket client) {
        Socket up = null;
        try {
            up = open(c);
            if (up == null) { client.close(); return; }
            final Socket a = client, b = up;
            Thread t = new Thread(() -> copy(a, b), "jarvis-link-up");
            t.start();
            copy(b, a);
        } catch (Exception e) {
            close(client);
            close(up);
        }
    }

    private static void copy(Socket from, Socket to) {
        try {
            InputStream in = from.getInputStream();
            OutputStream out = to.getOutputStream();
            byte[] buf = new byte[32768];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                out.flush();
            }
        } catch (Exception ignored) {
        } finally {
            close(from);
            close(to);
        }
    }

    private static void close(Socket s) {
        try { if (s != null) s.close(); } catch (Exception ignored) { }
    }

    // ---------- the ways to the PC ----------
    private static final class Route {
        final String key, host, kind;
        final int port;
        final JSONObject relay;
        Route(String kind, String host, int port, JSONObject relay) {
            this.kind = kind; this.host = host; this.port = port; this.relay = relay;
            this.key = kind + ":" + host + ":" + port;
        }
    }

    private static List<Route> routes(JSONObject info) {
        List<Route> out = new ArrayList<>();
        JSONArray d = info.optJSONArray("direct");
        if (d != null) for (int i = 0; i < d.length(); i++) {
            JSONObject o = d.optJSONObject(i);
            if (o != null && !o.optString("host").isEmpty()) out.add(new Route(o.optString("kind", "direct"), o.optString("host"), o.optInt("port"), null));
        }
        JSONObject r = info.optJSONObject("relay");
        if (r != null && !r.optString("host").isEmpty()) out.add(new Route("relay", r.optString("host"), r.optInt("port", 8443), r));
        return out;
    }

    /** One encrypted connection to the PC: the way that worked last time first, then all ways at once (direct wins). */
    static Socket open(Context c) {
        JSONObject info = info(c);
        if (info == null) return null;
        String fp = info.optString("fp");
        List<Route> all = routes(info);
        for (Route r : all) {
            if (r.key.equals(lastGood)) {
                try { return connect(r, fp, 4000); } catch (Exception e) { lastGood = ""; }
            }
        }
        return race(all, fp);
    }

    private static Socket race(List<Route> all, String fp) {
        final Object lock = new Object();
        final Socket[] won = { null };
        final int[] left = { all.size() };
        for (Route r : all) {
            new Thread(() -> {
                Socket s = null;
                try {
                    if (r.relay != null) Thread.sleep(700);          // a direct way is faster: give it a head start
                    synchronized (lock) { if (won[0] != null) return; }
                    s = connect(r, fp, r.kind.equals("lan") ? 1500 : 5000);
                } catch (Exception ignored) {
                } finally {
                    synchronized (lock) {
                        if (s != null && won[0] == null) { won[0] = s; lastGood = r.key; lastRoute = r.kind; s = null; }
                        left[0]--;
                        lock.notifyAll();
                    }
                    close(s);
                }
            }, "jarvis-link-try").start();
        }
        long end = System.currentTimeMillis() + 15000;
        synchronized (lock) {
            while (won[0] == null && left[0] > 0) {
                long w = end - System.currentTimeMillis();
                if (w <= 0) break;
                try { lock.wait(w); } catch (InterruptedException e) { break; }
            }
            Socket s = won[0];
            won[0] = s == null ? new Socket() : s;                // late winners close themselves
            return s;
        }
    }

    private static Socket connect(Route r, String fp, int timeoutMs) throws Exception {
        Socket raw = new Socket();
        try {
            raw.connect(new InetSocketAddress(r.host, r.port), timeoutMs);
            raw.setTcpNoDelay(true);
            if (r.relay != null) {
                raw.setSoTimeout(12000);
                String hello = "JRL1 " + r.relay.optString("key") + " phone " + r.relay.optString("room") + "\n";
                raw.getOutputStream().write(hello.getBytes(StandardCharsets.US_ASCII));
                raw.getOutputStream().flush();
                String line = readLine(raw.getInputStream());
                if (!"OK".equals(line)) throw new IllegalStateException("relay: " + line);
            }
            raw.setSoTimeout(10000);
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, new TrustManager[] { new Pinned(fp) }, null);
            SSLSocket s = (SSLSocket) ctx.getSocketFactory().createSocket(raw, "jarvis.link", r.port, true);
            s.setUseClientMode(true);
            s.startHandshake();                                    // fails unless it is our PC's certificate
            s.setSoTimeout(0);
            return s;
        } catch (Exception e) {
            close(raw);
            throw e;
        }
    }

    private static String readLine(InputStream in) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        int ch;
        while ((ch = in.read()) != -1 && ch != '\n') {
            b.write(ch);
            if (b.size() > 100) break;
        }
        return b.toString("US-ASCII").trim();
    }

    /** Trusts exactly one certificate: the PC's (by its SHA-256 fingerprint). */
    private static final class Pinned implements X509TrustManager {
        private final String fp;
        Pinned(String fp) { this.fp = fp.toLowerCase(); }

        @Override
        public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
            if (chain == null || chain.length == 0) throw new CertificateException("no certificate");
            try {
                byte[] h = MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
                StringBuilder sb = new StringBuilder();
                for (byte x : h) sb.append(String.format("%02x", x & 0xff));
                if (!MessageDigest.isEqual(sb.toString().getBytes(StandardCharsets.US_ASCII), fp.getBytes(StandardCharsets.US_ASCII)))
                    throw new CertificateException("not our PC");
            } catch (CertificateException e) {
                throw e;
            } catch (Exception e) {
                throw new CertificateException(e);
            }
        }

        @Override
        public void checkClientTrusted(X509Certificate[] chain, String authType) throws CertificateException {
            throw new CertificateException("server only");
        }

        @Override
        public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
    }
}
