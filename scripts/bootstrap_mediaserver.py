#!/usr/bin/env python3

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


REMOTE_BASE_DIR = Path("{{REMOTE_BASE_DIR}}")
PUBLIC_HOST = "{{PUBLIC_HOST}}"
PUBLIC_BASE_URL = "{{PUBLIC_BASE_URL}}"

TRANSMISSION_HOST = "{{TRANSMISSION_HOST}}"
TRANSMISSION_PORT = int("{{TRANSMISSION_RPC_PORT}}")

LIDARR_PORT = int("{{LIDARR_PORT}}")
RADARR_PORT = int("{{RADARR_PORT}}")
SONARR_PORT = int("{{SONARR_PORT}}")
PROWLARR_PORT = int("{{PROWLARR_PORT}}")
JELLYSEERR_PORT = int("{{JELLYSEERR_PORT}}")
JELLYFIN_PORT = int("{{JELLYFIN_PORT}}")

RADARR_EXTERNAL_URL = "{{RADARR_EXTERNAL_URL}}"
SONARR_EXTERNAL_URL = "{{SONARR_EXTERNAL_URL}}"
JELLYFIN_EXTERNAL_URL = "{{JELLYFIN_EXTERNAL_URL}}"
JELLYFIN_FORGOT_PASSWORD_URL = "{{JELLYFIN_FORGOT_PASSWORD_URL}}"

JELLYFIN_SERVER_NAME = "{{JELLYFIN_SERVER_NAME}}"
JELLYFIN_ADMIN_USERNAME = "{{JELLYFIN_ADMIN_USERNAME}}"
JELLYFIN_ADMIN_PASSWORD = "{{JELLYFIN_ADMIN_PASSWORD}}"
JELLYSEERR_APPLICATION_TITLE = "{{JELLYSEERR_APPLICATION_TITLE}}"
BOOTSTRAP_TIMEOUT_SECONDS = int("{{BOOTSTRAP_TIMEOUT_SECONDS}}")

MEDIA_ROOT = REMOTE_BASE_DIR / "mediaserver"
TOOLS_DIR = MEDIA_ROOT / "tools"
JELLYSEERR_SETTINGS_PATH = TOOLS_DIR / "jellyseerr" / "settings.json"

ARR_CONFIGS = {
    "lidarr": {
        "config_path": TOOLS_DIR / "lidarr" / "config.xml",
        "api_path": "/lidarr/api/v1",
        "port": LIDARR_PORT,
        "download_field": "musicCategory",
        "download_category": "",
        "application_name": "Lidarr",
        "application_base_url": "http://lidarr:8686",
        "external_url": f"{PUBLIC_BASE_URL}/lidarr",
    },
    "radarr": {
        "config_path": TOOLS_DIR / "radarr" / "config.xml",
        "api_path": "/radarr/api/v3",
        "port": RADARR_PORT,
        "download_field": "movieCategory",
        "download_category": "radarr",
        "application_name": "Radarr",
        "application_base_url": "http://radarr:7878",
        "external_url": RADARR_EXTERNAL_URL,
    },
    "sonarr": {
        "config_path": TOOLS_DIR / "sonarr" / "config.xml",
        "api_path": "/sonarr/api/v3",
        "port": SONARR_PORT,
        "download_field": "tvCategory",
        "download_category": "tv-sonarr",
        "application_name": "Sonarr",
        "application_base_url": "http://sonarr:8989",
        "external_url": SONARR_EXTERNAL_URL,
    },
}


def log(message: str) -> None:
    print(f"[bootstrap] {message}", flush=True)


def request_json(method: str, path: str, *, headers=None, payload=None, expected=(200, 201, 202), allow_empty=False):
    url = f"http://127.0.0.1{path}"
    data = None
    req_headers = {"Host": PUBLIC_HOST}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            if response.status not in expected:
                raise RuntimeError(f"{method} {path} returned {response.status}: {body[:400]}")
            if not body:
                return None if allow_empty else {}
            return json.loads(body)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned {error.code}: {body[:400]}") from error


def request_text(method: str, path: str, *, headers=None, payload=None, expected=(200, 201, 202)):
    url = f"http://127.0.0.1{path}"
    data = None
    req_headers = {"Host": PUBLIC_HOST}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            if response.status not in expected:
                raise RuntimeError(f"{method} {path} returned {response.status}: {body[:400]}")
            return body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned {error.code}: {body[:400]}") from error


