"""EVE Online SSO (OAuth 2) login and saving fits to a character's in-game fittings.

Needs EVE_CLIENT_ID and EVE_CLIENT_SECRET from developers.eveonline.com, with the
callback URL set to https://<your site>/sso/callback and the scope below.
The login lives in the pilot's signed session cookie; nothing is stored in the database.
"""
import base64
import json
import os
import secrets
import time
from urllib.parse import urlencode

from esi import ESI, session as http

AUTHORIZE = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN = "https://login.eveonline.com/v2/oauth/token"
SCOPES = "esi-fittings.write_fittings.v1 esi-skills.read_skills.v1"
SKILLS_SCOPE = "esi-skills.read_skills.v1"
CLIENT_ID = os.environ.get("EVE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("EVE_CLIENT_SECRET", "").strip()

# ESI slot names for each slot group on the site, and how many slots each can have
SLOT_FLAGS = {"high": ("HiSlot", 8), "mid": ("MedSlot", 8), "low": ("LoSlot", 8),
              "rig": ("RigSlot", 3), "subsystem": ("SubSystemSlot", 4)}
BAY_FLAGS = {"drones": "DroneBay", "fighters": "FighterBay", "cargo": "Cargo"}

KEYS = ("sso_char_id", "sso_char_name", "sso_access", "sso_refresh", "sso_expires", "sso_scopes")
_skill_cache = {}  # character id -> (fetched at, skills); short-lived, never saved


class NotLoggedIn(Exception):
    pass


def enabled():
    return bool(CLIENT_ID and CLIENT_SECRET)


def login_url(sess, callback_url):
    state = secrets.token_urlsafe(24)
    sess["sso_state"] = state
    return AUTHORIZE + "?" + urlencode({
        "response_type": "code", "redirect_uri": callback_url, "client_id": CLIENT_ID,
        "scope": SCOPES, "state": state,
    })


def _token_request(data):
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    r = http.post(TOKEN, data=data, timeout=20, headers={
        "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com"})
    r.raise_for_status()
    return r.json()


def _claims(jwt):
    """Read the character from the access token. It came straight from CCP over HTTPS
    in exchange for our secret, so there's no need to check the signature here."""
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _store(sess, tok):
    claims = _claims(tok["access_token"])
    sess["sso_char_id"] = int(claims["sub"].split(":")[-1])
    sess["sso_char_name"] = claims.get("name", "")
    sess["sso_access"] = tok["access_token"]
    sess["sso_refresh"] = tok.get("refresh_token") or sess.get("sso_refresh", "")
    sess["sso_expires"] = int(time.time()) + int(tok.get("expires_in", 1199))
    scp = claims.get("scp") or []
    sess["sso_scopes"] = [scp] if isinstance(scp, str) else list(scp)


def finish_login(sess, code, state):
    expected = sess.pop("sso_state", None)
    if not expected or not secrets.compare_digest(expected, state or ""):
        raise ValueError("Login link expired. Please try again.")
    _store(sess, _token_request({"grant_type": "authorization_code", "code": code}))


def logout(sess):
    for k in KEYS:
        sess.pop(k, None)


def character(sess):
    if sess.get("sso_char_id"):
        return {"id": sess["sso_char_id"], "name": sess.get("sso_char_name", "")}
    return None


def can_read_skills(sess):
    return SKILLS_SCOPE in (sess.get("sso_scopes") or [])


def pilot_skills(sess):
    """{skill_id: (trained level, active level)} for the logged-in pilot, or None if not available.
    Active is lower than trained when an alpha clone is holding a skill back."""
    if not sess.get("sso_char_id") or not can_read_skills(sess):
        return None
    cid = sess["sso_char_id"]
    hit = _skill_cache.get(cid)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    try:
        token = _access_token(sess)
        r = http.get(f"{ESI}/characters/{cid}/skills/", params={"datasource": "tranquility"},
                     timeout=15, headers={"Authorization": f"Bearer {token}"})
        if r.status_code in (401, 403):
            sess["sso_scopes"] = [s for s in sess.get("sso_scopes", []) if s != SKILLS_SCOPE]
            return None
        r.raise_for_status()
    except NotLoggedIn:
        return None
    except Exception:
        return hit[1] if hit else None
    skills = {s["skill_id"]: (int(s.get("trained_skill_level", 0)), int(s.get("active_skill_level", 0)))
              for s in r.json().get("skills", [])}
    if len(_skill_cache) > 500:
        _skill_cache.clear()
    _skill_cache[cid] = (time.time(), skills)
    return skills


def _access_token(sess):
    if not sess.get("sso_char_id"):
        raise NotLoggedIn()
    if sess.get("sso_expires", 0) - 60 > time.time():
        return sess["sso_access"]
    if not sess.get("sso_refresh"):
        logout(sess)
        raise NotLoggedIn()
    try:
        _store(sess, _token_request({"grant_type": "refresh_token", "refresh_token": sess["sso_refresh"]}))
    except Exception:
        logout(sess)
        raise NotLoggedIn()
    return sess["sso_access"]


def build_fitting(name, description, layout):
    """Turn a site layout into ESI's fitting format. Returns (body, skipped item names)."""
    items, skipped = [], []
    for kind, (prefix, limit) in SLOT_FLAGS.items():
        for i, it in enumerate(layout["groups"][kind]):
            if it["empty"]:
                continue
            if not it["type_id"] or i >= limit:
                skipped.append(it["name"])
                continue
            items.append({"type_id": it["type_id"], "flag": f"{prefix}{i}", "quantity": 1})
    for kind, flag in BAY_FLAGS.items():
        bay = {}
        for it in layout["groups"][kind]:
            if it["empty"]:
                continue
            if not it["type_id"]:
                skipped.append(it["name"])
                continue
            bay[it["type_id"]] = bay.get(it["type_id"], 0) + max(1, it["qty"])
        items += [{"type_id": t, "flag": flag, "quantity": q} for t, q in bay.items()]
    skipped += [it["name"] for it in layout["groups"]["implants"] if not it["empty"]]
    body = {"name": name[:50], "description": (description or name)[:500],
            "ship_type_id": layout["ship_id"], "items": items}
    return body, skipped


def save_fitting(sess, body):
    """Save one fit to the logged-in character. Returns (ok, message)."""
    token = _access_token(sess)
    r = http.post(f"{ESI}/characters/{sess['sso_char_id']}/fittings/", params={"datasource": "tranquility"},
                  json=body, timeout=20, headers={"Authorization": f"Bearer {token}"})
    if r.status_code in (200, 201):
        return True, "Saved"
    try:
        err = r.json().get("error", "")
    except ValueError:
        err = r.text[:200]
    if r.status_code in (401, 403):
        if "scope" in err.lower() or r.status_code == 403:
            logout(sess)
            raise NotLoggedIn()
    if "maximum" in err.lower() or "too many" in err.lower() or "limit" in err.lower():
        return False, "Your fittings are full (EVE allows 500). Delete some in game and try again."
    return False, f"EVE said no ({r.status_code}){': ' + err if err else ''}"
