package cz.adamekk.jarvis;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;

/** 3.5 "Najdi můj telefon": a loud alarm (even on silent) for a minute, until you tap "Našel jsem ho". */
public final class FindPhone {
    private FindPhone() {}

    static final int NOTIF_FIND = 7003;
    private static Ringtone tone;
    private static int savedVolume = -1;
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final Runnable autoStop = () -> stop(null);
    private static Context app;

    static synchronized void start(Context c) {
        app = c.getApplicationContext();
        stopSound();
        AudioManager am = app.getSystemService(AudioManager.class);
        if (am != null) {
            savedVolume = am.getStreamVolume(AudioManager.STREAM_ALARM);
            am.setStreamVolume(AudioManager.STREAM_ALARM, am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
        }
        Uri uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
        if (uri == null) uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
        tone = RingtoneManager.getRingtone(app, uri);
        if (tone != null) {
            tone.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
            if (Build.VERSION.SDK_INT >= 28) tone.setLooping(true);
            tone.play();
        }
        Vibrator v = app.getSystemService(Vibrator.class);
        if (v != null && Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createWaveform(new long[] { 0, 700, 400 }, 0));
        JarvisLink.channels(app);
        PendingIntent found = PendingIntent.getBroadcast(app, 4, new Intent(app, CallActionReceiver.class).putExtra("what", "find"),
                JarvisLink.piFlags());
        Notification n = JarvisLink.builder(app, JarvisLink.CH_CALL).setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setContentTitle("JARVIS hledá tenhle telefon").setContentText("Klepni, až ho najdeš.")
                .setCategory(Notification.CATEGORY_ALARM).setPriority(Notification.PRIORITY_MAX).setOngoing(true)
                .setContentIntent(found).setDeleteIntent(found)
                .addAction(new Notification.Action.Builder(null, "Našel jsem ho", found).build())
                .setVisibility(Notification.VISIBILITY_PUBLIC).build();
        NotificationManager nm = app.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTIF_FIND, n);
        main.removeCallbacks(autoStop);
        main.postDelayed(autoStop, 60000);
    }

    private static void stopSound() {
        if (tone != null) {
            try { tone.stop(); } catch (Exception ignored) { }
            tone = null;
        }
    }

    static synchronized void stop(Context c) {
        Context ctx = c != null ? c.getApplicationContext() : app;
        main.removeCallbacks(autoStop);
        stopSound();
        if (ctx == null) return;
        AudioManager am = ctx.getSystemService(AudioManager.class);
        if (am != null && savedVolume >= 0) am.setStreamVolume(AudioManager.STREAM_ALARM, savedVolume, 0);
        savedVolume = -1;
        Vibrator v = ctx.getSystemService(Vibrator.class);
        if (v != null) v.cancel();
        NotificationManager nm = ctx.getSystemService(NotificationManager.class);
        if (nm != null) nm.cancel(NOTIF_FIND);
    }
}
