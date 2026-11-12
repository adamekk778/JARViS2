package cz.adamekk.jarvis;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationManager;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.AssetFileDescriptor;
import android.database.ContentObserver;
import android.database.Cursor;
import android.net.ConnectivityManager;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.MediaStore;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

/**
 * 3.12 Záloha fotek z telefonu: new photos (and videos) go to your own PC by themselves – into
 * Obrázky\JARVIS Telefon\YYYY-MM. Switched on in the app (Více → Telefon); by default only on Wi-Fi.
 * It runs inside the visible "JARVIS je připojený k PC" service, shows its own progress notification while sending,
 * and only reads photos (never deletes or changes anything in the phone). Works at home and over JARVIS Link.
 */
final class PhotoBackup {
    private PhotoBackup() {}

    static final int NOTIF = 7020;
    private static final long PERIOD_MS = 30 * 60 * 1000L;
    private static volatile boolean running;
    private static volatile boolean stopAsked;
    private static Handler handler;
    private static ContentObserver observer;
    private static Context app;

    // ---------- settings ----------
    static SharedPreferences prefs(Context c) { return JarvisLink.prefs(c); }
    static boolean enabled(Context c) { return prefs(c).getBoolean("backup", false); }
    static boolean wifiOnly(Context c) { return prefs(c).getBoolean("backup_wifi", true); }
    static boolean chargingOnly(Context c) { return prefs(c).getBoolean("backup_charging", false); }
    static boolean videos(Context c) { return prefs(c).getBoolean("backup_videos", true); }
    static boolean isRunning() { return running; }

    static String[] permissions(Context c) {
        if (Build.VERSION.SDK_INT >= 33) {
            return videos(c) ? new String[] { Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO }
                    : new String[] { Manifest.permission.READ_MEDIA_IMAGES };
        }
        return new String[] { Manifest.permission.READ_EXTERNAL_STORAGE };
    }

    static boolean canRead(Context c) {
        for (String p : permissions(c)) if (!JarvisLink.has(c, p)) return false;
        return true;
    }

    /** Switched on: "all" = also the photos already in the phone, otherwise only the ones taken from now on. */
    static void setEnabled(Context c, boolean on, boolean all) {
        SharedPreferences.Editor e = prefs(c).edit();
        e.putBoolean("backup", on);
        if (on && !prefs(c).contains("backup_last_img")) {
            e.putLong("backup_last_img", all ? 0 : maxId(c, MediaStore.Images.Media.EXTERNAL_CONTENT_URI));
            e.putLong("backup_last_vid", all ? 0 : maxId(c, MediaStore.Video.Media.EXTERNAL_CONTENT_URI));
        } else if (on && all) {                    // switched on again with "everything": start over (what the PC has is skipped)
            e.putLong("backup_last_img", 0);
            e.putLong("backup_last_vid", 0);
        }
        e.apply();
        if (!on) stopAsked = true;
    }

    // ---------- when ----------
    /** Called by the background service: watch for new photos + a check every 30 minutes. */
    static synchronized void start(Context c) {
        if (handler != null) return;
        app = c.getApplicationContext();
        handler = new Handler(Looper.getMainLooper());
        observer = new ContentObserver(handler) {
            @Override
            public void onChange(boolean selfChange) {           // a new photo: wait a moment (bursts, still being written)
                handler.removeCallbacks(soon);
                handler.postDelayed(soon, 90 * 1000L);
            }
        };
        try {
            ContentResolver cr = app.getContentResolver();
            cr.registerContentObserver(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true, observer);
            cr.registerContentObserver(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, true, observer);
        } catch (Exception ignored) { }
        handler.postDelayed(tick, 20 * 1000L);
    }

    static synchronized void stop() {
        if (handler == null) return;
        handler.removeCallbacks(soon);
        handler.removeCallbacks(tick);
        try { app.getContentResolver().unregisterContentObserver(observer); } catch (Exception ignored) { }
        handler = null;
        observer = null;
        stopAsked = true;
    }

