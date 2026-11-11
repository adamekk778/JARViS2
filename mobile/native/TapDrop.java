package cz.adamekk.jarvis;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationManager;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.Context;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.MediaStore;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.ImageView;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * 3.12 "ťuk ťuk o monitor": while the background link runs and this is switched on (Více → Telefon), knocking the
 * phone twice against the monitor – held up, screen on, anywhere (also in the gallery) – sends the newest photo or
 * screenshot to the paired PC. A short flight animation on the phone (when JARVIS may draw over other apps), a buzz,
 * and the PC's notch shows it landing. Nothing is sent without the knock; the photo goes only to your own PC.
 */
final class TapDrop implements SensorEventListener {
    private static TapDrop active;
    private final Context ctx;
    private final SensorManager sm;
    private final float[] g = new float[3];
    private boolean gInit;
    private long lastSpike, firstKnock, lastFire;
    private volatile boolean sending;

    private TapDrop(Context c) {
        ctx = c.getApplicationContext();
        sm = (SensorManager) ctx.getSystemService(Context.SENSOR_SERVICE);
    }

    static boolean enabled(Context c) { return JarvisLink.prefs(c).getBoolean("tapdrop", false); }

    static synchronized void start(Context c) {
        if (active != null) return;
        TapDrop t = new TapDrop(c);
        Sensor acc = t.sm == null ? null : t.sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
        if (acc == null) return;
        t.sm.registerListener(t, acc, SensorManager.SENSOR_DELAY_GAME);
        active = t;
    }

    static synchronized void stop() {
        if (active == null) return;
        active.sm.unregisterListener(active);
        active = null;
    }

    static boolean canReadPhotos(Context c) {
        String p = Build.VERSION.SDK_INT >= 33 ? Manifest.permission.READ_MEDIA_IMAGES : Manifest.permission.READ_EXTERNAL_STORAGE;
        return JarvisLink.has(c, p);
    }

