// Every "Allow" in the UI goes through this guard. On the PC it is a plain click; the phone app sets it to a
// fingerprint / screen-lock check (3.0), so nothing runs on the PC from a phone without its owner.
let guard: (reason: string) => Promise<boolean> = async () => true;

export function setApproveGuard(fn: (reason: string) => Promise<boolean>) {
  guard = fn;
}

export function guardApprove(reason: string): Promise<boolean> {
  return guard(reason);
}

/** 3.20 (196) dangerous steps approved only with a touch of the YubiKey: the key types its one-time code into the box. */
export function askOtp(needed: unknown): string | null | undefined {
  if (!needed) return undefined;
  const v = (window.prompt("Dotkni se svého YubiKey – kód napíše sám:") || "").trim();
  return v || null;
}
