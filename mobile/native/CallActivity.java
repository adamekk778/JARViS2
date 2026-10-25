package cz.adamekk.jarvis;

import android.app.Activity;
import android.app.KeyguardManager;
import android.app.Notification;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioAttributes;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.speech.tts.TextToSpeech;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** "JARVIS volá": rings, then says the message out loud; you can answer by voice in the app. */
public class CallActivity extends Activity {
    private static final long RING_MS = 45000;
    private static final Set<String> handled = new HashSet<>();
    private static final Handler main = new Handler(Looper.getMainLooper());

    private String id = "", text = "";
    private Ringtone ringtone;
    private Vibrator vibrator;
    private TextToSpeech tts;
    private TextView title, sub, body;
    private LinearLayout buttons;
    private View orb;
    private boolean answered;

    /** Not picked up within 45 s → a missed call (also when the screen never opened). */
    static void scheduleMissed(final Context c, final String id, final String text) {
        main.postDelayed(() -> {
            synchronized (handled) {
                if (handled.contains(id)) return;
                handled.add(id);
            }
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.cancel(JarvisLink.NOTIF_CALL);
                Notification n = JarvisLink.builder(c, JarvisLink.CH_ACTION).setSmallIcon(android.R.drawable.sym_call_missed)
                        .setContentTitle("Zmeškaný hovor od JARVISe").setContentText(text)
                        .setStyle(new Notification.BigTextStyle().bigText(text)).setAutoCancel(true).build();
                nm.notify(JarvisLink.NOTIF_CALL + 1, n);
            }
            JarvisLink.ack(c, id, "missed", "");
        }, RING_MS);
    }

    static boolean claim(String id) {
        synchronized (handled) {
            if (handled.contains(id)) return false;
            handled.add(id);
            return true;
        }
    }

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        Intent in = getIntent();
        id = in.getStringExtra("id") == null ? "" : in.getStringExtra("id");
        text = in.getStringExtra("text") == null ? "" : in.getStringExtra("text");
        String caller = in.getStringExtra("caller") == null ? "JARVIS" : in.getStringExtra("caller");
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.cancel(JarvisLink.NOTIF_CALL);
        buildUi(caller);
        if (in.getBooleanExtra("answer", false)) answer();
        else startRinging();
    }

    private void buildUi(String caller) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(28), dp(90), dp(28), dp(56));
        GradientDrawable bg = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[] { 0xFF04121F, 0xFF02060C });
        root.setBackground(bg);

        orb = new View(this);
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setGradientType(GradientDrawable.RADIAL_GRADIENT);
        g.setGradientRadius(dp(80));
        g.setColors(new int[] { 0xFFFFFFFF, 0xFF8FE3FF, 0xFF2E8FD0, 0x00000000 });
        orb.setBackground(g);
        LinearLayout.LayoutParams op = new LinearLayout.LayoutParams(dp(160), dp(160));
        op.bottomMargin = dp(36);
        root.addView(orb, op);
        orb.animate().scaleX(1.12f).scaleY(1.12f).setDuration(900).setInterpolator(new AccelerateDecelerateInterpolator())
                .withEndAction(this::pulse).start();

        title = text(caller, 34, Color.WHITE, true);
        root.addView(title);
        sub = text("volá…", 18, 0xFF8FC3D6, false);
        root.addView(sub);
        body = text("", 22, 0xFFEFFBFF, false);
        body.setPadding(0, dp(32), 0, 0);
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(body, bp);

        buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setGravity(Gravity.CENTER);
        root.addView(buttons, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        showRingingButtons();
        setContentView(root);
    }

    private void pulse() {
        if (orb == null || isFinishing()) return;
        float to = orb.getScaleX() > 1.05f ? 1f : 1.12f;
        orb.animate().scaleX(to).scaleY(to).setDuration(answered ? 1400 : 700).withEndAction(this::pulse).start();
    }

    private TextView text(String s, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setGravity(Gravity.CENTER);
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.BOLD));
        return t;
    }

    private Button round(String label, int color, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextColor(Color.WHITE);
        b.setAllCaps(false);
        b.setTextSize(16);
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.RECTANGLE);
        d.setCornerRadius(dp(40));
        d.setColor(color);
        b.setBackground(d);
        b.setOnClickListener(l);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, dp(64), 1f);
        p.leftMargin = p.rightMargin = dp(10);
        b.setLayoutParams(p);
        return b;
    }

    private void showRingingButtons() {
        buttons.removeAllViews();
        buttons.addView(round("Odmítnout", 0xFFE5484D, v -> decline()));
        buttons.addView(round("Přijmout", 0xFF2FB463, v -> answer()));
    }

    private void startRinging() {
        try {
            ringtone = RingtoneManager.getRingtone(this, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE));
            if (ringtone != null) {
                if (Build.VERSION.SDK_INT >= 28) ringtone.setLooping(true);
                ringtone.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build());
                ringtone.play();
            }
            vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (vibrator != null && Build.VERSION.SDK_INT >= 26) {
                vibrator.vibrate(VibrationEffect.createWaveform(new long[] { 0, 800, 600 }, 0));
            }
        } catch (Exception ignored) { }
    }

    private void stopRinging() {
        try { if (ringtone != null) ringtone.stop(); } catch (Exception ignored) { }
        try { if (vibrator != null) vibrator.cancel(); } catch (Exception ignored) { }
    }

    private void answer() {
        if (answered) return;
        answered = true;
        stopRinging();
        claim(id);
        JarvisLink.ack(this, id, "answered", "");
        sub.setText("na lince");
        body.setText(text);
        buttons.removeAllViews();
        buttons.addView(round("Zavěsit", 0xFFE5484D, v -> finish()));
        buttons.addView(round("Odpovědět", 0xFF2E8FD0, v -> reply()));
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS && tts != null) {
                tts.setLanguage(new Locale("cs", "CZ"));
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis-" + id);
            }
        });
    }

    private void decline() {
        stopRinging();
        if (claim(id)) JarvisLink.ack(this, id, "declined", "");
        finish();
    }

    /** Opens the app ready to talk back to JARVIS (unlocks the phone first). */
    private void reply() {
        Intent i = new Intent(this, MainActivity.class).putExtra("jarvis_reply", true).putExtra("call_id", id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        KeyguardManager km = getSystemService(KeyguardManager.class);
        if (Build.VERSION.SDK_INT >= 26 && km != null && km.isKeyguardLocked()) {
            km.requestDismissKeyguard(this, new KeyguardManager.KeyguardDismissCallback() {
                @Override public void onDismissSucceeded() { startActivity(i); finish(); }
            });
        } else {
            startActivity(i);
            finish();
        }
    }

    @Override
    protected void onDestroy() {
        stopRinging();
        if (tts != null) { tts.stop(); tts.shutdown(); tts = null; }
        super.onDestroy();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
