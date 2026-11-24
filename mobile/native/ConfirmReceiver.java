package cz.adamekk.jarvis;

import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import org.json.JSONObject;

/** 3.12 "Povolit" / "Zamítnout" on the phone's notification when JARVIS asks for a confirmation while you are away. */
public class ConfirmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        String id = i.getStringExtra("id");
        boolean ok = i.getBooleanExtra("approved", false);
        int nid = i.getIntExtra("nid", 0);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null && nid != 0) nm.cancel(nid);
        final String act = i.getStringExtra("notice_action");
        if (act != null) {                       // 3.13 a button of a notice from the PC ("+5 min", "Za 10 min")
            if ("dismiss".equals(act)) return;
            String a0 = i.getStringExtra("notice_args");
            if (i.getBooleanExtra("reply", false) && android.os.Build.VERSION.SDK_INT >= 24) {   // 3.14 "Odpovědět"
                android.os.Bundle in = android.app.RemoteInput.getResultsFromIntent(i);
                CharSequence typed = in == null ? null : in.getCharSequence(JarvisLink.REPLY_KEY);
                if (typed == null || typed.toString().trim().isEmpty()) return;
                try { a0 = new JSONObject().put("text", typed.toString().trim()).toString(); } catch (Exception e) { return; }
            }
            final String args = a0;
            final PendingResult pr = goAsync();
            new Thread(() -> {
                try {
                    JSONObject b = new JSONObject();
                    b.put("action", act);
                    b.put("args", new JSONObject(args == null ? "{}" : args));
                    JarvisLink.http(c, "POST", "/api/phone/notice_action", b.toString(), 10000);
                } catch (Exception ignored) {
                } finally {
                    pr.finish();
                }
            }, "jarvis-notice").start();
            return;
        }
        if (id == null) return;
        final boolean fromWidget = i.getBooleanExtra("widget", false);
        if (fromWidget) {                       // 3.13 the widget shows the answer at once; the app sends the next one later
            JarvisWidget.prefs(c).edit().putString("biz", ok ? "Schvaluji…" : "Zamítnuto").putString("biz_id", "").apply();
            JarvisWidget.refresh(c);
        }
        final PendingResult pr = goAsync();
        new Thread(() -> {
            try {
                JSONObject b = new JSONObject();
                b.put("id", id);
                b.put("approved", ok);
                String r = JarvisLink.http(c, "POST", "/api/phone/confirm", b.toString(), 10000);
                if (fromWidget && ok) {
                    String msg = "Schváleno";
                    try { msg = new JSONObject(r).optString("message", msg); } catch (Exception ignored) { }
                    JarvisWidget.prefs(c).edit().putString("biz", "✓ " + msg).apply();
                    JarvisWidget.refresh(c);
                }
            } catch (Exception ignored) {
            } finally {
                pr.finish();
            }
        }, "jarvis-confirm").start();
    }
}