def wait_for(path: str, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            request_text("GET", path, expected=(200, 204))
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {path}")


def wait_for_file(path: Path, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for file {path}")


def get_xml_value(config_path: Path, tag: str) -> str:
    tree = ET.parse(config_path)
    node = tree.find(f".//{tag}")
    if node is None or node.text is None:
        raise RuntimeError(f"Missing <{tag}> in {config_path}")
    return node.text.strip()


def get_arr_api_key(app_key: str) -> str:
    return get_xml_value(ARR_CONFIGS[app_key]["config_path"], "ApiKey")


def find_by_implementation(items, implementation: str):
    for item in items:
        if item.get("implementation") == implementation or item.get("implementationName") == implementation:
            return item
    return None


def set_field(item: dict, name: str, value):
    for field in item.get("fields", []):
        if field.get("name") == name:
            field["value"] = value
            return


def bootstrap_download_client(app_key: str, api_key: str) -> None:
    cfg = ARR_CONFIGS[app_key]
    headers = {"X-Api-Key": api_key}
    clients = request_json("GET", f"{cfg['api_path']}/downloadclient", headers=headers)
    transmission = find_by_implementation(clients, "Transmission")

    if transmission is None:
        schema = request_json("GET", f"{cfg['api_path']}/downloadclient/schema", headers=headers)
        transmission = find_by_implementation(schema, "Transmission")
        if transmission is None:
            raise RuntimeError(f"Transmission schema not found for {app_key}")
        transmission.pop("presets", None)
        transmission["name"] = "Transmission"
        method = "POST"
    else:
        method = "PUT"

    transmission["enable"] = True
    transmission["priority"] = 1
    transmission["removeCompletedDownloads"] = True
    transmission["removeFailedDownloads"] = True
    set_field(transmission, "host", TRANSMISSION_HOST)
    set_field(transmission, "port", TRANSMISSION_PORT)
    set_field(transmission, "useSsl", False)
    set_field(transmission, "urlBase", "transmission")
    set_field(transmission, "username", "")
    set_field(transmission, "password", "")
    set_field(transmission, cfg["download_field"], cfg["download_category"])

    request_json(method, f"{cfg['api_path']}/downloadclient", headers=headers, payload=transmission, expected=(200, 201, 202))
    log(f"{cfg['application_name']}: download client linked to Transmission")


def bootstrap_prowlarr_application(app_key: str, api_key: str, prowlarr_api_key: str) -> None:
    cfg = ARR_CONFIGS[app_key]
    headers = {"X-Api-Key": prowlarr_api_key}
    applications = request_json("GET", "/prowlarr/api/v1/applications", headers=headers)
    current = None
    for app in applications:
        if app.get("name") == cfg["application_name"]:
            current = app
            break

    if current is None:
        schema = request_json("GET", "/prowlarr/api/v1/applications/schema", headers=headers)
        current = find_by_implementation(schema, cfg["application_name"])
        if current is None:
            raise RuntimeError(f"Prowlarr schema not found for {cfg['application_name']}")
        method = "POST"
        current["name"] = cfg["application_name"]
    else:
        method = "PUT"

    current["enable"] = True
    current["syncLevel"] = "fullSync"
    set_field(current, "prowlarrUrl", f"http://prowlarr:{PROWLARR_PORT}")
    set_field(current, "baseUrl", cfg["application_base_url"])
    set_field(current, "apiKey", api_key)

    request_json(method, "/prowlarr/api/v1/applications", headers=headers, payload=current, expected=(200, 201, 202))
    log(f"Prowlarr: linked {cfg['application_name']}")


def get_public_system_info() -> dict:
    return request_json("GET", "/jellyfin/System/Info/Public")


def ensure_jellyfin_bootstrap() -> None:
    info = get_public_system_info()
    if info.get("StartupWizardCompleted"):
        log("Jellyfin: startup wizard already completed")
        return

    request_json(
        "POST",
        "/jellyfin/Startup/Configuration",
        payload={"ServerName": JELLYFIN_SERVER_NAME, "UICulture": "en-US"},
        expected=(204,),
        allow_empty=True,
    )
    request_json(
        "POST",
        "/jellyfin/Startup/User",
        payload={"Name": JELLYFIN_ADMIN_USERNAME, "Password": JELLYFIN_ADMIN_PASSWORD},
        expected=(204,),
        allow_empty=True,
    )
    request_json("POST", "/jellyfin/Startup/Complete", expected=(204,), allow_empty=True)
    log("Jellyfin: startup wizard completed")


def authenticate_jellyfin_admin() -> str:
    response = request_json(
        "POST",
        "/jellyfin/Users/AuthenticateByName",
        headers={
            "X-Emby-Authorization": 'MediaBrowser Client="bootstrap", Device="deploy", DeviceId="bootstrap", Version="1.0"'
        },
        payload={"Username": JELLYFIN_ADMIN_USERNAME, "Pw": JELLYFIN_ADMIN_PASSWORD},
        expected=(200,),
    )
    token = response.get("AccessToken")
    if not token:
        raise RuntimeError("Jellyfin authentication did not return an access token")
    return token


def create_jellyfin_api_key(access_token: str) -> str:
    headers = {"X-Emby-Token": access_token}
    attempts = [
        ("POST", "/jellyfin/Auth/Keys?app=Jellyseerr"),
        ("POST", "/jellyfin/Auth/Keys?app=MediaServerBootstrap"),
    ]
    for method, path in attempts:
        try:
            body = request_text(method, path, headers=headers, expected=(200, 204, 201))
            if body:
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        for key in ("AccessToken", "Key", "Token"):
                            value = parsed.get(key)
                            if value:
                                return value
                    if isinstance(parsed, str) and parsed:
                        return parsed
                except json.JSONDecodeError:
                    return body.strip()
        except Exception:
            continue
    log("Jellyfin: API key creation failed, falling back to admin access token for Jellyseerr")
    return access_token


def update_jellyseerr_settings(radarr_api_key: str, sonarr_api_key: str, jellyfin_api_key: str) -> None:
    settings = json.loads(JELLYSEERR_SETTINGS_PATH.read_text(encoding="utf-8"))
    settings.setdefault("main", {})
    settings.setdefault("public", {})
    settings["main"]["applicationTitle"] = JELLYSEERR_APPLICATION_TITLE
    settings["main"]["applicationUrl"] = "/jellyseerr"
    settings["main"]["localLogin"] = True
    settings["main"]["newPlexLogin"] = True
    settings["main"]["mediaServerType"] = 2
    settings["public"]["initialized"] = True

    system_info = get_public_system_info()
    settings["jellyfin"] = {
        "name": JELLYFIN_SERVER_NAME,
        "ip": "jellyfin",
        "port": JELLYFIN_PORT,
        "useSsl": False,
        "urlBase": "/jellyfin",
        "externalHostname": JELLYFIN_EXTERNAL_URL,
        "jellyfinForgotPasswordUrl": JELLYFIN_FORGOT_PASSWORD_URL,
        "libraries": settings.get("jellyfin", {}).get("libraries", []),
        "serverId": system_info.get("Id", ""),
        "apiKey": jellyfin_api_key,
    }
    settings["radarr"] = [
        {
            "id": 0,
            "name": "Radarr",
            "hostname": "radarr",
            "port": RADARR_PORT,
            "apiKey": radarr_api_key,
            "useSsl": False,
            "baseUrl": "/radarr",
            "activeProfileId": 1,
            "activeDirectory": "/movies",
            "minimumAvailability": "released",
            "is4k": False,
            "isDefault": True,
            "externalUrl": RADARR_EXTERNAL_URL,
            "syncEnabled": True,
        }
    ]
    settings["sonarr"] = [
        {
            "id": 0,
            "name": "Sonarr",
            "hostname": "sonarr",
            "port": SONARR_PORT,
            "apiKey": sonarr_api_key,
            "useSsl": False,
            "baseUrl": "/sonarr",
            "activeProfileId": 1,
            "activeLanguageProfileId": 1,
            "activeDirectory": "/tv",
            "enableSeasonFolders": True,
            "is4k": False,
            "isDefault": True,
            "externalUrl": SONARR_EXTERNAL_URL,
            "syncEnabled": True,
        }
    ]

    JELLYSEERR_SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    log("Jellyseerr: settings.json wired to Jellyfin, Radarr and Sonarr")


def get_existing_jellyseerr_api_key() -> str:
    if not JELLYSEERR_SETTINGS_PATH.exists():
        return ""
    try:
        settings = json.loads(JELLYSEERR_SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    return settings.get("jellyfin", {}).get("apiKey", "")


def main() -> None:
    wait_for("/dashboard/api/services", BOOTSTRAP_TIMEOUT_SECONDS)
    wait_for("/jellyseerr/api/v1/status", BOOTSTRAP_TIMEOUT_SECONDS)
    wait_for("/radarr/ping", BOOTSTRAP_TIMEOUT_SECONDS)
    wait_for("/sonarr/ping", BOOTSTRAP_TIMEOUT_SECONDS)
    wait_for("/lidarr/ping", BOOTSTRAP_TIMEOUT_SECONDS)
    wait_for("/prowlarr/ping", BOOTSTRAP_TIMEOUT_SECONDS)
    wait_for_file(JELLYSEERR_SETTINGS_PATH, BOOTSTRAP_TIMEOUT_SECONDS)

    ensure_jellyfin_bootstrap()

    lidarr_api_key = get_arr_api_key("lidarr")
    radarr_api_key = get_arr_api_key("radarr")
    sonarr_api_key = get_arr_api_key("sonarr")
    prowlarr_api_key = get_xml_value(TOOLS_DIR / "prowlarr" / "config.xml", "ApiKey")

    bootstrap_download_client("lidarr", lidarr_api_key)
    bootstrap_download_client("radarr", radarr_api_key)
    bootstrap_download_client("sonarr", sonarr_api_key)

    bootstrap_prowlarr_application("lidarr", lidarr_api_key, prowlarr_api_key)
    bootstrap_prowlarr_application("radarr", radarr_api_key, prowlarr_api_key)
    bootstrap_prowlarr_application("sonarr", sonarr_api_key, prowlarr_api_key)

    existing_jellyfin_api_key = get_existing_jellyseerr_api_key()
    try:
        jellyfin_access_token = authenticate_jellyfin_admin()
        jellyfin_api_key = create_jellyfin_api_key(jellyfin_access_token)
    except Exception as error:
        if not existing_jellyfin_api_key:
            raise
        jellyfin_api_key = existing_jellyfin_api_key
        log(f"Jellyfin: reusing existing Jellyseerr API key because admin authentication failed ({error})")

    update_jellyseerr_settings(radarr_api_key, sonarr_api_key, jellyfin_api_key)
    log("Bootstrap completed")


if __name__ == "__main__":
    main()
