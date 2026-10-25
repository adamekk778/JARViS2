// Thin wrappers over Capacitor plugins; everything degrades gracefully in a normal browser.
import { Capacitor, registerPlugin } from "@capacitor/core";

export interface ShareEvent { title: string; texts: string[]; files: { uri: string; name: string; mimeType: string }[] }

const isNative = Capacitor.isNativePlatform();
// 3.4 the app's own native part (mobile/native/*.java): background link, "JARVIS volá", dialing, SMS, notification mirror
const JarvisPhone: any = isNative ? registerPlugin("JarvisPhone") : null;
export interface PhoneStatus { running: boolean; enabled: boolean; mirror: boolean; phone: boolean; notifAccess: boolean; fullScreen: boolean; battery: boolean; overlay: boolean }
let notifyId = 1;
let actionsRegistered = false;

export const native = {
  isNative,

  phone: {
    available: isNative,
    configure: (o: { base?: string; token?: string; enabled?: boolean; mirror?: boolean }): Promise<PhoneStatus> => JarvisPhone.configure(o),
    status: (): Promise<PhoneStatus> => JarvisPhone.status(),
    requestPhone: (): Promise<PhoneStatus> => JarvisPhone.requestPhone(),
    openNotificationAccess: () => JarvisPhone.openNotificationAccess(),
    openFullScreen: () => JarvisPhone.openFullScreen(),
    openBattery: () => JarvisPhone.openBattery(),
    openOverlay: () => JarvisPhone.openOverlay(),
    handle: (cmd: any): Promise<{ state: string }> => JarvisPhone.handle({ cmd }),
    onReply: (cb: (d: { callId: string }) => void) => {
      JarvisPhone.addListener("reply", cb);
      JarvisPhone.takePendingReply().then((r: any) => r.reply && cb(r)).catch(() => {});
    },
  },

  deviceName(): string {
    const ua = navigator.userAgent;
    const m = ua.match(/Android [\d.]+; ([^;)]+)/);
    return m ? m[1].trim() : "Telefon";
  },

  async scanQr(): Promise<string | null> {
    const { BarcodeScanner, BarcodeFormat } = await import("@capacitor-mlkit/barcode-scanning");
    const avail = await BarcodeScanner.isGoogleBarcodeScannerModuleAvailable().catch(() => ({ available: true }));
    if (!avail.available) {
      await BarcodeScanner.installGoogleBarcodeScannerModule();
      throw new Error("Stahuji modul skeneru od Googlu, zkus to za chvilku znovu.");
    }
    const { barcodes } = await BarcodeScanner.scan({ formats: [BarcodeFormat.QrCode] });
    return barcodes[0]?.rawValue ?? null;
  },

  async askNotifyPermission() {
    if (!isNative) return Notification?.requestPermission?.();
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    await LocalNotifications.requestPermissions();
  },

  async notify(title: string, body: string) {
    if (localStorage.getItem("jarvis.notify") === "0") return;
    try {
      if (isNative) {
        const { LocalNotifications } = await import("@capacitor/local-notifications");
        await LocalNotifications.schedule({ notifications: [{ id: notifyId++, title, body }] });
      } else if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body });
      }
    } catch { /* ignore */ }
  },

  /** Fingerprint / face / screen lock before an "Allow" (3.0). In a plain browser there is nothing to check. */
  async verify(reason: string): Promise<boolean> {
    if (!isNative) return true;
    try {
      const { NativeBiometric } = await import("@capgo/capacitor-native-biometric");
      const av = await NativeBiometric.isAvailable({ useFallback: true }).catch(() => ({ isAvailable: false }));
      if (!av.isAvailable) return window.confirm(`${reason}\n\nTelefon nemá nastavený otisk ani zámek obrazovky. Povolit i tak?`);
      await NativeBiometric.verifyIdentity({ title: "Potvrdit v JARVISovi", subtitle: reason.slice(0, 90), negativeButtonText: "Zrušit", maxAttempts: 3 });
      return true;
    } catch {
      return false;
    }
  },

  /** A notification with Povolit / Zamítnout buttons; both open the app (Povolit then asks for the fingerprint). */
  async notifyApproval(title: string, body: string, extra: Record<string, string>) {
    if (localStorage.getItem("jarvis.notify") === "0") return;
    try {
      if (isNative) {
        const { LocalNotifications } = await import("@capacitor/local-notifications");
        if (!actionsRegistered) {
          actionsRegistered = true;
          await LocalNotifications.registerActionTypes({ types: [{ id: "approve", actions: [
            { id: "allow", title: "Povolit", foreground: true }, { id: "deny", title: "Zamítnout", foreground: true }] }] });
        }
        await LocalNotifications.schedule({ notifications: [{ id: notifyId++, title, body, actionTypeId: "approve", extra }] });
      } else await this.notify(title, body);
    } catch { /* ignore */ }
  },

  onApprovalAction(cb: (action: string, extra: Record<string, string>) => void) {
    if (!isNative) return;
    import("@capacitor/local-notifications").then(({ LocalNotifications }) =>
      LocalNotifications.addListener("localNotificationActionPerformed", (ev: any) => cb(ev.actionId, ev.notification?.extra || {}))).catch(() => {});
  },

  haptic() {
    if (!isNative) return;
    import("@capacitor/haptics").then(({ Haptics, ImpactStyle }) => Haptics.impact({ style: ImpactStyle.Light })).catch(() => {});
  },

  onResume(cb: () => void) {
    document.addEventListener("visibilitychange", () => !document.hidden && cb());
    window.addEventListener("online", cb);
    if (isNative) import("@capacitor/app").then(({ App }) => App.addListener("resume", cb)).catch(() => {});
  },

  onShare(cb: (ev: ShareEvent) => void) {
    if (!isNative) return;
    import("@capgo/capacitor-share-target")
      .then(({ CapacitorShareTarget }) => CapacitorShareTarget.addListener("shareReceived", (ev: any) => cb({ title: ev.title || "", texts: ev.texts || [], files: ev.files || [] })))
      .catch(() => {});
  },

  async readShared(f: { uri: string; name: string; mimeType: string }): Promise<Blob> {
    if (f.uri.startsWith("data:") || f.uri.startsWith("http") || f.uri.startsWith("blob:")) return (await fetch(f.uri)).blob();
    try {
      return await (await fetch(Capacitor.convertFileSrc(f.uri))).blob();
    } catch {
      const { Filesystem } = await import("@capacitor/filesystem");
      const r = await Filesystem.readFile({ path: f.uri });
      const data = typeof r.data === "string" ? Uint8Array.from(atob(r.data), (ch) => ch.charCodeAt(0)) : r.data;
      return new Blob([data as BlobPart], { type: f.mimeType || "application/octet-stream" });
    }
  },
};