    @Override
    public void onSensorChanged(SensorEvent e) {
        float x = e.values[0], y = e.values[1], z = e.values[2];
        if (!gInit) { g[0] = x; g[1] = y; g[2] = z; gInit = true; return; }
        final float a = 0.9f;                                  // slow average = gravity; the rest = the knock
        g[0] = a * g[0] + (1 - a) * x; g[1] = a * g[1] + (1 - a) * y; g[2] = a * g[2] + (1 - a) * z;
        float lx = x - g[0], ly = y - g[1], lz = z - g[2];
        double mag = Math.sqrt(lx * lx + ly * ly + lz * lz);
        long now = SystemClock.uptimeMillis();
        if (mag < 13 || now - lastSpike < 90) return;
        lastSpike = now;
        boolean upright = Math.abs(g[2]) < 6.0f;               // held up to the screen, not lying on a table
        if (!upright) { firstKnock = 0; return; }
        if (firstKnock > 0 && now - firstKnock >= 120 && now - firstKnock <= 700) {
            firstKnock = 0;
            if (now - lastFire > 4000 && !sending && interactive() && !MainActivity.visible) {
                lastFire = now;
                sending = true;
                new Thread(this::send, "jarvis-tapdrop").start();
            }
        } else {
            firstKnock = now;
        }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    private boolean interactive() {
        PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
        return pm == null || pm.isInteractive();
    }

    // ---------- the newest photo → the PC ----------
    private void send() {
        try {
            buzz(30);
            if (!canReadPhotos(ctx)) { notice("Povol JARVISovi fotky", "Otevři JARVIS → Více → Telefon → Ťuk o monitor a povol přístup k fotkám."); return; }
            ContentResolver cr = ctx.getContentResolver();
            Uri coll = MediaStore.Images.Media.EXTERNAL_CONTENT_URI;
            String[] proj = { MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.MIME_TYPE };
            long id = -1; String name = "fotka.jpg", mime = "image/jpeg";
            try (Cursor cur = cr.query(coll, proj, null, null, MediaStore.Images.Media.DATE_ADDED + " DESC")) {
                if (cur != null && cur.moveToFirst()) {
                    id = cur.getLong(0);
                    if (cur.getString(1) != null) name = cur.getString(1);
                    if (cur.getString(2) != null) mime = cur.getString(2);
                }
            }
            if (id < 0) { notice("Žádná fotka", "V telefonu jsem nenašel žádnou fotku."); return; }
            Uri uri = ContentUris.withAppendedId(coll, id);
            final Bitmap thumb = thumbnail(cr, uri, id);
            new Handler(Looper.getMainLooper()).post(() -> fly(thumb));
            String aid = upload(cr, uri, name, mime);
            JSONObject o = new JSONObject();
            o.put("attachment_id", aid);
            JarvisLink.http(ctx, "POST", "/api/phone/drop", o.toString(), 15000);
            buzz(60);
        } catch (Exception ex) {
            notice("Na PC se to neposlalo", "Je PC zapnuté a JARVIS na něm běží? (" + ex.getMessage() + ")");
        } finally {
            sending = false;
        }
    }

    private static Bitmap thumbnail(ContentResolver cr, Uri uri, long id) {
        try {
            if (Build.VERSION.SDK_INT >= 29) return cr.loadThumbnail(uri, new android.util.Size(480, 480), null);
            return MediaStore.Images.Thumbnails.getThumbnail(cr, id, MediaStore.Images.Thumbnails.MINI_KIND, null);
        } catch (Exception e) {
            return null;
        }
    }

    private String upload(ContentResolver cr, Uri uri, String name, String mime) throws Exception {
        String base = JarvisLink.base(ctx);
        if (base.isEmpty()) throw new IllegalStateException("telefon není spárovaný");
        String boundary = "jarvis" + System.currentTimeMillis();
        HttpURLConnection con = (HttpURLConnection) new URL(base + "/api/upload").openConnection();
        con.setRequestMethod("POST");
        con.setConnectTimeout(8000);
        con.setReadTimeout(60000);
        con.setDoOutput(true);
        con.setChunkedStreamingMode(64 * 1024);
        con.setRequestProperty("Authorization", "Bearer " + JarvisLink.token(ctx));
        con.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        String safe = name.replace("\"", "").replace("\r", "").replace("\n", "");
        try (OutputStream os = con.getOutputStream(); InputStream in = cr.openInputStream(uri)) {
            if (in == null) throw new IllegalStateException("fotku nejde přečíst");
            os.write(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" + safe + "\"\r\nContent-Type: "
                    + mime + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
            os.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
        }
        int code = con.getResponseCode();
        InputStream rin = code < 400 ? con.getInputStream() : con.getErrorStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (rin != null) {
            byte[] b = new byte[8192];
            int k;
            while ((k = rin.read(b)) > 0) out.write(b, 0, k);
            rin.close();
        }
        con.disconnect();
        if (code >= 400) throw new IllegalStateException("HTTP " + code);
        return new JSONObject(out.toString("UTF-8")).getString("id");
    }

    // ---------- the phone side of the animation ----------
    private void fly(Bitmap thumb) {
        if (thumb == null || !Settings.canDrawOverlays(ctx)) return;      // no "draw over apps": the buzz is enough
        try {
            final WindowManager wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
            int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY : WindowManager.LayoutParams.TYPE_PHONE;
            WindowManager.LayoutParams lp = new WindowManager.LayoutParams(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT, type,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                    PixelFormat.TRANSLUCENT);
            final FrameLayout root = new FrameLayout(ctx);
            final View flash = new View(ctx);
            flash.setBackgroundColor(Color.argb(140, 255, 255, 255));
            root.addView(flash, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
            final ImageView img = new ImageView(ctx);
            img.setImageBitmap(thumb);
            img.setScaleType(ImageView.ScaleType.CENTER_CROP);
            GradientDrawable bg = new GradientDrawable();
            float d = ctx.getResources().getDisplayMetrics().density;
            bg.setCornerRadius(28 * d);
            bg.setColor(Color.BLACK);
            img.setBackground(bg);
            img.setClipToOutline(true);
            img.setElevation(24 * d);
            int size = (int) (240 * d);
            root.addView(img, new FrameLayout.LayoutParams(size, (int) (size * 1.25f), Gravity.CENTER));
            wm.addView(root, lp);
            float up = -ctx.getResources().getDisplayMetrics().heightPixels * 0.55f;
            flash.animate().alpha(0f).setDuration(450).start();
            img.setScaleX(0.85f); img.setScaleY(0.85f); img.setAlpha(0f);
            img.animate().scaleX(1.05f).scaleY(1.05f).alpha(1f).setDuration(220).withEndAction(() ->
                    img.animate().translationY(up).scaleX(0.12f).scaleY(0.12f).rotation(-8f).alpha(0f).setDuration(620)
                            .withEndAction(() -> { try { wm.removeView(root); } catch (Exception ignored) { } }).start()).start();
        } catch (Exception ignored) { }
    }

    private void buzz(long ms) {
        try {
            Vibrator v = (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
            if (v == null) return;
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE));
            else v.vibrate(ms);
        } catch (Exception ignored) { }
    }

    private void notice(String title, String text) {
        try {
            JarvisLink.channels(ctx);
            Notification n = JarvisLink.builder(ctx, JarvisLink.CH_ACTION).setSmallIcon(android.R.drawable.ic_menu_upload)
                    .setContentTitle(title).setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setAutoCancel(true).build();
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.notify(7010, n);
        } catch (Exception ignored) { }
    }
}
