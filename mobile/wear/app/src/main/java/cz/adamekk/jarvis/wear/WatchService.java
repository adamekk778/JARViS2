package cz.adamekk.jarvis.wear;

import android.Manifest;
import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 3.20 Spojení hodinek s PC (switched on in the app, it shows a notification while it runs):
 * - (141, 144, 146) the PC's notices as vibration codes; (145) a timer counted on the wrist; (154) the silent alarm;
 *   (157) "find the watch"; (149) the route steps for the navigation screen
 * - (150) fall detection: a free fall, a hard hit, then stillness → "Jsi v pořádku?" for 30 s → the PC's emergency
 * - (143, 152) the heart rate every 2 minutes (only with the sensor permission and the switch on)
 */
public class WatchService extends Service implements SensorEventListener {
    static final String CH = "jarvis_watch";
    static final String CH_ALERT = "jarvis_watch_alert";
    static final int NOTIF = 4101;
    static volatile boolean running;
    private Thread worker;
    private SensorManager sm;
    private long freeFallAt;
    private long lastFall;
    private final JSONArray hrBuf = new JSONArray();
    private long lastHr;

    static void start(Context c) {
        Intent i = new Intent(c, WatchService.class);
        c.startForegroundService(i);
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, WatchService.class));
    }

    static void channel(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null && nm.getNotificationChannel(CH) == null) {
            nm.createNotificationChannel(new NotificationChannel(CH, "Spojení s PC", NotificationManager.IMPORTANCE_LOW));
        }
        if (nm != null && nm.getNotificationChannel(CH_ALERT) == null) {
            NotificationChannel a = new NotificationChannel(CH_ALERT, "Budík, minutka, pád", NotificationManager.IMPORTANCE_HIGH);
            a.enableVibration(false);                          // the screen itself vibrates its own pattern
            nm.createNotificationChannel(a);
        }
    }

    private boolean has(String perm) {
        return checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        channel(this);
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, CH).setSmallIcon(R.drawable.ic_jarvis).setContentTitle("JARVIS")
                .setContentText("Spojeno s PC").setContentIntent(open).setOngoing(true).build();
        boolean hr = Api.prefs(this).getBoolean("hr", false) && has(Manifest.permission.BODY_SENSORS);
        int type = ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC | (hr ? ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH : 0);
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF, n, type);
        else startForeground(NOTIF, n);
        sensors(hr);
        if (!running) {
            running = true;
            worker = new Thread(this::loop, "jarvis-watch-link");
            worker.start();
        }
        return START_STICKY;
    }

    private void sensors(boolean hr) {
        if (sm == null) sm = getSystemService(SensorManager.class);
        if (sm == null) return;
        sm.unregisterListener(this);
        if (Api.prefs(this).getBoolean("fall", false)) {
            Sensor acc = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
            if (acc != null) sm.registerListener(this, acc, SensorManager.SENSOR_DELAY_GAME);
        }
        if (hr) {
            Sensor h = sm.getDefaultSensor(Sensor.TYPE_HEART_RATE);
            if (h != null) sm.registerListener(this, h, SensorManager.SENSOR_DELAY_NORMAL);
        }
    }

    private void loop() {
        long backoff = 3000;
        while (running && Api.paired(this)) {
            try {
                JSONArray evs = Api.events(this);
                backoff = 3000;
                for (int k = 0; k < evs.length(); k++) handle(evs.getJSONObject(k));
                flushHr(false);
            } catch (Exception e) {
                try { Thread.sleep(backoff); } catch (InterruptedException ie) { return; }
                backoff = Math.min(60000, backoff * 2);
            }
        }
        running = false;
        stopSelf();
    }

    private void handle(JSONObject e) {
        String kind = e.optString("kind");
        long[] p = Buzz.pattern(e.optJSONArray("pattern"));
        switch (kind) {
            case "timer": {                                 // (145) counted on the wrist: the vibration comes even offline
                long until = (long) (e.optDouble("until", 0) * 1000);
                if (until > System.currentTimeMillis()) alarmAt(until, e.optString("label", "Časovač"));
                Api.prefs(this).edit().putLong("timer_until", until).putString("timer_label", e.optString("label")).apply();
                break;
            }
            case "alarm":                                   // (154) the silent alarm: vibrates until you tap
            case "find":                                    // (157) "find the watch"
                fullScreen(this, kind, e.optString("text"));
                break;
            case "route":                                   // (149) the steps for the navigation screen
                Api.prefs(this).edit().putString("route", String.valueOf(e.optJSONArray("steps"))).putString("route_to", e.optString("text")).apply();
                Buzz.play(this, p, false);
                break;
            default:                                        // (141) a notice: its code + the text in a notification
                Buzz.play(this, p, false);
                show(e.optString("text"));
        }
    }

    private void show(String text) {
        if (text == null || text.isEmpty()) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        Notification n = new Notification.Builder(this, CH).setSmallIcon(R.drawable.ic_jarvis).setContentTitle("JARVIS")
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setAutoCancel(true).build();
        nm.notify((int) (System.currentTimeMillis() & 0xffff), n);
    }

    private void alarmAt(long when, String label) {
        AlarmManager am = getSystemService(AlarmManager.class);
        Intent i = new Intent(this, AlertActivity.class).putExtra("kind", "timer").putExtra("text", label)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pi = PendingIntent.getActivity(this, 4201, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        try {
            if (am == null) throw new SecurityException("no alarm manager");
            am.setAlarmClock(new AlarmManager.AlarmClockInfo(when, pi), pi);
        } catch (SecurityException e) {        // exact alarms not allowed: count it here while the link runs
            new android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(() -> fullScreen(this, "timer", label),
                    Math.max(0, when - System.currentTimeMillis()));
        }
    }

    /** From the background Android opens a screen only through a full-screen notification (an alarm's way). */
    static void fullScreen(Context c, String kind, String text) {
        channel(c);
        Intent i = new Intent(c, AlertActivity.class).putExtra("kind", kind).putExtra("text", text == null ? "" : text)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pi = PendingIntent.getActivity(c, kind.hashCode() & 0xffff, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        String title = "fall".equals(kind) ? "Jsi v pořádku?" : "find".equals(kind) ? "Tady jsem!" : "timer".equals(kind) ? "Čas vypršel" : "Budík";
        Notification n = new Notification.Builder(c, CH_ALERT).setSmallIcon(R.drawable.ic_jarvis).setContentTitle(title)
                .setContentText(text == null ? "" : text).setCategory(Notification.CATEGORY_ALARM).setFullScreenIntent(pi, true)
                .setContentIntent(pi).setAutoCancel(true).build();
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(4300 + (kind.hashCode() & 0xff), n);
        try { c.startActivity(i); } catch (Exception ignored) { }     // allowed when the app is in front
    }

    // ---------- (150) fall, (143) heart rate
    @Override
    public void onSensorChanged(SensorEvent ev) {
        long now = System.currentTimeMillis();
        if (ev.sensor.getType() == Sensor.TYPE_ACCELEROMETER) {
            float x = ev.values[0], y = ev.values[1], z = ev.values[2];
            double g = Math.sqrt(x * x + y * y + z * z);
            if (g < 3.0) {                                  // free fall (well under 1 g)
                if (freeFallAt == 0) freeFallAt = now;
            } else if (g > 25.0 && freeFallAt != 0 && now - freeFallAt > 60 && now - freeFallAt < 1200 && now - lastFall > 60_000) {
                lastFall = now;                             // a hard hit right after the fall
                freeFallAt = 0;
                fullScreen(this, "fall", "");
            } else if (freeFallAt != 0 && now - freeFallAt > 1500) {
                freeFallAt = 0;
            }
        } else if (ev.sensor.getType() == Sensor.TYPE_HEART_RATE && ev.values.length > 0) {
            int bpm = Math.round(ev.values[0]);
            if (bpm >= 30 && bpm <= 230 && now - lastHr >= 120_000) {
                lastHr = now;
                synchronized (hrBuf) {
                    try { hrBuf.put(new JSONObject().put("bpm", bpm).put("ts", now)); } catch (Exception ignored) { }
                }
            }
        }
    }

    private void flushHr(boolean force) {
        JSONArray send;
        synchronized (hrBuf) {
            if (hrBuf.length() == 0 || (!force && hrBuf.length() < 5)) return;
            send = new JSONArray();
            for (int k = 0; k < hrBuf.length(); k++) send.put(hrBuf.opt(k));
            while (hrBuf.length() > 0) hrBuf.remove(0);
        }
        try { Api.post(this, "/api/watch/hr", new JSONObject().put("samples", send), 10000); } catch (Exception ignored) { }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    @Override
    public void onDestroy() {
        running = false;
        if (sm != null) sm.unregisterListener(this);
        if (worker != null) worker.interrupt();
        new Thread(() -> flushHr(true)).start();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
