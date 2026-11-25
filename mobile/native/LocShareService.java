package cz.adamekk.jarvis;

import android.Manifest;
import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationManager;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONObject;

/**
 * 3.20 (139) Sdílení polohy na čas: started only by your tap on "Sdílet" (Android then lets it use the location in the
 * background for this one share). It sends the position every minute to the link you shared and stops by itself when
 * the time is up, when you tap "Zastavit" or when the PC ends the share.
 */
public class LocShareService extends Service {
    static final int NOTIF = 7012;
    private volatile boolean running;
    private Thread worker;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && intent.getBooleanExtra("stop", false)) { stopSelf(); return START_NOT_STICKY; }
        final String token = intent == null ? "" : intent.getStringExtra("token");
        final int minutes = intent == null ? 0 : intent.getIntExtra("minutes", 0);
        if (token == null || token.isEmpty() || minutes <= 0) { stopSelf(); return START_NOT_STICKY; }
        JarvisLink.channels(this);
        android.app.NotificationManager nm = getSystemService(android.app.NotificationManager.class);
        if (nm != null) nm.cancel(PhoneX.NOTIF_LOC_ASK);
        PendingIntent stop = PendingIntent.getService(this, NOTIF, new Intent(this, LocShareService.class).putExtra("stop", true),
                JarvisLink.piFlags());
        Notification n = JarvisLink.builder(this, JarvisLink.CH_QUIET).setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentTitle("Sdílím polohu").setContentText("Ještě " + minutes + " min – pak se to samo vypne.").setOngoing(true)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,
                        android.R.drawable.ic_menu_close_clear_cancel), "Zastavit", stop).build()).build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
        else startForeground(NOTIF, n);
        final long until = System.currentTimeMillis() + minutes * 60_000L;
        running = false;
        if (worker != null) worker.interrupt();
        running = true;
        worker = new Thread(() -> loop(token, until), "jarvis-locshare");
        worker.start();
        return START_NOT_STICKY;
    }

    private void loop(String token, long until) {
        while (running && System.currentTimeMillis() < until) {
            Location l = last();
            if (l != null) {
                try {
                    JSONObject b = new JSONObject().put("token", token).put("lat", l.getLatitude()).put("lon", l.getLongitude());
                    if (l.hasAccuracy()) b.put("acc", Math.round(l.getAccuracy()));
                    String r = JarvisLink.http(this, "POST", "/api/phone/loc", b.toString(), 15000);
                    if (new JSONObject(r).optBoolean("stop", false)) break;
                } catch (Exception ignored) { }
            }
            try { Thread.sleep(60_000); } catch (InterruptedException e) { break; }
        }
        running = false;
        stopSelf();
    }

    @SuppressWarnings("MissingPermission")
    private Location last() {
        if (!JarvisLink.has(this, Manifest.permission.ACCESS_FINE_LOCATION) && !JarvisLink.has(this, Manifest.permission.ACCESS_COARSE_LOCATION)) {
            return null;
        }
        LocationManager lm = getSystemService(LocationManager.class);
        if (lm == null) return null;
        Location best = null;
        for (String p : lm.getProviders(true)) {
            try {
                Location l = lm.getLastKnownLocation(p);
                if (l != null && (best == null || l.getTime() > best.getTime())) best = l;
            } catch (SecurityException ignored) { }
        }
        if (best == null || System.currentTimeMillis() - best.getTime() > 120_000) {
            try {      // ask for a fresh fix (the answer lands in the last known location for the next round)
                lm.requestSingleUpdate(LocationManager.GPS_PROVIDER, loc -> { }, android.os.Looper.getMainLooper());
            } catch (Exception ignored) { }
        }
        return best;
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
