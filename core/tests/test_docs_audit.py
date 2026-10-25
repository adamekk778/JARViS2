"""The OMEGA feature audit stays complete: all 795 catalogue items, valid states, no excluded brand anywhere in docs."""
import importlib.util
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _mod():
    spec = importlib.util.spec_from_file_location("build_audit", DOCS / "audit" / "build_audit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_catalogue_complete_and_states_valid():
    m = _mod()
    sections, names = m.catalog()
    assert len(names) == 795 and sorted(names) == list(range(1, 796)) and len(sections) == 58
    st = m.statuses()
    assert set(st) <= set(names)
    assert len(m.original()) >= 110


def test_generated_audit_is_current():
    audit = (DOCS / "FEATURE_AUDIT.md").read_text(encoding="utf-8")
    m = _mod()
    for n, (s, _) in list(m.statuses().items())[:50]:
        assert re.search(rf"\| {n:03d} \| .* \| \S+ {s} \|", audit), f"{n} není v FEATURE_AUDIT.md aktuální – spusť build_audit.py"


EXCLUDED = bytes([118, 101, 120, 101, 108]).decode()   # the excluded platform's name (not written out on purpose)


def test_no_excluded_brand_anywhere():
    root = DOCS.parent
    files = [p for d in ("docs", "core/jarvis", "web/src", "mobile/native", "packaging", ".github") for p in (root / d).rglob("*")
             if p.is_file() and p.suffix in (".md", ".py", ".ts", ".css", ".html", ".java", ".yml", ".iss", ".spec", ".json")]
    assert files
    for p in files:
        assert EXCLUDED not in p.read_text(encoding="utf-8", errors="ignore").lower(), p
