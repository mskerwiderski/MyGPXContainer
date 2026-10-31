"""Every marked text has a German translation, and the language follows MyAuth."""

import ast
import re
from pathlib import Path

from app import i18n

APP = Path(__file__).parent.parent / "app"
_TEMPLATE_TEXT = re.compile(r"""\b_\(\s*(["'])(.+?)\1""", re.S)


def marked_texts() -> set[str]:
    found = set()
    for py in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant)):
                found.add(node.args[0].value)
    for tpl in (APP / "templates").rglob("*.html"):
        found |= {m.group(2) for m in _TEMPLATE_TEXT.finditer(tpl.read_text())}
    return found


def test_texts_are_found():
    texts = marked_texts()
    assert "Routes" in texts and "No access" in texts


def test_every_marked_text_is_translated():
    missing = sorted(marked_texts() - set(i18n.DE))
    assert not missing, f"missing in i18n.DE: {missing}"


def test_no_unused_translations():
    unused = sorted(set(i18n.DE) - marked_texts())
    assert not unused, f"unused in i18n.DE: {unused}"


def test_placeholders_match():
    for en, de in i18n.DE.items():
        assert set(re.findall(r"\{(\w+)\}", en)) == set(re.findall(r"\{(\w+)\}", de)), en


def test_pick_prefers_myauth_language():
    assert i18n.pick({"language": "de"}, "en-US") == "de"
    assert i18n.pick({"language": "fr"}, "de-DE") == "en"   # signed in: MyAuth decides
    assert i18n.pick(None, "de-DE,de;q=0.9") == "de"
    assert i18n.pick(None, "") == "en"


def test_german_page(client, myauth):
    myauth.body = {**myauth.body, "language": "de"}
    client.cookies.set("sso_session", "abc")
    r = client.get("/")
    assert '<html lang="de">' in r.text
    assert "Noch keine Routen" in r.text and "Abmelden" in r.text


def test_german_error_page(client, myauth):
    myauth.status, myauth.body = 403, {"detail": "app_not_allowed"}
    client.cookies.set("sso_session", "abc")
    r = client.get("/", headers={"accept-language": "de"})
    assert "Kein Zugriff" in r.text
