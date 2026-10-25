package cz.adamekk.jarvis;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Keeps the phone reachable for JARVIS while the app is closed: a visible "Spojení s PC" notification and a long-poll
 * to the PC. Commands (ring, dial, SMS, WhatsApp) are carried out here. You switch it off in the app (Více → Telefon).
 */
public class LinkService extends Service {
    static volatile boolean running;
    private Thread worker;

    static void start(Context c) {
        Intent i = new Intent(c, LinkService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
        else c.startService(i);
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, LinkService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        JarvisLink.channels(this);
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), JarvisLink.piFlags());
        Notification n = JarvisLink.builder(this, JarvisLink.CH_LINK).setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
                .setContentTitle("JARVIS je připojený k PC").setContentText("Může ti zavolat a poslat zprávu. Vypneš v aplikaci → Více.")
                .setContentIntent(open).setOngoing(true).build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(JarvisLink.NOTIF_LINK, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(JarvisLink.NOTIF_LINK, n);
        if (!running) {
            running = true;
            worker = new Thread(this::loop, "jarvis-link");
            worker.start();
        }
        return START_STICKY;
    }

    private void loop() {
        long backoff = 3000;
        while (running && JarvisLink.enabled(this)) {
            try {
                JSONArray cmds = JarvisLink.poll(this);
                backoff = 3000;
                for (int i = 0; cmds != null && i < cmds.length(); i++) {
                    JSONObject cmd = cmds.getJSONObject(i);
                    String state = JarvisLink.run(this, cmd, false);
                    if (!"ringing".equals(state)) JarvisLink.ack(this, cmd.optString("id"), state, "");
                }
            } catch (Exception e) {
                try { Thread.sleep(backoff); } catch (InterruptedException ie) { return; }
                backoff = Math.min(60000, backoff * 2);
            }
        }
        running = false;
        stopSelf();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (worker != null) worker.interrupt();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
