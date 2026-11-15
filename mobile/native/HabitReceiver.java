package cz.adamekk.jarvis;

import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import org.json.JSONObject;

/** 3.12 "✓ Voda" in the evening habits notification: that habit is ticked for today on the PC, the notification goes. */
public class HabitReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        int id = i.getIntExtra("id", 0);
        int nid = i.getIntExtra("nid", 0);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null && nid != 0) nm.cancel(nid);
        if (id <= 0) return;
        final PendingResult pr = goAsync();
        new Thread(() -> {
            try {
                JSONObject b = new JSONObject();
                b.put("id", id);
                JarvisLink.http(c, "POST", "/api/phone/habit", b.toString(), 10000);
            } catch (Exception ignored) {
            } finally {
                pr.finish();
            }
        }, "jarvis-habit").start();
    }
}
