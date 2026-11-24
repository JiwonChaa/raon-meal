"""Fixed account routing shared by the publisher and performance collector."""
import json
import os

PROFILES = {
    "ko": ("phyedu_net", "ko", "shorts", "IG_SECRETS_JSON"),
    "en": ("phyedu_en", "en", "shorts-en", "IG_EN_SECRETS_JSON"),
    "cut": ("phyedu.cut", "ko", "shorts-cut", "IG_CUT_SECRETS_JSON"),
}


def selected_profile():
    # Preserve the existing language-only entry points and English default.
    profile = os.environ.get("REEL_ACCOUNT", os.environ.get("REEL_LANGUAGE", "en"))
    if profile not in PROFILES:
        raise RuntimeError("Unsupported Reel account")
    account, language, directory, secret = PROFILES[profile]
    if os.environ.get("REEL_LANGUAGE", language) != language:
        raise RuntimeError("Reel account/language mismatch")
    return account, language, directory, secret


def read_credentials(account, secret_name):
    raw = os.environ.get(secret_name, "")
    if not raw:
        raise RuntimeError("Dedicated Reel Instagram secret is missing")
    try:
        value = json.loads(raw)
        if account == "phyedu_net":
            value = dict(value["accounts"][account], username=account)
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("Dedicated Reel Instagram secret is invalid") from None
    if not isinstance(value, dict):
        raise RuntimeError("Dedicated Reel Instagram secret is invalid")
    if (value.get("username") != account or not value.get("user_id")
            or not isinstance(value.get("access_token"), str) or not value["access_token"]):
        raise RuntimeError("Reel credentials do not identify the expected account")
    if not str(value["user_id"]).isdigit():
        raise RuntimeError("Invalid Instagram account ID")
    return value
