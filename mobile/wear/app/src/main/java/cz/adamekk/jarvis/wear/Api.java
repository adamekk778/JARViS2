package cz.adamekk.jarvis.wear;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** 3.18 The watch talks to the JARVIS PC: pair with the 6-digit code, ask by voice, read the tile's status line. */
final class Api {
    private Api() { }

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("jarvis", Context.MODE_PRIVATE);
    }

    static boolean paired(Context c) {
        return !prefs(c).getString("token", "").isEmpty() && !prefs(c).getString("base", "").isEmpty();
    }

    /** "192.168.1.20:8765" or "pc.local" → "http://192.168.1.20:8765" (the PC's default port when none is given). */
    static String base(String hostPort) {
        String h = hostPort.trim().replaceAll("^https?://", "").replaceAll("/+$", "");
        if (!h.contains(":")) h = h + ":8765";
        return "http://" + h;
    }

    static String pair(Context c, String hostPort, String code) throws Exception {
        String base = base(hostPort);
        JSONObject body = new JSONObject().put("code", code.trim()).put("name", "Hodinky");
        JSONObject res = new JSONObject(request(base + "/api/watch/pair", "POST", body.toString(), null, 10000));
        String token = res.optString("token", "");
        if (token.isEmpty()) throw new IllegalStateException(res.optString("detail", "PC kód nepřijalo"));
        prefs(c).edit().putString("base", base).putString("token", token).apply();
        return "Spárováno";
    }

    static String ask(Context c, String text) throws Exception {
        JSONObject body = new JSONObject().put("text", text);
        JSONObject res = new JSONObject(request(prefs(c).getString("base", "") + "/api/watch/ask", "POST", body.toString(),
                prefs(c).getString("token", ""), 95000));
        return res.optString("answer", "Hotovo.");
    }

    static String status(Context c) throws Exception {
        JSONObject res = new JSONObject(request(prefs(c).getString("base", "") + "/api/watch/status", "GET", null,
                prefs(c).getString("token", ""), 8000));
        String line = res.optString("line", "");
        prefs(c).edit().putString("status", line).apply();
        return line;
    }

    private static String request(String url, String method, String body, String token, int timeoutMs) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(url).openConnection();
        h.setRequestMethod(method);
        h.setConnectTimeout(6000);
        h.setReadTimeout(timeoutMs);
        h.setRequestProperty("Accept", "application/json");
        if (token != null && !token.isEmpty()) h.setRequestProperty("Authorization", "Bearer " + token);
        if (body != null) {
            h.setDoOutput(true);
            h.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream o = h.getOutputStream()) { o.write(body.getBytes(StandardCharsets.UTF_8)); }
        }
        int code = h.getResponseCode();
        InputStream in = code >= 400 ? h.getErrorStream() : h.getInputStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (in != null) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            in.close();
        }
        String text = out.toString("UTF-8");
        if (code >= 400) {
            String why = text;
            try { why = new JSONObject(text).optString("detail", text); } catch (Exception ignored) { }
            throw new IllegalStateException(why.isEmpty() ? ("HTTP " + code) : why);
        }
        return text;
    }
}
