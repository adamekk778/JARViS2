// Thin wrappers over Capacitor plugins; everything degrades gracefully in a normal browser.
import { Capacitor } from "@capacitor/core";

export interface ShareEvent { title: string; texts: string[]; files: { uri: string; name: string; mimeType: string }[] }

const isNative = Capacitor.isNativePlatform();
let notifyId = 1;

export const native = {
  isNative,

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
        await LocalNotifications.schedule({ notifications: [{ id: notifyId++, title, body, smallIcon: "ic_stat_jarvis" }] });
      } else if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body });
      }
    } catch { /* ignore */ }
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
