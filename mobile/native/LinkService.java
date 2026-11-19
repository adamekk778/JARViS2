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
    private android.content.BroadcastReceiver power;      // 3.13 plugged in / unplugged → the PC's notch at once
    private android.content.BroadcastReceiver dnd;        // 3.13 Do Not Disturb on / off
    private android.media.AudioDeviceCallback heads;      // 3.13 headphones connected / gone (no extra permission)
    private boolean headsReady;

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
                .setContentIntent(open).setOngoing(true)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this, android.R.drawable.ic_btn_speak_now),
                        "Mluvit", PendingIntent.getActivity(this, 1, new Intent(this, VoiceActivity.class)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), JarvisLink.piFlags())).build())   // 3.12 talk through the headphones
                .build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(JarvisLink.NOTIF_LINK, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(JarvisLink.NOTIF_LINK, n);
        if (TapDrop.enabled(this)) TapDrop.start(this);      // 3.12 "ťuk ťuk o monitor" → the newest photo to the PC
        else TapDrop.stop();
        if (PhoneIsland.enabled(this)) PhoneIsland.start(this);   // 3.12 the notch on the phone
        else PhoneIsland.stop();
        if (PhotoBackup.enabled(this)) PhotoBackup.start(this);   // 3.12 new photos → the PC by themselves
        else PhotoBackup.stop();
        if (power == null) {
            power = new android.content.BroadcastReceiver() {
                @Override
                public void onReceive(Context c, Intent i) {
                    JarvisLink.powerEvent(c.getApplicationContext(), Intent.ACTION_POWER_CONNECTED.equals(i.getAction()));
                }
            };
            android.content.IntentFilter f = new android.content.IntentFilter(Intent.ACTION_POWER_CONNECTED);
            f.addAction(Intent.ACTION_POWER_DISCONNECTED);
            try {
                if (Build.VERSION.SDK_INT >= 33) registerReceiver(power, f, Context.RECEIVER_NOT_EXPORTED);
                else registerReceiver(power, f);
            } catch (Exception ignored) { power = null; }
        }
        if (dnd == null) {
            dnd = new android.content.BroadcastReceiver() {
                @Override
                public void onReceive(Context c, Intent i) {
                    try {
                        android.app.NotificationManager nm = c.getSystemService(android.app.NotificationManager.class);
                        int f = nm.getCurrentInterruptionFilter();
                        JarvisLink.deviceEvent(c.getApplicationContext(), "dnd", f != android.app.NotificationManager.INTERRUPTION_FILTER_ALL, "");
                    } catch (Exception ignored) { }
                }
            };
            try {
                android.content.IntentFilter f = new android.content.IntentFilter(android.app.NotificationManager.ACTION_INTERRUPTION_FILTER_CHANGED);
                if (Build.VERSION.SDK_INT >= 33) registerReceiver(dnd, f, Context.RECEIVER_NOT_EXPORTED);
                else registerReceiver(dnd, f);
            } catch (Exception ignored) { dnd = null; }
        }
        if (heads == null && Build.VERSION.SDK_INT >= 23) {
            headsReady = false;                       // the first call lists what is already connected: not news
            heads = new android.media.AudioDeviceCallback() {
                @Override
                public void onAudioDevicesAdded(android.media.AudioDeviceInfo[] added) { report(added, true); }

                @Override
                public void onAudioDevicesRemoved(android.media.AudioDeviceInfo[] removed) { report(removed, false); }

                private void report(android.media.AudioDeviceInfo[] list, boolean on) {
                    if (!headsReady) { headsReady = true; return; }
                    for (android.media.AudioDeviceInfo d : list) {
                        if (!d.isSink()) continue;
                        int t = d.getType();
                        boolean hp = t == android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES || t == android.media.AudioDeviceInfo.TYPE_WIRED_HEADSET
                                || t == android.media.AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || t == android.media.AudioDeviceInfo.TYPE_USB_HEADSET
                                || (Build.VERSION.SDK_INT >= 31 && t == android.media.AudioDeviceInfo.TYPE_BLE_HEADSET);
                        if (hp) {
                            CharSequence n = d.getProductName();
                            JarvisLink.deviceEvent(getApplicationContext(), "headphones", on, n == null ? "" : n.toString());
                            return;
                        }
                    }
                }
            };
            try {
                android.media.AudioManager am = getSystemService(android.media.AudioManager.class);
                am.registerAudioDeviceCallback(heads, new android.os.Handler(android.os.Looper.getMainLooper()));
            } catch (Exception ignored) { heads = null; }
        }
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
        if (power != null) {
            try { unregisterReceiver(power); } catch (Exception ignored) { }
            power = null;
        }
        if (dnd != null) {
            try { unregisterReceiver(dnd); } catch (Exception ignored) { }
            dnd = null;
        }
        if (heads != null && Build.VERSION.SDK_INT >= 23) {
            try { getSystemService(android.media.AudioManager.class).unregisterAudioDeviceCallback(heads); } catch (Exception ignored) { }
            heads = null;
        }
        TapDrop.stop();
        PhoneIsland.stop();
        PhotoBackup.stop();
        if (worker != null) worker.interrupt();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