    private static final Runnable soon = () -> { if (app != null) runNow(app, false); };
    private static final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (app != null) runNow(app, false);
            Handler h = handler;
            if (h != null) h.postDelayed(this, PERIOD_MS);
        }
    };

    /** Why it cannot run now ("" = it can). force = "Zálohovat teď" (ignores the charger, never the Wi-Fi choice). */
    static String blocked(Context c, boolean force) {
        if (!enabled(c)) return "vypnuto";
        if (JarvisLink.base(c).isEmpty()) return "telefon není spárovaný s PC";
        if (!canRead(c)) return "chybí povolení k fotkám";
        if (wifiOnly(c) && metered(c)) return "čeká na Wi-Fi";
        if (!force && chargingOnly(c) && !charging(c)) return "čeká na nabíječku";
        return "";
    }

    static boolean metered(Context c) {
        ConnectivityManager cm = (ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE);
        return cm == null || cm.getActiveNetwork() == null || cm.isActiveNetworkMetered();
    }

    static boolean charging(Context c) {
        BatteryManager bm = (BatteryManager) c.getSystemService(Context.BATTERY_SERVICE);
        return bm != null && bm.isCharging();
    }

    static synchronized boolean runNow(Context c, boolean force) {
        final Context ctx = c.getApplicationContext();
        String why = blocked(ctx, force);
        prefs(ctx).edit().putString("backup_state", why).apply();
        if (running || !why.isEmpty()) return false;
        running = true;
        stopAsked = false;
        new Thread(() -> {
            try { round(ctx, force); } finally { running = false; }
        }, "jarvis-photo-backup").start();
        return true;
    }

    // ---------- what ----------
    private static long maxId(Context c, Uri coll) {
        try (Cursor cur = c.getContentResolver().query(coll, new String[] { "_id" }, null, null, "_id DESC")) {
            if (cur != null && cur.moveToFirst()) return cur.getLong(0);
        } catch (Exception ignored) { }
        return 0;
    }

    /** How many photos/videos still wait for the PC. */
    static int pending(Context c) {
        if (!canRead(c)) return -1;
        int n = count(c, MediaStore.Images.Media.EXTERNAL_CONTENT_URI, prefs(c).getLong("backup_last_img", 0));
        if (videos(c)) n += count(c, MediaStore.Video.Media.EXTERNAL_CONTENT_URI, prefs(c).getLong("backup_last_vid", 0));
        return n;
    }

    private static String where() { return Build.VERSION.SDK_INT >= 29 ? "_id > ? AND is_pending = 0" : "_id > ?"; }

    private static int count(Context c, Uri coll, long after) {
        try (Cursor cur = c.getContentResolver().query(coll, new String[] { "_id" }, where(), new String[] { String.valueOf(after) }, null)) {
            return cur == null ? 0 : cur.getCount();
        } catch (Exception e) {
            return 0;
        }
    }

    private static final class Item {
        long id; String name; long size; long taken; Uri uri;
    }

    private static void round(Context ctx, boolean force) {
        PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
        PowerManager.WakeLock wl = pm == null ? null : pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:photobackup");
        if (wl != null) wl.acquire(60 * 60 * 1000L);
        int sent = 0;
        String state = "";
        try {
            int total = pending(ctx), done = 0;
            Uri[] colls = videos(ctx) ? new Uri[] { MediaStore.Images.Media.EXTERNAL_CONTENT_URI, MediaStore.Video.Media.EXTERNAL_CONTENT_URI }
                    : new Uri[] { MediaStore.Images.Media.EXTERNAL_CONTENT_URI };
            for (Uri coll : colls) {
                String key = coll.equals(MediaStore.Images.Media.EXTERNAL_CONTENT_URI) ? "backup_last_img" : "backup_last_vid";
                while (true) {
                    Item[] batch = next(ctx, coll, prefs(ctx).getLong(key, 0), 50);
                    if (batch.length == 0) break;
                    boolean[] have = have(ctx, batch);
                    for (int i = 0; i < batch.length; i++) {
                        String why = blocked(ctx, force);
                        if (stopAsked || !why.isEmpty()) { state = stopAsked ? "" : why; return; }
                        Item it = batch[i];
                        progress(ctx, done, total, it.name);
                        if (!have[i]) {
                            upload(ctx, it);
                            sent++;
                        }
                        done++;
                        prefs(ctx).edit().putLong(key, it.id).putInt("backup_total", prefs(ctx).getInt("backup_total", 0) + (have[i] ? 0 : 1)).apply();
                    }
                }
            }
        } catch (Exception e) {
            state = "nepovedlo se: " + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
        } finally {
            if (sent > 0) {
                try { JarvisLink.http(ctx, "POST", "/api/phone/backup/done", "{\"sent\":" + sent + "}", 15000); } catch (Exception ignored) { }
            }
            prefs(ctx).edit().putString("backup_state", state).putLong("backup_last_run", System.currentTimeMillis()).apply();
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.cancel(NOTIF);
            if (wl != null && wl.isHeld()) wl.release();
        }
    }

    private static Item[] next(Context c, Uri coll, long after, int limit) {
        String[] proj = { "_id", "_display_name", "_size", "datetaken", "date_added" };
        java.util.ArrayList<Item> out = new java.util.ArrayList<>();
        try (Cursor cur = c.getContentResolver().query(coll, proj, where(), new String[] { String.valueOf(after) }, "_id ASC")) {
            while (cur != null && cur.moveToNext() && out.size() < limit) {
                Item it = new Item();
                it.id = cur.getLong(0);
                it.name = cur.getString(1) == null ? ("foto_" + it.id + ".jpg") : cur.getString(1);
                it.size = cur.getLong(2);
                it.taken = cur.isNull(3) ? 0 : cur.getLong(3);
                if (it.taken <= 0) it.taken = cur.getLong(4) * 1000L;
                it.uri = ContentUris.withAppendedId(coll, it.id);
                out.add(it);
            }
        }
        return out.toArray(new Item[0]);
    }

    /** Ask the PC which of these it already has – only the rest is sent (a repeated backup costs nothing). */
    private static boolean[] have(Context c, Item[] batch) throws Exception {
        JSONArray items = new JSONArray();
        for (Item it : batch) {
            JSONObject o = new JSONObject();
            o.put("name", it.name);
            o.put("size", realSize(c, it));
            o.put("taken", it.taken);
            items.put(o);
        }
        JSONObject body = new JSONObject();
        body.put("items", items);
        JSONArray r = new JSONObject(JarvisLink.http(c, "POST", "/api/phone/backup/have", body.toString(), 30000)).getJSONArray("have");
        boolean[] out = new boolean[batch.length];
        for (int i = 0; i < batch.length && i < r.length(); i++) out[i] = r.optBoolean(i, false);
        return out;
    }

    private static long realSize(Context c, Item it) {
        if (it.size > 0) return it.size;
        try (AssetFileDescriptor fd = c.getContentResolver().openAssetFileDescriptor(it.uri, "r")) {
            if (fd != null && fd.getLength() > 0) it.size = fd.getLength();
        } catch (Exception ignored) { }
        return it.size;
    }

    private static void upload(Context c, Item it) throws Exception {
        long size = realSize(c, it);
        if (size <= 0) return;                                    // an empty or unreadable entry: nothing to keep
        String base = JarvisLink.liveBase(c);
        if (base.isEmpty()) throw new IllegalStateException("telefon není spárovaný");
        HttpURLConnection con = (HttpURLConnection) new URL(base + "/api/phone/backup").openConnection();
        con.setRequestMethod("POST");
        con.setConnectTimeout(10000);
        con.setReadTimeout(120000);
        con.setDoOutput(true);
        con.setFixedLengthStreamingMode(size);
        con.setRequestProperty("Authorization", "Bearer " + JarvisLink.token(c));
        con.setRequestProperty("Content-Type", "application/octet-stream");
        con.setRequestProperty("X-Name", URLEncoder.encode(it.name, "UTF-8").replace("+", "%20"));
        con.setRequestProperty("X-Size", String.valueOf(size));
        con.setRequestProperty("X-Taken", String.valueOf(it.taken));
        try (OutputStream os = con.getOutputStream(); InputStream in = c.getContentResolver().openInputStream(it.uri)) {
            if (in == null) throw new IllegalStateException("fotku nejde přečíst");
            byte[] buf = new byte[128 * 1024];
            long left = size;
            int n;
            while (left > 0 && (n = in.read(buf, 0, (int) Math.min(buf.length, left))) > 0) {
                os.write(buf, 0, n);
                left -= n;
            }
            if (left > 0) throw new IllegalStateException("soubor se změnil během zálohy");
        }
        int code = con.getResponseCode();
        con.disconnect();
        if (code == 415) return;                                  // not something the PC keeps (an odd format): skip it
        if (code == 507) throw new IllegalStateException("na PC dochází místo");
        if (code >= 400) throw new IllegalStateException("PC odpovědělo " + code);
    }

    private static void progress(Context c, int done, int total, String name) {
        try {
            JarvisLink.channels(c);
            Notification n = JarvisLink.builder(c, JarvisLink.CH_LINK).setSmallIcon(android.R.drawable.ic_menu_upload)
                    .setContentTitle("Zálohuji fotky na PC").setContentText((done + 1) + " z " + Math.max(total, done + 1) + " · " + name)
                    .setProgress(Math.max(total, done + 1), done, false).setOngoing(true).setOnlyAlertOnce(true).build();
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.notify(NOTIF, n);
        } catch (Exception ignored) { }
    }
}
