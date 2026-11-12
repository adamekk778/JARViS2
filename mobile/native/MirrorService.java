package cz.adamekk.jarvis;

import android.app.Activity;
import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.util.DisplayMetrics;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;

/**
 * 3.12 Telefon na monitoru PC: the phone's screen in a window on your PC. Starts only after Android's own "share your
 * screen" question (every time), shows a notification "Obrazovka se zobrazuje na PC" with Zastavit the whole time,
 * and sends the picture only to your paired PC. Mouse and keyboard on the PC drive the phone through MirrorControl
 * (an accessibility service you switch on once) – only while this is running.
 */
public class MirrorService extends Service {
    static volatile boolean running;
    static final String STOP = "cz.adamekk.jarvis.MIRROR_STOP";
    private static final int NOTIF = 7400;
    private static final int TARGET_W = 720;            // the picture's shorter side (enough to read, light to send)
    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader reader;
    private HandlerThread thread;
    private volatile boolean stopping;
    private int w, h;

    static void stop(Context c) {
        c.startService(new Intent(c, MirrorService.class).setAction(STOP));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (running || intent == null) return START_NOT_STICKY;
        JarvisLink.channels(this);
        PendingIntent stopPi = PendingIntent.getService(this, 7401, new Intent(this, MirrorService.class).setAction(STOP), JarvisLink.piFlags());
        Notification n = JarvisLink.builder(this, JarvisLink.CH_LINK).setSmallIcon(android.R.drawable.ic_menu_view)
                .setContentTitle("Obrazovka telefonu se zobrazuje na PC").setContentText("Jen na tvém PC. Zastavíš tady.")
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                        "Zastavit", stopPi).build()).build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        else startForeground(NOTIF, n);
        int code = intent.getIntExtra("code", Activity.RESULT_CANCELED);
        Intent data = intent.getParcelableExtra("data");
        MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        if (mpm == null || data == null || code != Activity.RESULT_OK) { stopSelf(); return START_NOT_STICKY; }
        try {
            projection = mpm.getMediaProjection(code, data);
        } catch (Exception e) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (projection == null) { stopSelf(); return START_NOT_STICKY; }
        thread = new HandlerThread("jarvis-mirror-display");
        thread.start();
        Handler handler = new Handler(thread.getLooper());
        projection.registerCallback(new MediaProjection.Callback() {
            @Override public void onStop() { stopSelf(); }
        }, handler);
        int[] size = size();
        w = size[0];
        h = size[1];
        reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
        display = projection.createVirtualDisplay("jarvis-mirror", w, h, size[2], DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.getSurface(), null, handler);
        running = true;
        stopping = false;
        new Thread(this::loop, "jarvis-mirror").start();
        return START_NOT_STICKY;
    }

    /** The picture size for the current orientation: the shorter side TARGET_W, the real aspect ratio. */
    @SuppressWarnings("deprecation")
    private int[] size() {
        DisplayMetrics m = new DisplayMetrics();
        DisplayManager dm = (DisplayManager) getSystemService(Context.DISPLAY_SERVICE);
        dm.getDisplay(android.view.Display.DEFAULT_DISPLAY).getRealMetrics(m);   // a service has no window: ask the display
        int rw = m.widthPixels, rh = m.heightPixels;
        float scale = Math.min(1f, TARGET_W / (float) Math.min(rw, rh));
        int dpi = Math.max(120, (int) (m.densityDpi * scale));
        return new int[] { Math.max(2, Math.round(rw * scale) & ~1), Math.max(2, Math.round(rh * scale) & ~1), dpi };
    }

    private void loop() {
        int errors = 0;
        long lastSent = 0;
        while (running && !stopping) {
            long t0 = System.currentTimeMillis();
            try {
                int[] s = size();
                if (s[0] != w || s[1] != h) {                 // turned the phone: a new picture size
                    ImageReader old = reader;
                    w = s[0];
                    h = s[1];
                    reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
                    display.resize(w, h, s[2]);
                    display.setSurface(reader.getSurface());
                    old.close();
                }
                byte[] jpeg = grab();
                if (jpeg != null || t0 - lastSent > 400) {   // nothing changed: still ask for the PC's clicks
                    handle(post(jpeg));
                    lastSent = t0;
                }
                errors = 0;
            } catch (Exception e) {
                if (++errors > 40) break;                     // ~10 s without the PC: end it
            }
            long left = 220 - (System.currentTimeMillis() - t0);
            if (left > 0) try { Thread.sleep(left); } catch (InterruptedException ie) { break; }
        }
        stopSelf();
    }

    private byte[] grab() {
        Image img = reader.acquireLatestImage();
        if (img == null) return null;
        try {
            Image.Plane p = img.getPlanes()[0];
            ByteBuffer buf = p.getBuffer();
            int pixel = p.getPixelStride(), row = p.getRowStride();
            int iw = img.getWidth(), ih = img.getHeight();
            Bitmap bmp = Bitmap.createBitmap(row / pixel, ih, Bitmap.Config.ARGB_8888);
            bmp.copyPixelsFromBuffer(buf);
            Bitmap crop = bmp.getWidth() == iw ? bmp : Bitmap.createBitmap(bmp, 0, 0, iw, ih);
            ByteArrayOutputStream out = new ByteArrayOutputStream(64 * 1024);
            crop.compress(Bitmap.CompressFormat.JPEG, 60, out);
            if (crop != bmp) crop.recycle();
            bmp.recycle();
            return out.toByteArray();
        } finally {
            img.close();
        }
    }

    private JSONObject post(byte[] jpeg) throws Exception {
        String base = JarvisLink.liveBase(this);
        HttpURLConnection con = (HttpURLConnection) new URL(base + "/api/phone/mirror/frame").openConnection();
        con.setRequestMethod("POST");
        con.setConnectTimeout(5000);
        con.setReadTimeout(8000);
        con.setDoOutput(true);
        byte[] body = jpeg == null ? new byte[0] : jpeg;
        con.setFixedLengthStreamingMode(body.length);
        con.setRequestProperty("Authorization", "Bearer " + JarvisLink.token(this));
        con.setRequestProperty("Content-Type", "image/jpeg");
        con.setRequestProperty("X-W", String.valueOf(w));
        con.setRequestProperty("X-H", String.valueOf(h));
        con.setRequestProperty("X-Control", MirrorControl.ready() ? "1" : "0");
        try (OutputStream os = con.getOutputStream()) { os.write(body); }
        int code = con.getResponseCode();
        if (code >= 400) { con.disconnect(); throw new IllegalStateException("HTTP " + code); }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (InputStream in = con.getInputStream()) {
            byte[] b = new byte[4096];
            int n;
            while ((n = in.read(b)) > 0) out.write(b, 0, n);
        }
        return new JSONObject(out.toString("UTF-8"));
    }

    private void handle(JSONObject r) {
        if (r == null) return;
        if (r.optBoolean("stop")) { stopping = true; return; }
        JSONArray in = r.optJSONArray("inputs");
        for (int i = 0; in != null && i < in.length(); i++) {
            JSONObject m = in.optJSONObject(i);
            if (m != null) MirrorControl.perform(m);
        }
    }

    @Override
    public void onDestroy() {
        running = false;
        stopping = true;
        try { if (display != null) display.release(); } catch (Exception ignored) { }
        try { if (reader != null) reader.close(); } catch (Exception ignored) { }
        try { if (projection != null) projection.stop(); } catch (Exception ignored) { }
        if (thread != null) thread.quitSafely();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
