"""3.12 Mailchimp: seznamy kontaktů (kolik odběratelů) a kampaně s výsledky (otevření, kliknutí) – jen čtení."""
from __future__ import annotations

from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value


def base() -> str:
    key = value("mailchimp", "key")
    if "-" not in key:
        raise ServiceError("Mailchimp klíč končí „-us…“ (např. …-us21) – zkopíruj ho celý.")
    return f"https://{key.rsplit('-', 1)[1]}.api.mailchimp.com/3.0"


async def _api(path: str, transport=None, **params) -> Any:
    need("mailchimp")
    return await call("GET", base() + path, params=params or None, transport=transport, auth=("jarvis", value("mailchimp", "key")))


async def _test(rt: Any) -> str:
    r = await _api("/")
    return f"Propojeno – účet {r.get('account_name', '?')}, {r.get('total_subscribers', '?')} odběratelů."


register("mailchimp", "Mailchimp (newslettery)", "megaphone", [
    {"key": "key", "label": "API key", "secret": True, "hint": "…-us21"},
], [
    "V Mailchimpu: profil → Account & billing → Extras → API keys → Create A Key.",
    "Zkopíruj celý klíč (končí -us…) sem a ulož.",
], url="https://admin.mailchimp.com/account/api/", what="Seznamy odběratelů a výsledky kampaní – jen čtení.", test=_test, group="sales",
    probe={"method": "GET", "url": "https://us1.api.mailchimp.com/3.0/", "auth": ["jarvis", "FAKE-us1"]})


@tool("mailchimp_audiences", "Mailchimp: seznamy kontaktů – počet odběratelů, průměrné otevření.", category="propojení", perm="network")
@guarded
async def audiences(ctx) -> ToolResult:
    r = await _api("/lists", count=50)
    out = [{"name": x.get("name"), "members": (x.get("stats") or {}).get("member_count"), "unsubscribed": (x.get("stats") or {}).get("unsubscribe_count"),
            "open_rate": (x.get("stats") or {}).get("open_rate"), "click_rate": (x.get("stats") or {}).get("click_rate")} for x in r.get("lists", [])]
    return ToolResult(True, f"{len(out)} seznamů.", data=out)


@tool("mailchimp_campaigns", "Mailchimp: poslední kampaně a jejich výsledky (otevření, kliknutí).", category="propojení", perm="network")
@guarded
async def campaigns(ctx, limit: Annotated[int, "kolik"] = 10) -> ToolResult:
    r = await _api("/campaigns", count=max(1, min(int(limit or 10), 50)), sort_field="send_time", sort_dir="DESC")
    out = [{"subject": (c.get("settings") or {}).get("subject_line"), "status": c.get("status"), "sent": c.get("send_time"),
            "recipients": c.get("emails_sent"), "open_rate": (c.get("report_summary") or {}).get("open_rate"),
            "click_rate": (c.get("report_summary") or {}).get("click_rate")} for c in r.get("campaigns", [])]
    return ToolResult(True, f"{len(out)} kampaní.", data=out)
