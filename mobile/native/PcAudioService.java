package cz.adamekk.jarvis;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import java.util.HashMap;
import java.util.Map;

/**
 * 3.12 Zvuk z PC do telefonu: plays what your PC plays (an AAC stream from your own PC – at home or through JARVIS
 * Link). Started by you in the app; the notification "Zvuk z PC" with Zastavit shows the whole time.
 */
public class PcAudioService extends Service {
    static volatile boolean running;
    static final String STOP = "cz.adamekk.jarvis.PCAUDIO_STOP";
    private static final int NOTIF = 7500;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private MediaPlayer mp;
    private WifiManager.WifiLock wifi;
    private int retries;
    private volatile boolean stopping;

    static void start(Context c) {
        Intent i = new Intent(c, PcAudioService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
        else c.startService(i);
    }

    static void stop(Context c) {
        c.startService(new Intent(c, PcAudioService.class).setAction(STOP));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) { stopping = true; stopSelf(); return START_NOT_STICKY; }
        JarvisLink.channels(this);
        PendingIntent stopPi = PendingIntent.getService(this, 7501, new Intent(this, PcAudioService.class).setAction(STOP), JarvisLink.piFlags());
        Notification n = JarvisLink.builder(this, JarvisLink.CH_LINK).setSmallIcon(android.R.drawable.ic_lock_silent_mode_off)
                .setContentTitle("Zvuk z PC").setContentText("Hraje to, co hraje tvoje PC.").setOngoing(true)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this, android.R.drawable.ic_media_pause),
                        "Zastavit", stopPi).build()).build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        else startForeground(NOTIF, n);
        if (running) return START_NOT_STICKY;
        running = true;
        stopping = false;
        retries = 0;
        try {
            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                wifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "jarvis:pcaudio");
                wifi.acquire();
            }
        } catch (Exception ignored) { }
        connect();
        return START_NOT_STICKY;
    }

    /** The address can need the JARVIS Link tunnel (network): find it off the main thread, then play. */
    private void connect() {
        new Thread(() -> {
            String base = JarvisLink.liveBase(this);
            ui.post(() -> play(base));
        }, "jarvis-pcaudio-connect").start();
    }

    private void play(String base) {
        if (stopping) return;
        release();
        try {
            mp = new MediaPlayer();
            mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());
            mp.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
            Map<String, String> h = new HashMap<>();
            h.put("Authorization", "Bearer " + JarvisLink.token(this));
            mp.setDataSource(this, Uri.parse(base + "/api/phone/audio"), h);
            mp.setOnPreparedListener(p -> { retries = 0; p.start(); });
            mp.setOnErrorListener((p, what, extra) -> { again(); return true; });
            mp.setOnCompletionListener(p -> again());      // the stream ended (the PC restarted, the network switched)
            mp.prepareAsync();
        } catch (Exception e) {
            again();
        }
    }

    private void again() {
        if (stopping) return;
        if (++retries > 8) { stopSelf(); return; }        // the PC is gone: end it (the notification goes away)
        ui.postDelayed(this::connect, Math.min(10000, 1500L * retries));
    }

    private void release() {
        if (mp != null) {
            try { mp.stop(); } catch (Exception ignored) { }
            mp.release();
            mp = null;
        }
    }

    @Override
    public void onDestroy() {
        stopping = true;
        running = false;
        ui.removeCallbacksAndMessages(null);
        release();
        try { if (wifi != null && wifi.isHeld()) wifi.release(); } catch (Exception ignored) { }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
