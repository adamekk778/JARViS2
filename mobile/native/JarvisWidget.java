package cz.adamekk.jarvis;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.widget.RemoteViews;

/** OMEGA 136 / 722: a home-screen widget – what JARVIS is doing, the current mission and the pinned to-dos,
 *  with "Mluvit" and "Napsat". The app writes the state (JarvisPhonePlugin.widget); the widget only shows it. */
public class JarvisWidget extends AppWidgetProvider {
    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("jarvis_widget", Context.MODE_PRIVATE);
    }

    private static PendingIntent open(Context c, String what, int code) {
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse("jarvis://open/" + what));
        i.setPackage(c.getPackageName());
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(c, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    /** 3.12 the widget's "Zapnout PC": the magic packet straight from the widget, no app opened. */
    static final String WAKE = "cz.adamekk.jarvis.WIDGET_WAKE";

    /** 3.12 the song on the PC: back / play-pause / next straight from the widget (sent to the PC, no app opened). */
    static final String MEDIA = "cz.adamekk.jarvis.WIDGET_MEDIA";

    @Override
    public void onReceive(Context c, Intent intent) {
        if (MEDIA.equals(intent.getAction())) {
            final PendingResult done = goAsync();
            final Context app = c.getApplicationContext();
            final String action = intent.getStringExtra("action");
            new Thread(() -> {
                try {
                    org.json.JSONObject b = new org.json.JSONObject();
                    b.put("action", action == null ? "play_pause" : action);
                    JarvisLink.http(app, "POST", "/api/phone/media", b.toString(), 8000);
                } catch (Exception ignored) {
                } finally {
                    done.finish();
                }
            }, "jarvis-widget-media").start();
            return;
        }
        if (WAKE.equals(intent.getAction())) {
            final PendingResult done = goAsync();
            final Context app = c.getApplicationContext();
            prefs(app).edit().putString("wake_state", "Posílám signál…").apply();
            refresh(app);
            new Thread(() -> {
                try {
                    org.json.JSONObject r = WakePc.send(app);
                    String msg = r.optBoolean("ok") ? "Signál odeslán – PC se zapíná" : r.optString("error", "Nepovedlo se");
                    prefs(app).edit().putString("wake_state", msg).apply();
                } catch (Exception e) {
                    prefs(app).edit().putString("wake_state", "Nepovedlo se").apply();
                }
                refresh(app);
                done.finish();
            }, "jarvis-widget-wake").start();
            return;
        }
        super.onReceive(c, intent);
    }

    private static PendingIntent media(Context c, String action, int code) {
        Intent i = new Intent(c, JarvisWidget.class).setAction(MEDIA).putExtra("action", action);
        return PendingIntent.getBroadcast(c, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    /** 3.13 "✓ Schválit" / "✕" for a Velín proposal right on the widget – the same path as the notification's buttons. */
    private static PendingIntent decide(Context c, String pid, boolean yes, int code) {
        Intent i = new Intent(c, ConfirmReceiver.class).putExtra("id", "biz:" + pid).putExtra("approved", yes).putExtra("widget", true);
        return PendingIntent.getBroadcast(c, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    private static PendingIntent wake(Context c) {
        Intent i = new Intent(c, JarvisWidget.class).setAction(WAKE);
        return PendingIntent.getBroadcast(c, 9, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static RemoteViews views(Context c) {
        SharedPreferences p = prefs(c);
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_jarvis);
        v.setTextViewText(R.id.w_status, p.getString("status", "Otevři aplikaci JARVIS"));
        // 3.15 Mega animace: a spinning ring while JARVIS works, a bar filling with the running task
        v.setViewVisibility(R.id.w_spin, p.getBoolean("busy", false) ? android.view.View.VISIBLE : android.view.View.GONE);
        int prog = p.getInt("progress", -1);
        v.setViewVisibility(R.id.w_prog, prog >= 0 ? android.view.View.VISIBLE : android.view.View.GONE);
        if (prog >= 0) v.setProgressBar(R.id.w_prog, 100, Math.min(100, prog), false);
        String task = p.getString("task", "");
        v.setTextViewText(R.id.w_task, task);
        v.setViewVisibility(R.id.w_task, task.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
        String pins = p.getString("pins", "");
        v.setTextViewText(R.id.w_pins, pins.isEmpty() ? "Nic připnutého" : pins);
        String habits = p.getString("habits", "");
        v.setTextViewText(R.id.w_habits, habits);
        v.setViewVisibility(R.id.w_habits, habits.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
        v.setOnClickPendingIntent(R.id.w_habits, open(c, "habits", 4));
        String biz = p.getString("biz", "");            // 3.13 Velín: the first thing waiting for your approval
        String bizId = p.getString("biz_id", "");
        v.setViewVisibility(R.id.w_biz, biz.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
        v.setTextViewText(R.id.w_biz_text, "🏢  " + biz);
        v.setOnClickPendingIntent(R.id.w_biz_text, open(c, "company", 5));
        boolean act = !bizId.isEmpty();
        v.setViewVisibility(R.id.w_biz_yes, act ? android.view.View.VISIBLE : android.view.View.GONE);
        v.setViewVisibility(R.id.w_biz_no, act ? android.view.View.VISIBLE : android.view.View.GONE);
        if (act) {
            v.setOnClickPendingIntent(R.id.w_biz_yes, decide(c, bizId, true, 31));
            v.setOnClickPendingIntent(R.id.w_biz_no, decide(c, bizId, false, 32));
        }
        String song = p.getString("song", "");
        v.setViewVisibility(R.id.w_music, song.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
        v.setTextViewText(R.id.w_song, "♪  " + song);
        v.setOnClickPendingIntent(R.id.w_prev, media(c, "previous", 21));
        v.setOnClickPendingIntent(R.id.w_play, media(c, "play_pause", 22));
        v.setOnClickPendingIntent(R.id.w_next, media(c, "next", 23));
        String ws = p.getString("wake_state", "");
        v.setTextViewText(R.id.w_wake, ws.isEmpty() ? "⏻  Zapnout PC" : "⏻  " + ws);
        v.setViewVisibility(R.id.w_wake, WakePc.known(c) ? android.view.View.VISIBLE : android.view.View.GONE);
        v.setOnClickPendingIntent(R.id.w_wake, wake(c));
        v.setOnClickPendingIntent(R.id.w_talk, open(c, "talk", 1));
        v.setOnClickPendingIntent(R.id.w_chat, open(c, "chat", 2));
        v.setOnClickPendingIntent(R.id.w_root, open(c, "home", 3));
        return v;
    }

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) m.updateAppWidget(id, views(c));
    }

    static void refresh(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] ids = m.getAppWidgetIds(new ComponentName(c, JarvisWidget.class));
        for (int id : ids) m.updateAppWidget(id, views(c));
    }
}
