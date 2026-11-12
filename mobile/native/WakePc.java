package cz.adamekk.jarvis;

import android.content.Context;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/**
 * 3.12 Zapnout PC z telefonu: the Wake-on-LAN "magic packet" for your PC – sent on the home network (broadcast),
 * straight to the home router (it forwards UDP 9 to the PC) and through your JARVIS relay, which knows where home
 * is. The packet only wakes that one network card; it carries nothing else. The PC must allow it (Settings on the PC).
 */
final class WakePc {
    private WakePc() {}

    static boolean known(Context c) { return !mac(c).isEmpty(); }

    static String mac(Context c) {
        try {
            return new JSONObject(JarvisLink.prefs(c).getString("wake_info", "{}")).optString("mac", "").toLowerCase();
        } catch (Exception e) {
            return "";
        }
    }

    static byte[] packet(String mac) {
        byte[] m = new byte[6];
        for (int i = 0; i < 6; i++) m[i] = (byte) Integer.parseInt(mac.substring(i * 2, i * 2 + 2), 16);
        byte[] p = new byte[6 + 16 * 6];
        for (int i = 0; i < 6; i++) p[i] = (byte) 0xff;
        for (int i = 0; i < 16; i++) System.arraycopy(m, 0, p, 6 + i * 6, 6);
        return p;
    }

    /** Sends the packet every way it can; returns what went out ("lan", "router", "relay") or why not. */
    static JSONObject send(Context c) {
        JSONObject r = new JSONObject();
        String mac = mac(c);
        try {
            if (!mac.matches("[0-9a-f]{12}")) { r.put("ok", false); r.put("error", "PC ještě neposlalo svou adresu – otevři aplikaci doma, když PC běží."); return r; }
            byte[] p = packet(mac);
            JSONObject info = new JSONObject(JarvisLink.prefs(c).getString("wake_info", "{}"));
            StringBuilder via = new StringBuilder();
            // 1) at home: everyone on the network hears it, the PC's card wakes up
            if (udp(p, "255.255.255.255") | udp(p, info.optString("broadcast", ""))) via.append("lan ");
            // 2) the home router's public address (UPnP forwards UDP 9 to the PC)
            if (!info.optString("public", "").isEmpty() && udp(p, info.optString("public", ""))) via.append("router ");
            // 3) the relay: it knows the home's address even when it changed
            String relay = relayWake(c, mac);
            if ("OK".equals(relay)) via.append("relay");
            r.put("ok", via.length() > 0);
            r.put("via", via.toString().trim());
            if (!relay.isEmpty() && !"OK".equals(relay)) r.put("relay", relay);
        } catch (Exception e) {
            try { r.put("ok", false); r.put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) { }
        }
        return r;
    }

    private static boolean udp(byte[] p, String host) {
        if (host == null || host.isEmpty()) return false;
        try (DatagramSocket s = new DatagramSocket()) {
            s.setBroadcast(true);
            InetAddress a = InetAddress.getByName(host);
            s.send(new DatagramPacket(p, p.length, a, 9));
            s.send(new DatagramPacket(p, p.length, a, 7));
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** "OK", "" (no relay set up) or the relay's answer ("ERR nohome" = the PC never reached it yet). */
    private static String relayWake(Context c, String mac) {
        try {
            JSONObject link = new JSONObject(JarvisLink.prefs(c).getString("link_info", "{}"));
            JSONObject relay = link.optJSONObject("relay");
            if (relay == null || relay.optString("host").isEmpty()) return "";
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress(relay.getString("host"), relay.optInt("port", 8443)), 6000);
                s.setSoTimeout(6000);
                OutputStream os = s.getOutputStream();
                os.write(("JRL1 " + relay.getString("key") + " wake " + relay.getString("room") + " " + mac + "\n").getBytes(StandardCharsets.US_ASCII));
                os.flush();
                String line = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.US_ASCII)).readLine();
                return line == null ? "ERR closed" : line.trim();
            }
        } catch (Exception e) {
            return "ERR " + e.getClass().getSimpleName();
        }
    }
}
