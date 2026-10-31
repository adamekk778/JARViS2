"""3.4 e-mail: IMAP/SMTP accounts (Seznam, Gmail, Centrum, Atlas, iCloud or any other).

The password is an app password kept in the system keyring. JARVIS keeps one IMAP connection per account open and
checks it every few seconds (NOOP), so a new e-mail is announced within ~20 s. Sending always goes through a tool
that asks first (the e-mail is shown in full before it leaves).
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import email.utils
import imaplib
import logging
import re
import smtplib
import ssl
import threading
import time
import uuid
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Any

from . import secrets

log = logging.getLogger(__name__)

PRESETS: dict[str, dict[str, Any]] = {
    "seznam": {"label": "Seznam (Email.cz)", "imap_host": "imap.seznam.cz", "imap_port": 993, "smtp_host": "smtp.seznam.cz", "smtp_port": 465,
               "help": "Na email.seznam.cz → Nastavení → Hesla pro aplikace vytvoř heslo pro JARVISe (bez dvoufázového ověření stačí běžné heslo)."},
    "gmail": {"label": "Gmail", "imap_host": "imap.gmail.com", "imap_port": 993, "smtp_host": "smtp.gmail.com", "smtp_port": 465,
              "help": "Účet Google → Zabezpečení → Dvoufázové ověření → Hesla aplikací → vytvoř heslo „JARVIS“ (16 písmen)."},
    "centrum": {"label": "Centrum.cz", "imap_host": "imap.centrum.cz", "imap_port": 993, "smtp_host": "smtp.centrum.cz", "smtp_port": 465,
                "help": "V nastavení pošty zapni přístup přes IMAP."},
    "atlas": {"label": "Atlas.cz", "imap_host": "imap.atlas.cz", "imap_port": 993, "smtp_host": "smtp.atlas.cz", "smtp_port": 465,
              "help": "V nastavení pošty zapni přístup přes IMAP."},
    "icloud": {"label": "iCloud", "imap_host": "imap.mail.me.com", "imap_port": 993, "smtp_host": "smtp.mail.me.com", "smtp_port": 587,
               "help": "appleid.apple.com → Hesla pro aplikace."},
    "custom": {"label": "Jiný (IMAP)", "imap_host": "", "imap_port": 993, "smtp_host": "", "smtp_port": 465, "help": ""},
}


def guess_provider(address: str) -> str:
    dom = address.rsplit("@", 1)[-1].lower()
    if dom in ("seznam.cz", "email.cz", "post.cz", "spoluzaci.cz", "stream.cz", "firmy.cz"):
        return "seznam"
    if dom in ("gmail.com", "googlemail.com"):
        return "gmail"
    if dom in ("centrum.cz", "centrum.sk"):
        return "centrum"
    if dom == "atlas.cz":
        return "atlas"
    if dom in ("icloud.com", "me.com", "mac.com"):
        return "icloud"
    return "custom"


def dec(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def sender(from_header: str) -> tuple[str, str]:
    name, addr = email.utils.parseaddr(dec(from_header))
    return (name or addr.split("@")[0]), addr.lower()


def body_text(msg: email.message.EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        from .powers import page_text

        text = page_text(text)
    # drop the quoted history of replies ("> …" lines and "Dne … napsal(a):" blocks)
    lines, out = text.splitlines(), []
    for ln in lines:
        if re.match(r"^\s*(Dne .+napsal|On .+wrote:|-----Original Message-----|-------- Původní zpráva)", ln):
            break
        if not ln.startswith(">"):
            out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def is_newsletter(headers: email.message.Message, addr: str) -> bool:
    if headers.get("List-Unsubscribe") or (headers.get("Precedence") or "").lower() in ("bulk", "list", "junk"):
        return True
    return bool(re.match(r"^(no-?reply|newsletter|news|info|marketing|notifications?|mailer-daemon)@", addr))


class Account:
    """One mailbox. Every IMAP call runs in a worker thread under the account's lock."""

    def __init__(self, cfg, password_getter=None):
        self.cfg = cfg
        self.lock = threading.RLock()
        self.conn: imaplib.IMAP4 | None = None
        self._password = password_getter or (lambda: secrets.get(f"mail:{cfg.id}"))
        self.last_uid = 0
        self.error = ""

    # ---------- connection ----------
    def imap(self) -> imaplib.IMAP4:
        if self.conn is not None:
            try:
                self.conn.noop()
                return self.conn
            except Exception:
                self.close()
        c = imaplib.IMAP4_SSL(self.cfg.imap_host, self.cfg.imap_port, ssl_context=ssl.create_default_context(), timeout=30)
        c.login(self.cfg.address, self._password())
        self.conn = c
        return c

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.logout()
        except Exception:
            pass
        self.conn = None

    def folder(self, flag: str, fallbacks: tuple[str, ...]) -> str | None:
        """A special folder by its flag (\\Sent, \\Trash) or a common name."""
        c = self.imap()
        typ, rows = c.list()
        names = []
        for raw in rows or []:
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            m = re.match(r'\((?P<flags>[^)]*)\) "?(?P<sep>[^" ]*)"? (?P<name>.+)$', line)
            if not m:
                continue
            name = m.group("name").strip().strip('"')
            if flag.lower() in m.group("flags").lower():
                return name
            names.append(name)
        return next((n for n in names if n.lower() in fallbacks), None)

    # ---------- reading ----------
    def _headers(self, c, uids: list[bytes]) -> list[dict]:
        if not uids:
            return []
        typ, data = c.uid("FETCH", b",".join(uids), "(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE "
                                                    "MESSAGE-ID LIST-UNSUBSCRIBE PRECEDENCE)])")
        out = []
        for item in data or []:
            if not isinstance(item, tuple):
                continue
            meta = item[0].decode("utf-8", "replace")
            uid = int(re.search(r"UID (\d+)", meta).group(1))
            h = email.message_from_bytes(item[1], policy=email.policy.compat32)
            name, addr = sender(h.get("From", ""))
            try:
                ts = email.utils.parsedate_to_datetime(h.get("Date")).timestamp()
            except Exception:
                ts = 0.0
            out.append({"id": f"{self.cfg.id}:{uid}", "uid": uid, "from_name": name, "from": addr, "subject": dec(h.get("Subject")) or "(bez předmětu)",
                        "date": ts, "unread": "\\Seen" not in meta, "newsletter": is_newsletter(h, addr), "account": self.cfg.address})
        out.sort(key=lambda m: -m["uid"])
        return out

    def list(self, unread: bool = False, limit: int = 10, query: str = "", folder: str = "INBOX") -> list[dict]:
        with self.lock:
            c = self.imap()
            c.select(f'"{folder}"' if " " in folder else folder, readonly=True)
            if query:
                c.literal = query.encode("utf-8")
                crit = ("UNSEEN", "TEXT") if unread else ("TEXT",)
                typ, data = c.uid("SEARCH", "CHARSET", "UTF-8", *crit)
            else:
                typ, data = c.uid("SEARCH", "UNSEEN" if unread else "ALL")
            uids = (data[0] or b"").split()[-max(1, limit):]
            return self._headers(c, uids)

    def read(self, uid: int, mark_seen: bool = True) -> dict:
        with self.lock:
            c = self.imap()
            c.select("INBOX", readonly=not mark_seen)
            typ, data = c.uid("FETCH", str(uid), "(BODY.PEEK[])" if not mark_seen else "(BODY[])")
            raw = next((x[1] for x in data or [] if isinstance(x, tuple)), None)
            if raw is None:
                raise LookupError("Ten e-mail už ve schránce není.")
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            name, addr = sender(msg.get("From", ""))
            files = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
            return {"id": f"{self.cfg.id}:{uid}", "uid": uid, "from_name": name, "from": addr, "to": dec(msg.get("To")),
                    "subject": dec(msg.get("Subject")), "date": dec(msg.get("Date")), "text": body_text(msg)[:20000],
                    "attachments": files, "message_id": msg.get("Message-ID", ""), "references": msg.get("References", ""),
                    "reply_to": email.utils.parseaddr(dec(msg.get("Reply-To") or ""))[1].lower() or addr}

    def attachment_bytes(self, uid: int, max_mb: float = 25) -> list[tuple[str, bytes]]:
        """OMEGA 545: the attachments' content (read-only peek) – to find the same / a similar file in the PC."""
        with self.lock:
            c = self.imap()
            c.select("INBOX", readonly=True)
            _typ, data = c.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((x[1] for x in data or [] if isinstance(x, tuple)), None)
        if raw is None:
            return []
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        out = []
        for part in msg.iter_attachments():
            name = part.get_filename()
            body = part.get_payload(decode=True) or b""
            if name and len(body) <= max_mb * 2**20:
                out.append((name, body))
        return out

    def set_flag(self, uid: int, flag: str = "\\Seen", on: bool = True) -> None:
        with self.lock:
            c = self.imap()
            c.select("INBOX")
            c.uid("STORE", str(uid), "+FLAGS" if on else "-FLAGS", f"({flag})")

    def trash(self, uid: int) -> None:
        with self.lock:
            c = self.imap()
            c.select("INBOX")
            tr = self.folder("\\Trash", ("trash", "koš", "kos", "deleted items", "[gmail]/trash", "[gmail]/koš"))
            if tr:
                c.uid("COPY", str(uid), f'"{tr}"')
            c.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
            c.expunge()

    def new_since_last(self) -> list[dict]:
        """New e-mails since the previous check (the first check only remembers where we are)."""
        with self.lock:
            c = self.imap()
            c.select("INBOX", readonly=True)
            typ, data = c.uid("SEARCH", "ALL")
            uids = [int(u) for u in (data[0] or b"").split()]
            top = max(uids, default=0)
            if not self.last_uid:
                self.last_uid = top
                return []
            fresh = [str(u).encode() for u in uids if u > self.last_uid]
            self.last_uid = max(top, self.last_uid)
            return self._headers(c, fresh)

    def contacts(self, name: str, limit: int = 300) -> list[tuple[str, str, int]]:
        """People whose name or address matches, from the From: of recent mail: [(name, address, count)]."""
        with self.lock:
            c = self.imap()
            c.select("INBOX", readonly=True)
            c.literal = name.encode("utf-8")
            typ, data = c.uid("SEARCH", "CHARSET", "UTF-8", "FROM")
            uids = (data[0] or b"").split()[-limit:]
            seen: dict[str, list] = {}
            for m in self._headers(c, uids):
                e = seen.setdefault(m["from"], [m["from_name"], m["from"], 0])
                e[2] += 1
            return sorted((tuple(v) for v in seen.values()), key=lambda x: -x[2])

    # ---------- sending ----------
    def send(self, to: str, subject: str, body: str, in_reply_to: str = "", references: str = "") -> str:
        msg = EmailMessage()
        msg["From"] = email.utils.formataddr((self.cfg.name, self.cfg.address)) if self.cfg.name else self.cfg.address
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=self.cfg.address.rsplit("@", 1)[-1])
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = (references + " " + in_reply_to).strip()
        msg.set_content(body)
        ctx = ssl.create_default_context()
        if self.cfg.smtp_port == 465:
            with smtplib.SMTP_SSL(self.cfg.smtp_host, 465, context=ctx, timeout=30) as s:
                s.login(self.cfg.address, self._password())
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(self.cfg.address, self._password())
                s.send_message(msg)
        if self.cfg.provider != "gmail":   # Gmail files sent mail itself; elsewhere put a copy into Sent
            try:
                with self.lock:
                    sent = self.folder("\\Sent", ("sent", "odeslané", "odeslane", "sent items", "sent messages"))
                    if sent:
                        self.imap().append(f'"{sent}"', "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            except Exception as e:
                log.debug("copy to Sent: %s", e)
        return msg["Message-ID"]


def test_login(cfg, password: str) -> None:
    """Raises with a readable reason when the address/password/server is wrong."""
    acc = Account(cfg, lambda: password)
    try:
        acc.imap().select("INBOX", readonly=True)
    except imaplib.IMAP4.error as e:
        raise ValueError("Přihlášení nevyšlo – zkontroluj adresu a heslo pro aplikace (" + str(e)[:120] + ")") from e
    except OSError as e:
        raise ValueError(f"Nepodařilo se spojit se serverem {cfg.imap_host}: {e}") from e
    finally:
        acc.close()


class Mail:
    """All accounts + the new-mail watcher."""

    def __init__(self, rt):
        self.rt = rt
        self.accounts: dict[str, Account] = {}
        self.recent: list[dict] = []        # last announced e-mails (for "co mi přišlo")
        self._task: asyncio.Task | None = None
        self.sync()

    def sync(self) -> None:
        want = {a.id: a for a in self.rt.cfg.mail.accounts}
        for aid in list(self.accounts):
            if aid not in want or self.accounts[aid].cfg != want[aid]:
                self.accounts.pop(aid).close()
        for aid, cfg in want.items():
            self.accounts.setdefault(aid, Account(cfg))

    def account(self, which: str = "") -> Account:
        self.sync()
        if not self.accounts:
            raise LookupError("Nemám připojený žádný e-mail. Přidej ho v okně JARVIS → E-mail a kalendář.")
        if not which:
            return next(iter(self.accounts.values()))
        for a in self.accounts.values():
            if which in (a.cfg.id, a.cfg.address) or which.lower() in a.cfg.address.lower():
                return a
        raise LookupError(f"Účet {which} neznám.")

    def by_id(self, mid: str) -> tuple[Account, int]:
        aid, _, uid = mid.rpartition(":")
        self.sync()
        acc = self.accounts.get(aid) or self.account()
        return acc, int(uid)

    def is_vip(self, m: dict) -> bool:
        who = f"{m.get('from_name', '')} {m.get('from', '')}".lower()
        return any(v.strip() and v.strip().lower() in who for v in self.rt.cfg.mail.vip)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        for a in self.accounts.values():
            a.close()

    async def check(self) -> list[dict]:
        cfg = self.rt.cfg.mail
        self.sync()
        fresh: list[dict] = []
        for acc in list(self.accounts.values()):
            try:
                got = await asyncio.to_thread(acc.new_since_last)
                acc.error = ""
            except Exception as e:
                acc.error = str(e)[:200]
                acc.close()
                log.debug("mail check %s: %s", acc.cfg.address, e)
                continue
            fresh += got
        for m in fresh:
            m["vip"] = self.is_vip(m)
            self.recent = ([m] + self.recent)[:30]
            if m["newsletter"] and cfg.ignore_newsletters and not m["vip"]:
                continue
            self.rt.bus.publish("mail_new", **m)
            if cfg.notify:
                who = m["from_name"] or m["from"]
                title = "Důležitý e-mail" if m["vip"] else "Nový e-mail"
                self.rt.notify(title, f"Píše vám {who}: {m['subject']}", speak=cfg.speak and self.rt.cfg.voice.speak_mode != "never")
            if m["vip"] and cfg.call_vip and getattr(self.rt, "phone", None):
                await self.rt.phone.ring(f"Pane, přišel důležitý e-mail od {m['from_name'] or m['from']}: {m['subject']}.", reason="mail")
        return fresh

    async def _loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            if self.rt.cfg.mail.accounts:
                try:
                    await self.check()
                except Exception as e:
                    log.debug("mail loop: %s", e)
            await asyncio.sleep(max(10, self.rt.cfg.mail.check_seconds))

    def status(self) -> list[dict]:
        self.sync()
        return [{"id": a.cfg.id, "address": a.cfg.address, "provider": a.cfg.provider, "error": a.error,
                 "connected": a.conn is not None} for a in self.accounts.values()]


def new_account_id() -> str:
    return uuid.uuid4().hex[:8]
