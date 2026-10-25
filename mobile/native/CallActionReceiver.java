package cz.adamekk.jarvis;

import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** "Odmítnout" on the ringing notification. */
public class CallActionReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        String id = i.getStringExtra("id");
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.cancel(JarvisLink.NOTIF_CALL);
        if (id != null && CallActivity.claim(id)) JarvisLink.ack(c, id, "declined", "");
    }
}
