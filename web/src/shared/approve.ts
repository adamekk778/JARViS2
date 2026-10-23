// Every "Allow" in the UI goes through this guard. On the PC it is a plain click; the phone app sets it to a
// fingerprint / screen-lock check (3.0), so nothing runs on the PC from a phone without its owner.
let guard: (reason: string) => Promise<boolean> = async () => true;

export function setApproveGuard(fn: (reason: string) => Promise<boolean>) {
  guard = fn;
}

export function guardApprove(reason: string): Promise<boolean> {
  return guard(reason);
}
