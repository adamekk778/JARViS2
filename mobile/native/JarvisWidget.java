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

    static RemoteViews views(Context c) {
        SharedPreferences p = prefs(c);
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_jarvis);
        v.setTextViewText(R.id.w_status, p.getString("status", "Otevři aplikaci JARVIS"));
        String task = p.getString("task", "");
        v.setTextViewText(R.id.w_task, task);
        v.setViewVisibility(R.id.w_task, task.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
        String pins = p.getString("pins", "");
        v.setTextViewText(R.id.w_pins, pins.isEmpty() ? "Nic připnutého" : pins);
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
