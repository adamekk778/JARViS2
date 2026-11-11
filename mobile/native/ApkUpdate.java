package cz.adamekk.jarvis;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 3.12 Aktualizace jedním ťuknutím: the new JARVIS.apk is downloaded into the app's own cache and Android's install
 * dialog opens (Android always asks you – nothing installs on its own). The first time, Android asks to allow
 * "installing from JARVIS".
 */
final class ApkUpdate {
    interface Progress { void on(double p); }

    static long versionCode(Context c) {
        try {
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    /** May this app open the install dialog? If not, the system page to allow it opens and false comes back. */
    static boolean canInstall(Context c) {
        if (Build.VERSION.SDK_INT < 26 || c.getPackageManager().canRequestPackageInstalls()) return true;
        Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + c.getPackageName()))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        c.startActivity(i);
        return false;
    }

    static File download(Context c, String url, Progress progress) throws Exception {
        if (!url.startsWith("https://github.com/") && !url.startsWith("https://objects.githubusercontent.com/"))
            throw new IllegalArgumentException("aktualizace jen z GitHubu JARVISe");
        File dir = new File(c.getCacheDir(), "updates");
        dir.mkdirs();
        File out = new File(dir, "JARVIS.apk");
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setInstanceFollowRedirects(true);
        con.setConnectTimeout(20000);
        con.setReadTimeout(60000);
        long total = con.getContentLengthLong(), got = 0, last = 0;
        try (InputStream in = con.getInputStream(); FileOutputStream fo = new FileOutputStream(out)) {
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = in.read(buf)) > 0) {
                fo.write(buf, 0, n);
                got += n;
                if (total > 0 && got - last > total / 50) { last = got; progress.on((double) got / total); }
            }
        } finally {
            con.disconnect();
        }
        if (out.length() < 5_000_000) { out.delete(); throw new IllegalStateException("stažený soubor není aplikace JARVIS"); }
        return out;
    }

    static void openInstaller(Context c, File apk) {
        Uri uri = FileProvider.getUriForFile(c, c.getPackageName() + ".fileprovider", apk);
        Intent i = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        c.startActivity(i);
    }
}
