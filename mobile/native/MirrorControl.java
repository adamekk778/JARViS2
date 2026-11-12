package cz.adamekk.jarvis;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Build;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONObject;

/**
 * 3.12 Telefon na monitoru PC – the mouse and keyboard part. An accessibility service you switch on once
 * (Nastavení → Přístupnost → JARVIS). It does nothing by itself: it only performs the clicks and typing that your PC
 * sends while "Telefon na monitoru" runs (with its notification visible). It reads no content of other apps.
 */
public class MirrorControl extends AccessibilityService {
    private static volatile MirrorControl instance;

    static boolean ready() { return instance != null; }

    @Override
    protected void onServiceConnected() { instance = this; }

    @Override
    public boolean onUnbind(android.content.Intent intent) {
        instance = null;
        return super.onUnbind(intent);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) { }

    @Override
    public void onInterrupt() { }

    /** One input from the PC: x/y are 0–1 of the phone's screen. Only while the mirror runs. */
    static void perform(JSONObject m) {
        MirrorControl s = instance;
        if (s == null || !MirrorService.running) return;
        try {
            s.run(m);
        } catch (Exception ignored) { }
    }

    @SuppressWarnings("deprecation")
    private float[] px(double x, double y) {
        DisplayMetrics d = new DisplayMetrics();
        android.hardware.display.DisplayManager dm = getSystemService(android.hardware.display.DisplayManager.class);
        dm.getDisplay(android.view.Display.DEFAULT_DISPLAY).getRealMetrics(d);
        return new float[] { (float) (Math.max(0, Math.min(1, x)) * (d.widthPixels - 1)), (float) (Math.max(0, Math.min(1, y)) * (d.heightPixels - 1)) };
    }

    private void gesture(float x1, float y1, float x2, float y2, long ms) {
        Path p = new Path();
        p.moveTo(x1, y1);
        if (x1 != x2 || y1 != y2) p.lineTo(x2, y2);
        dispatchGesture(new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(p, 0, Math.max(1, ms))).build(), null, null);
    }

    private void run(JSONObject m) {
        String k = m.optString("kind");
        switch (k) {
            case "tap":
            case "long": {
                float[] a = px(m.optDouble("x"), m.optDouble("y"));
                gesture(a[0], a[1], a[0], a[1], "long".equals(k) ? 650 : 50);
                break;
            }
            case "swipe": {
                float[] a = px(m.optDouble("x1"), m.optDouble("y1"));
                float[] b = px(m.optDouble("x2"), m.optDouble("y2"));
                gesture(a[0], a[1], b[0], b[1], Math.max(80, Math.min(1500, m.optLong("ms", 250))));
                break;
            }
            case "back": performGlobalAction(GLOBAL_ACTION_BACK); break;
            case "home": performGlobalAction(GLOBAL_ACTION_HOME); break;
            case "recents": performGlobalAction(GLOBAL_ACTION_RECENTS); break;
            case "notifications": performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS); break;
            case "text": edit(m.optString("text"), false); break;
            case "backspace": edit("", true); break;
            case "enter": {
                AccessibilityNodeInfo f = findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
                if (f != null && Build.VERSION.SDK_INT >= 30) f.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId());
                break;
            }
            default: break;
        }
    }

    /** Typing from the PC's keyboard into the field that has the focus on the phone. */
    private void edit(String add, boolean back) {
        AccessibilityNodeInfo f = findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (f == null || !f.isEditable()) return;
        CharSequence cur = f.getText();
        String now = cur == null || (Build.VERSION.SDK_INT >= 26 && f.isShowingHintText()) ? "" : cur.toString();
        if (back) now = now.isEmpty() ? now : now.substring(0, now.length() - 1);
        else now = now + (add.length() > 500 ? add.substring(0, 500) : add);
        Bundle b = new Bundle();
        b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, now);
        f.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b);
    }
}
