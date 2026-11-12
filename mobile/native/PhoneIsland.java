package cz.adamekk.jarvis;

import android.animation.LayoutTransition;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * 3.12 Notch na telefonu: a small black island at the top of the screen, over other apps (like the PC's notch). It
 * shows JARVIS's eyes and the one thing that matters now on the PC – thinking/speaking, a song, a timer, "JARVIS
 * ovládá PC". Tap = open JARVIS, hold = talk. It asks the PC every few seconds only while the screen is on and hides
 * while the JARVIS app itself is open. Needs "Zobrazovat přes jiné aplikace"; switched on in the app (Více → Telefon).
 */
final class PhoneIsland {
    private static PhoneIsland active;
    private static final int POLL_MS = 3000;

    private final Context ctx;
    private final WindowManager wm;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private LinearLayout pill;
    private View eyeL, eyeR, dot;
    private TextView text, sub;
    private boolean attached, polling, busy;
    private int blinkTick;

    private PhoneIsland(Context c) {
        ctx = c.getApplicationContext();
        wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
    }

    static boolean enabled(Context c) { return JarvisLink.prefs(c).getBoolean("island", false); }

    static synchronized void start(Context c) {
        if (active != null) return;
        if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(c)) return;   // the user has not allowed it (yet)
        PhoneIsland p = new PhoneIsland(c);
        active = p;
        p.ui.post(p::attach);
    }

    static synchronized void stop() {
        if (active == null) return;
        PhoneIsland p = active;
        active = null;
        p.ui.post(p::detach);
    }

    // ---------- the view ----------
    private int dp(float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, ctx.getResources().getDisplayMetrics()));
    }

    private View eye() {
        View v = new View(ctx);
        GradientDrawable g = new GradientDrawable();
        g.setColor(Color.WHITE);
        g.setCornerRadius(dp(3));
        v.setBackground(g);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(5), dp(10));
        lp.setMargins(dp(2), 0, dp(2), 0);
        v.setLayoutParams(lp);
        return v;
    }

    private void attach() {
        pill = new LinearLayout(ctx);
        pill.setOrientation(LinearLayout.HORIZONTAL);
        pill.setGravity(Gravity.CENTER_VERTICAL);
        pill.setPadding(dp(14), 0, dp(14), 0);
        pill.setMinimumWidth(dp(84));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.BLACK);
        bg.setCornerRadius(dp(18));
        pill.setBackground(bg);
        pill.setElevation(dp(6));
        LayoutTransition lt = new LayoutTransition();
        lt.enableTransitionType(LayoutTransition.CHANGING);
        pill.setLayoutTransition(lt);

        dot = new View(ctx);
        GradientDrawable dg = new GradientDrawable();
        dg.setShape(GradientDrawable.OVAL);
        dg.setColor(0xFF0A84FF);
        dot.setBackground(dg);
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(dp(7), dp(7));
        dlp.setMargins(0, 0, dp(8), 0);
        dot.setLayoutParams(dlp);
        dot.setVisibility(View.GONE);

        text = new TextView(ctx);
        text.setTextColor(Color.WHITE);
        text.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        text.setSingleLine(true);
        text.setVisibility(View.GONE);
        sub = new TextView(ctx);
        sub.setTextColor(0x99FFFFFF);
        sub.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        sub.setSingleLine(true);
        sub.setPadding(dp(6), 0, 0, 0);
        sub.setVisibility(View.GONE);

        LinearLayout eyes = new LinearLayout(ctx);
        eyes.setGravity(Gravity.CENTER);
        eyeL = eye();
        eyeR = eye();
        eyes.addView(eyeL);
        eyes.addView(eyeR);
        LinearLayout.LayoutParams elp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        elp.setMargins(dp(10), 0, 0, 0);

        pill.addView(dot);
        pill.addView(text);
        pill.addView(sub);
        pill.addView(eyes, elp);

        pill.setOnClickListener(v -> open(null));
        pill.setOnLongClickListener(v -> { open("jarvis://open/talk"); return true; });

        int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY : WindowManager.LayoutParams.TYPE_PHONE;
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT, dp(34), type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        lp.y = statusBar() + dp(4);              // just under the status bar, right below the camera
        try {
            wm.addView(pill, lp);
            attached = true;
        } catch (Exception e) {
            attached = false;
            return;
        }
        IntentFilter f = new IntentFilter(Intent.ACTION_SCREEN_OFF);
        f.addAction(Intent.ACTION_SCREEN_ON);
        try { ctx.registerReceiver(screen, f); } catch (Exception ignored) { }
        resume();
    }

    private int statusBar() {
        int id = ctx.getResources().getIdentifier("status_bar_height", "dimen", "android");
        return id > 0 ? ctx.getResources().getDimensionPixelSize(id) : dp(24);
    }

    private void detach() {
        polling = false;
        ui.removeCallbacksAndMessages(null);
        try { ctx.unregisterReceiver(screen); } catch (Exception ignored) { }
        if (attached) {
            try { wm.removeView(pill); } catch (Exception ignored) { }
            attached = false;
        }
    }

    private void open(String link) {
        Intent i = link == null ? new Intent(ctx, MainActivity.class) : new Intent(Intent.ACTION_VIEW, Uri.parse(link)).setClass(ctx, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        try { ctx.startActivity(i); } catch (Exception ignored) { }
    }

    // ---------- saving the battery: only while the screen is on ----------
    private final BroadcastReceiver screen = new BroadcastReceiver() {
        @Override
        public void onReceive(Context c, Intent i) {
            if (Intent.ACTION_SCREEN_OFF.equals(i.getAction())) { polling = false; ui.removeCallbacks(tick); }
            else resume();
        }
    };

    private void resume() {
        if (polling) return;
        PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
        if (pm != null && !pm.isInteractive()) return;
        polling = true;
        ui.post(tick);
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!polling || !attached) return;
            pill.setVisibility(MainActivity.visible ? View.GONE : View.VISIBLE);   // the app itself is open: step aside
            blink();
            if (!MainActivity.visible && !busy) {
                busy = true;
                new Thread(() -> {
                    JSONObject st = null;
                    try { st = new JSONObject(JarvisLink.http(ctx, "GET", "/api/phone/island", null, 5000)); } catch (Exception ignored) { }
                    final JSONObject s = st;
                    ui.post(() -> { busy = false; show(s); });
                }, "jarvis-island").start();
            }
            ui.postDelayed(this, POLL_MS);
        }
    };

    private void blink() {
        if (++blinkTick % 2 != 0) return;
        for (View e : new View[] { eyeL, eyeR }) {
            e.animate().scaleY(0.15f).setDuration(90).withEndAction(() -> e.animate().scaleY(1f).setDuration(110).start()).start();
        }
    }

    private void show(JSONObject s) {
        if (!attached) return;
        String kind = s == null ? "offline" : s.optString("kind", "idle");
        String t = s == null ? "" : s.optString("text", "");
        String st = s == null ? "" : s.optString("sub", "");
        int color;
        switch (kind) {
            case "music": color = 0xFF30D158; break;
            case "timer": color = 0xFFFF9F0A; break;
            case "rec": color = 0xFFFF453A; break;
            default: color = 0xFF0A84FF;
        }
        ((GradientDrawable) dot.getBackground()).setColor(color);
        boolean has = !t.isEmpty();
        dot.setVisibility(has ? View.VISIBLE : View.GONE);
        text.setVisibility(has ? View.VISIBLE : View.GONE);
        sub.setVisibility(has && !st.isEmpty() ? View.VISIBLE : View.GONE);
        text.setText(t);
        sub.setText(st);
        float a = "offline".equals(kind) ? 0.35f : 1f;          // the PC is off / away: dimmed eyes
        eyeL.setAlpha(a);
        eyeR.setAlpha(a);
    }
}
