package cz.adamekk.jarvis;

import android.content.Intent;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(JarvisPhonePlugin.class);
        super.onCreate(savedInstanceState);
        handle(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handle(intent);
    }

    /** "Odpovědět" on JARVIS's call: the app opens ready to talk. */
    private void handle(Intent i) {
        if (i != null && i.getBooleanExtra("jarvis_reply", false)) JarvisPhonePlugin.reply(i.getStringExtra("call_id"));
    }
}
