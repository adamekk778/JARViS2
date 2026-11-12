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
        if (id == null) return;
        final PendingResult pr = goAsync();
        new Thread(() -> {
            try {
                JSONObject b = new JSONObject();
                b.put("id", id);
                b.put("approved", ok);
                JarvisLink.http(c, "POST", "/api/phone/confirm", b.toString(), 10000);
            } catch (Exception ignored) {
            } finally {
                pr.finish();
            }
        }, "jarvis-confirm").start();
    }
}
