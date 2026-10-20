"""Local model settings. Never execute .env contents or print credentials."""
from __future__ import annotations

import getpass
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .data import ROOT

KEYS = ("INSIGHTOPS_BASE_URL", "INSIGHTOPS_MODEL", "INSIGHTOPS_API_KEY")
DEFAULT_BASE = "https://api.openai.com/v1"


def validate_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Use an endpoint URL without credentials, query or fragment")
    if not parts.hostname:
        raise ValueError("Endpoint must have a hostname")
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")):
        raise ValueError("Use HTTPS, or HTTP on localhost only")
    return value.rstrip("/")


def load_settings(path: Path | None = None) -> dict[str, str]:
    path = path or ROOT / ".env"
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or name not in KEYS:
                continue
            value = value.strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid quoted configuration for {name}") from None
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            if not isinstance(value, str) or "\n" in value or "\r" in value:
                raise ValueError(f"Invalid configuration for {name}")
            values[name] = value
    for name in KEYS:
        if os.environ.get(name):
            values[name] = os.environ[name]
    return values


def configuration_status(path: Path | None = None) -> dict:
    settings = load_settings(path)
    return {"api_key_configured":bool(settings.get("INSIGHTOPS_API_KEY")),
            "model":settings.get("INSIGHTOPS_MODEL"),
            "base_url":settings.get("INSIGHTOPS_BASE_URL", DEFAULT_BASE),
            "ready":bool(settings.get("INSIGHTOPS_API_KEY") and settings.get("INSIGHTOPS_MODEL")),
            "network_request_sent":False}


def probe_configuration(path: Path | None = None) -> dict:
    """Read model metadata without sending a generation request or printing keys."""
    settings=load_settings(path)
    status=configuration_status(path)
    if not status["ready"]:
        return status
    base=validate_base_url(settings.get("INSIGHTOPS_BASE_URL",DEFAULT_BASE))
    request=urllib.request.Request(base+"/models",headers={"Authorization":"Bearer "+settings["INSIGHTOPS_API_KEY"]})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            data=json.load(response)
            identifiers=[item["id"] for item in data.get("data",[]) if isinstance(item,dict) and "id" in item]
            return {**status,"network_request_sent":True,"http_status":response.status,
                    "configured_model_available":settings["INSIGHTOPS_MODEL"] in identifiers,
                    "available_model_ids":identifiers}
    except urllib.error.HTTPError as error:
        return {**status,"network_request_sent":True,"http_status":error.code}
    except Exception as error:
        return {**status,"network_request_sent":True,"error_type":type(error).__name__}


def configure(path: Path | None = None) -> dict:
    path = path or ROOT / ".env"
    current = load_settings(path)
    base = input(f"API base URL [{current.get('INSIGHTOPS_BASE_URL', DEFAULT_BASE)}]: ").strip() or current.get("INSIGHTOPS_BASE_URL", DEFAULT_BASE)
    base = validate_base_url(base)
    model = input(f"Exact model ID [{current.get('INSIGHTOPS_MODEL', '')}]: ").strip() or current.get("INSIGHTOPS_MODEL", "")
    key = getpass.getpass("API key (hidden; Enter keeps existing key): ").strip() or current.get("INSIGHTOPS_API_KEY", "")
    if not key or not model:
        raise ValueError("API key and exact model ID are required; nothing was saved")
    settings = dict(zip(KEYS, [base, model, key]))
    if any("\n" in value or "\r" in value for value in settings.values()):
        raise ValueError("Multiline settings are not allowed")
    # Do not silently create a potentially publishable credential file.
    if ".env" not in (path.parent / ".gitignore").read_text(encoding="utf-8").splitlines():
        raise ValueError("The project .gitignore must explicitly ignore .env before saving")
    path.write_text("# Local credentials. Never commit or share this file.\n" + "\n".join(name+"="+json.dumps(value) for name,value in settings.items()) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return configuration_status(path)
