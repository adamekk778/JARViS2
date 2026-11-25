package cz.adamekk.jarvis;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * 3.20 (121) NFC štítky: a sticker with the address jarvis://tag/<name> (written once with any NFC app). Touch it with
 * the phone and JARVIS does what you set for that tag on the PC ("štítek kuchyň = zhasni v kuchyni"). No window – a
 * short message with JARVIS's answer.
 */
public class NfcActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        handle(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handle(intent);
    }

    private void handle(Intent i) {
        Uri u = i == null ? null : i.getData();
        String tag = u != null && "jarvis".equals(u.getScheme()) && "tag".equals(u.getHost()) && u.getLastPathSegment() != null
                ? u.getLastPathSegment().toLowerCase(java.util.Locale.ROOT) : "";
        if (!tag.matches("[a-z0-9_-]{1,40}")) { finish(); return; }
        final android.content.Context app = getApplicationContext();
        final Handler ui = new Handler(Looper.getMainLooper());
        Toast.makeText(app, "JARVIS: štítek " + tag + "…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            String msg;
            try {
                String r = JarvisLink.http(app, "POST", "/api/phone/event", new JSONObject().put("kind", "nfc").put("tag", tag).toString(), 60000);
                msg = new JSONObject(r).optString("message", "Hotovo.");
            } catch (Exception e) {
                msg = "PC teď neodpovídá.";
            }
            final String shown = msg.length() > 160 ? msg.substring(0, 160) + "…" : msg;
            ui.post(() -> Toast.makeText(app, shown, Toast.LENGTH_LONG).show());
        }, "jarvis-nfc").start();
        finish();
    }
}
