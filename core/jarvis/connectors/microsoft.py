"""3.12 Microsoft 365: Outlook (e-maily), Kalendář, OneDrive, To Do a kontakty – osobní účet (outlook.com, hotmail)
i firemní/školní. Sign-in in the browser with your own free app registration (PKCE, no secret). Reading is free;
sending a mail, an invitation or adding a task asks first."""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import call, guarded, register
from .oauth import Pkce

GRAPH = "https://graph.microsoft.com/v1.0"
REDIRECT_HOST = "localhost"            # Microsoft accepts http://localhost for desktop apps (any port)
SCOPES = "offline_access User.Read Mail.ReadWrite Mail.Send Calendars.ReadWrite Files.ReadWrite Contacts.Read Tasks.ReadWrite"
AUTH = Pkce("microsoft", "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "https://login.microsoftonline.com/common/oauth2/v2.0/token", SCOPES, scope_on_token=True,
            extra={"response_mode": "query", "prompt": "select_account"}, name="Microsoft")
start, finish = AUTH.start, AUTH.finish


async def _api(method: str, path: str, transport=None, **kw) -> Any:
    hdrs = {**await AUTH.headers(transport), "Prefer": 'outlook.timezone="Europe/Prague", outlook.body-content-type="text"',
            **kw.pop("headers", {})}
    url = path if path.startswith("http") else GRAPH + path
    return await call(method, url, headers=hdrs, transport=transport, **kw)


async def _test(rt: Any) -> str:
    me = await _api("GET", "/me?$select=displayName,mail,userPrincipalName")
    return f"Přihlášeno jako {me.get('displayName') or ''} ({me.get('mail') or me.get('userPrincipalName') or '?'})."


