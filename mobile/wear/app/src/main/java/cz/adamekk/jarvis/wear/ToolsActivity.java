package cz.adamekk.jarvis.wear;

import android.app.Activity;
import android.graphics.Color;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Bundle;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 3.20 (142) the PC from the wrist: mute, lock, music, volume; (148) a waiting payment opens on the phone (approved
 * there with the fingerprint); "find the phone"; (155) the presenter: big Další / Zpět, or a flick of the wrist
 * (outwards = next slide, inwards = back) while this screen is on.
 */
public class ToolsActivity extends Activity implements SensorEventListener {
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private TextView msg;
    private SensorManager sm;
    private boolean presenter;
    private long lastFlick;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        presenter = getIntent().getBooleanExtra("presenter", false);
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER_HORIZONTAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        l.setPadding(pad, pad, pad, pad);
        l.setBackgroundColor(Color.BLACK);
        msg = new TextView(this);
        msg.setTextColor(Color.WHITE);
        msg.setGravity(Gravity.CENTER);
        String[][] acts = presenter
                ? new String[][]{{"next_slide", "Další snímek ▶"}, {"prev_slide", "◀ Zpět"}}
                : new String[][]{{"mute", "Ztlumit PC"}, {"unmute", "Zapnout zvuk"}, {"play_pause", "Pauza / hrát"}, {"next", "Další skladba"},
                {"vol_up", "Hlasitěji"}, {"vol_down", "Tišeji"}, {"lock", "Zamknout PC"}, {"open_payment", "Platba → telefon"},
                {"find_phone", "Najít telefon"}};
        if (presenter) {
            msg.setText("Švihni zápěstím ven = další, dovnitř = zpět");
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
        for (String[] a : acts) {
            Button b = new Button(this);
            b.setText(a[1]);
            final String act = a[0];
            b.setOnClickListener(v -> send(act));
            l.addView(b);
        }
        l.addView(msg);
        ScrollView sv = new ScrollView(this);
        sv.addView(l);
        setContentView(sv);
    }

    private void send(String action) {
        msg.setText("…");
        io.execute(() -> {
            String m;
            try { m = Api.action(this, action); } catch (Exception e) { m = "PC neodpovídá."; }
            final String shown = m;
            runOnUiThread(() -> msg.setText(shown));
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!presenter) return;
        sm = getSystemService(SensorManager.class);
        Sensor g = sm == null ? null : sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
        if (g != null) sm.registerListener(this, g, SensorManager.SENSOR_DELAY_GAME);
    }

    @Override
    protected void onPause() {
        if (sm != null) sm.unregisterListener(this);
        super.onPause();
    }

    @Override
    public void onSensorChanged(SensorEvent e) {
        float rot = e.values[0];                              // roll of the wrist (rad/s)
        long now = System.currentTimeMillis();
        if (Math.abs(rot) > 6.0f && now - lastFlick > 900) {
            lastFlick = now;
            Buzz.play(this, new long[]{0, 40}, false);
            send(rot > 0 ? "next_slide" : "prev_slide");
        }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    @Override
    protected void onDestroy() {
        io.shutdown();
        super.onDestroy();
    }
}
