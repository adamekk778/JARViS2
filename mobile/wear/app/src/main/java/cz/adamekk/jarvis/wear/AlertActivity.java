package cz.adamekk.jarvis.wear;

import android.app.Activity;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.CountDownTimer;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * 3.20 Full-screen moments on the wrist: the silent alarm (154) and "find the watch" (157) vibrate until you tap;
 * a timer that ran out (145); after a fall (150) "Jsi v pořádku?" for 30 s – no answer → the PC's emergency protocol.
 */
public class AlertActivity extends Activity {
    private CountDownTimer timer;
    private boolean answered;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        String kind = getIntent().getStringExtra("kind");
        String text = getIntent().getStringExtra("text");
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER);
        l.setBackgroundColor("fall".equals(kind) ? Color.rgb(120, 0, 0) : Color.BLACK);
        TextView t = new TextView(this);
        t.setTextColor(Color.WHITE);
        t.setTextSize(16);
        t.setGravity(Gravity.CENTER);
        Button ok = new Button(this);
        l.addView(t);
        l.addView(ok);
        setContentView(l);
        if ("fall".equals(kind)) {
            ok.setText("Jsem v pořádku");
            Buzz.play(this, new long[]{0, 500, 300, 500}, true);
            timer = new CountDownTimer(30_000, 1000) {
                @Override
                public void onTick(long left) { t.setText("Spadl jsi? Jsi v pořádku?\n" + (left / 1000) + " s"); }

                @Override
                public void onFinish() { if (!answered) sendFall(t); }
            }.start();
        } else {
            ok.setText("Ok");
            t.setText(text == null || text.isEmpty() ? ("find".equals(kind) ? "Tady jsem!" : "timer".equals(kind) ? "Čas vypršel" : "Dobré ráno") : text);
            Buzz.play(this, "find".equals(kind) ? new long[]{0, 500, 250, 500, 250} : new long[]{0, 800, 400}, true);
        }
        ok.setOnClickListener(v -> { answered = true; Buzz.stop(this); finish(); });
    }

    private void sendFall(TextView t) {
        Buzz.stop(this);
        t.setText("Volám pomoc přes JARVISe…");
        new Thread(() -> {
            String msg;
            try {
                JSONObject b = new JSONObject();
                Location loc = last();
                if (loc != null) b.put("lat", loc.getLatitude()).put("lon", loc.getLongitude());
                msg = Api.post(this, "/api/watch/fall", b, 15000).optString("message", "Nouzový protokol běží.");
            } catch (Exception e) {
                msg = "PC neodpovídá – zavolej 112.";
            }
            final String shown = msg;
            runOnUiThread(() -> t.setText(shown));
        }).start();
    }

    @SuppressWarnings("MissingPermission")
    private Location last() {
        try {
            LocationManager lm = getSystemService(LocationManager.class);
            Location best = null;
            for (String p : lm.getProviders(true)) {
                Location l = lm.getLastKnownLocation(p);
                if (l != null && (best == null || l.getTime() > best.getTime())) best = l;
            }
            return best;
        } catch (Exception e) {
            return null;
        }
    }

    @Override
    protected void onDestroy() {
        if (timer != null) timer.cancel();
        Buzz.stop(this);
        super.onDestroy();
    }
}