register("microsoft", "Microsoft 365 (Outlook, OneDrive, To Do)", "microsoft-outlook-logo", [
    {"key": "client_id", "label": "Application (client) ID", "secret": False, "hint": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
], [
    "Otevři portal.azure.com → Microsoft Entra ID → App registrations → New registration (stačí osobní Microsoft účet).",
    "Název JARVIS, Supported account types: „Accounts in any organizational directory and personal Microsoft accounts“.",
    "Redirect URI: platforma „Public client/native (mobile & desktop)“, adresa přesně: http://localhost:8765/api/oauth/microsoft",
    "Register → zkopíruj „Application (client) ID“ sem a ulož.",
    "Klikni „Přihlásit se Microsoftem“ a povol přístup.",
], url="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade", oauth=True,
    what="Outlook e-maily (číst, koncepty, odeslat s potvrzením), kalendář, soubory na OneDrive, úkoly v To Do a kontakty.",
    test=_test, group="work", prefixes=("outlook_", "onedrive_", "mstodo_"), login="Přihlásit se Microsoftem",
    probe={"method": "GET", "url": GRAPH + "/me", "headers": {"Authorization": "Bearer FAKE"}})


def _addr(x: dict) -> str:
    e = (x or {}).get("emailAddress") or {}
    return f"{e.get('name', '')} <{e.get('address', '')}>".strip()


def _plain(html: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


# ---------------------------------------------------------------- Outlook mail
@tool("outlook_mail_search", "Outlook: najde e-maily (text, odesílatel) – bez textu ukáže poslední doručené.",
      category="propojení", perm="network")
@guarded
async def mail_search(ctx, query: Annotated[str, "co hledat (prázdné = poslední e-maily)"] = "",
                      unread: Annotated[bool, "jen nepřečtené"] = False, limit: Annotated[int, "kolik (max 30)"] = 15) -> ToolResult:
    n = max(1, min(int(limit or 15), 30))
    params: dict[str, Any] = {"$top": n, "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead,hasAttachments"}
    if query.strip():
        params["$search"] = '"' + query.replace('"', " ").strip() + '"'
    else:
        params["$orderby"] = "receivedDateTime desc"
        if unread:       # Graph: a property in $orderby must also be in $filter, first ("InefficientFilter" otherwise)
            params["$filter"] = "receivedDateTime ge 2000-01-01T00:00:00Z and isRead eq false"
    r = await _api("GET", "/me/mailFolders/inbox/messages" if not query.strip() else "/me/messages", params=params)
    items = [{"id": m["id"], "from": _addr(m.get("from")), "subject": m.get("subject"), "date": m.get("receivedDateTime"),
              "unread": not m.get("isRead"), "preview": (m.get("bodyPreview") or "")[:200]} for m in r.get("value", [])]
    if unread and query.strip():
        items = [i for i in items if i["unread"]]
    return ToolResult(True, f"{len(items)} e-mailů.", data=items)


@tool("outlook_mail_read", "Outlook: přečte celý e-mail podle id.", category="propojení", perm="network")
@guarded
async def mail_read(ctx, message_id: Annotated[str, "id e-mailu z outlook_mail_search"]) -> ToolResult:
    m = await _api("GET", f"/me/messages/{message_id}",
                   params={"$select": "subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments"})
    body = m.get("body") or {}
    text = body.get("content", "") if body.get("contentType") == "text" else _plain(body.get("content", ""))
    return ToolResult(True, m.get("subject") or "(bez předmětu)", data={
        "from": _addr(m.get("from")), "to": [_addr(x) for x in m.get("toRecipients", [])], "cc": [_addr(x) for x in m.get("ccRecipients", [])],
        "date": m.get("receivedDateTime"), "subject": m.get("subject"), "attachments": m.get("hasAttachments"), "text": text[:12000]})


def _message(to: str, subject: str, body: str, cc: str = "") -> dict:
    rec = lambda s: [{"emailAddress": {"address": x.strip()}} for x in (s or "").split(",") if x.strip()]  # noqa: E731
    return {"subject": subject, "body": {"contentType": "Text", "content": body}, "toRecipients": rec(to), "ccRecipients": rec(cc)}


def _mail_details(a: dict) -> list[str]:
    return [f"Komu: {a.get('to', '')}", *([f"Kopie: {a['cc']}"] if a.get("cc") else []), f"Předmět: {a.get('subject', '')}", "",
            *str(a.get("body", "")).splitlines()[:30]]


@tool("outlook_mail_send", "Outlook: odešle e-mail (nebo odpověď – pak dej reply_to id). Zeptá se uživatele.", danger=True,
      category="propojení", perm="network", details=_mail_details)
@guarded
async def mail_send(ctx, to: Annotated[str, "příjemci (e-maily oddělené čárkou)"], subject: Annotated[str, "předmět"],
                    body: Annotated[str, "text e-mailu"], cc: Annotated[str, "kopie (nepovinné)"] = "",
                    reply_to: Annotated[str, "id e-mailu, na který odpovídáš (nepovinné)"] = "") -> ToolResult:
    if reply_to:
        await _api("POST", f"/me/messages/{reply_to}/reply", json={"message": {k: v for k, v in _message(to, subject, body, cc).items()
                                                                             if k != "subject"}})
    else:
        await _api("POST", "/me/sendMail", json={"message": _message(to, subject, body, cc), "saveToSentItems": True})
    return ToolResult(True, f"E-mail odeslán ({to}).")


@tool("outlook_mail_draft", "Outlook: uloží koncept e-mailu do Konceptů (nic neodešle).", category="propojení", perm="network")
@guarded
async def mail_draft(ctx, to: Annotated[str, "příjemci"], subject: Annotated[str, "předmět"], body: Annotated[str, "text"],
                     cc: Annotated[str, "kopie"] = "") -> ToolResult:
    m = await _api("POST", "/me/messages", json=_message(to, subject, body, cc))
    return ToolResult(True, "Koncept je v Outlooku.", data={"id": m.get("id"), "link": m.get("webLink")})


# ---------------------------------------------------------------- calendar
@tool("outlook_calendar_events", "Outlook Kalendář: události na dny dopředu (od dneška).", category="propojení", perm="network")
@guarded
async def calendar_events(ctx, days: Annotated[int, "kolik dní dopředu"] = 7) -> ToolResult:
    now = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    r = await _api("GET", "/me/calendarView", params={
        "startDateTime": now.isoformat(), "endDateTime": (now + dt.timedelta(days=max(1, min(int(days or 7), 60)))).isoformat(),
        "$orderby": "start/dateTime", "$top": 80, "$select": "subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,webLink"})
    out = [{"title": e.get("subject"), "start": (e.get("start") or {}).get("dateTime"), "end": (e.get("end") or {}).get("dateTime"),
            "where": (e.get("location") or {}).get("displayName"), "organizer": _addr(e.get("organizer")),
            "people": [_addr(a) for a in e.get("attendees", [])][:10],
            "online": ((e.get("onlineMeeting") or {}).get("joinUrl")) if e.get("isOnlineMeeting") else None} for e in r.get("value", [])]
    return ToolResult(True, f"{len(out)} událostí.", data=out)


@tool("outlook_calendar_create", "Outlook Kalendář: vytvoří událost (pozvaní dostanou pozvánku, volitelně schůzka v Teams). "
      "Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Událost: {a.get('title', '')}", f"Od: {a.get('start', '')}", f"Do: {a.get('end', '')}",
                         f"Pozvaní: {a.get('attendees', '') or 'nikdo'}", *(["Online schůzka v Teams"] if a.get("teams") else [])])
@guarded
async def calendar_create(ctx, title: Annotated[str, "název"], start: Annotated[str, "začátek, např. 2026-11-20T10:00:00"],
                          end: Annotated[str, "konec"], attendees: Annotated[str, "e-maily oddělené čárkou"] = "",
                          description: Annotated[str, "popis"] = "", location: Annotated[str, "místo"] = "",
                          teams: Annotated[bool, "online schůzka v Teams"] = False) -> ToolResult:
    tz = "Central Europe Standard Time"
    body: dict[str, Any] = {"subject": title, "body": {"contentType": "Text", "content": description},
                            "start": {"dateTime": start[:19], "timeZone": tz}, "end": {"dateTime": end[:19], "timeZone": tz},
                            "attendees": [{"emailAddress": {"address": x.strip()}, "type": "required"} for x in attendees.split(",") if x.strip()]}
    if location:
        body["location"] = {"displayName": location}
    if teams:
        body.update(isOnlineMeeting=True, onlineMeetingProvider="teamsForBusiness")
    e = await _api("POST", "/me/events", json=body)
    return ToolResult(True, f"Událost „{title}“ je v kalendáři.", data={"link": e.get("webLink"),
                                                                     "teams": (e.get("onlineMeeting") or {}).get("joinUrl")})


@tool("outlook_contacts_search", "Outlook: najde kontakt (jméno → e-mail, telefon).", category="propojení", perm="network")
@guarded
async def contacts_search(ctx, query: Annotated[str, "jméno nebo část e-mailu"]) -> ToolResult:
    r = await _api("GET", "/me/contacts", params={"$top": 500, "$select": "displayName,emailAddresses,mobilePhone,businessPhones,companyName"})
    q = query.lower().strip()
    hit = [c for c in r.get("value", []) if q in (c.get("displayName") or "").lower() or q in (c.get("companyName") or "").lower()
           or any(q in (e.get("address") or "").lower() for e in c.get("emailAddresses", []))]
    out = [{"name": c.get("displayName"), "emails": [e.get("address") for e in c.get("emailAddresses", [])],
            "phone": c.get("mobilePhone") or (c.get("businessPhones") or [None])[0], "company": c.get("companyName")} for c in hit[:20]]
    return ToolResult(True, f"{len(out)} kontaktů.", data=out)


# ---------------------------------------------------------------- OneDrive
@tool("onedrive_search", "OneDrive: najde soubory podle názvu nebo obsahu.", category="propojení", perm="network")
@guarded
async def drive_search(ctx, query: Annotated[str, "co hledat"]) -> ToolResult:
    q = query.replace("'", "''")
    r = await _api("GET", f"/me/drive/root/search(q='{q}')", params={"$top": 25, "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder"})
    out = [{"id": f["id"], "name": f.get("name"), "folder": "folder" in f, "size": f.get("size"), "modified": f.get("lastModifiedDateTime"),
            "url": f.get("webUrl")} for f in r.get("value", [])]
    return ToolResult(True, f"{len(out)} souborů.", data=out)


def docx_text(raw: bytes) -> str:
    """The text of a Word document (no extra library)."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()


@tool("onedrive_read", "OneDrive: přečte textový soubor nebo dokument Word (.docx) podle id.", category="propojení", perm="network")
@guarded
async def drive_read(ctx, file_id: Annotated[str, "id souboru z onedrive_search"]) -> ToolResult:
    from . import http

    meta = await _api("GET", f"/me/drive/items/{file_id}", params={"$select": "name,size,file"})
    name = meta.get("name", "")
    if (meta.get("size") or 0) > 15_000_000:
        return ToolResult(False, f"{name} je moc velký na přečtení ({meta['size'] // 1_000_000} MB).")
    async with http() as c:
        r = await c.get(f"{GRAPH}/me/drive/items/{file_id}/content", headers=await AUTH.headers(), follow_redirects=True)
        r.raise_for_status()
    if name.lower().endswith(".docx"):
        text = docx_text(r.content)
    else:
        text = r.content.decode("utf-8", "replace")
    return ToolResult(True, name, data={"name": name, "text": text[:15000]})


# ---------------------------------------------------------------- To Do
async def _lists() -> list[dict]:
    return (await _api("GET", "/me/todo/lists")).get("value", [])


@tool("mstodo_tasks", "Microsoft To Do: nesplněné úkoly (ze všech seznamů nebo z jednoho).", category="propojení", perm="network")
@guarded
async def todo_tasks(ctx, list_name: Annotated[str, "název seznamu (prázdné = všechny)"] = "") -> ToolResult:
    out = []
    for lst in await _lists():
        if list_name and list_name.lower() not in (lst.get("displayName") or "").lower():
            continue
        r = await _api("GET", f"/me/todo/lists/{lst['id']}/tasks", params={"$filter": "status ne 'completed'", "$top": 50})
        out += [{"list": lst.get("displayName"), "title": t.get("title"), "due": ((t.get("dueDateTime") or {}).get("dateTime") or "")[:10] or None,
                 "important": t.get("importance") == "high"} for t in r.get("value", [])]
    return ToolResult(True, f"{len(out)} úkolů.", data=out)


@tool("mstodo_add", "Microsoft To Do: přidá úkol. Zeptá se uživatele.", danger=True, category="propojení", perm="network",
      details=lambda a: [f"Úkol: {a.get('title', '')}", f"Termín: {a.get('due', '') or '–'}", f"Seznam: {a.get('list_name', '') or 'výchozí'}"])
@guarded
async def todo_add(ctx, title: Annotated[str, "úkol"], due: Annotated[str, "termín YYYY-MM-DD (nepovinné)"] = "",
                   list_name: Annotated[str, "seznam (prázdné = výchozí)"] = "") -> ToolResult:
    lists = await _lists()
    lst = next((x for x in lists if list_name and list_name.lower() in (x.get("displayName") or "").lower()), None) \
        or next((x for x in lists if x.get("wellknownListName") == "defaultList"), None) or (lists[0] if lists else None)
    if not lst:
        return ToolResult(False, "V To Do není žádný seznam.")
    body: dict[str, Any] = {"title": title}
    if due:
        body["dueDateTime"] = {"dateTime": f"{due[:10]}T12:00:00", "timeZone": "Central Europe Standard Time"}
    await _api("POST", f"/me/todo/lists/{lst['id']}/tasks", json=body)
    return ToolResult(True, f"Úkol „{title}“ je v To Do ({lst.get('displayName')}).")
