package cz.adamekk.jarvis;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** 3.20 (133) the buttons of the lock-screen line: the PC's volume −, mute, + (and the tiles' actions). */
public class PcControlReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        String a = i.getStringExtra("action");
        if (a == null || !a.matches("[a-z_]{2,20}")) return;
        PhoneX.pcAction(c.getApplicationContext(), a, goAsync());
    }
}
