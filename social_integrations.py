from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

try:
    import httpx
except ImportError:  # pragma: no cover - handled by runtime checks in the UI
    httpx = None  # type: ignore[assignment]

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - handled by runtime checks in the UI
    keyring = None  # type: ignore[assignment]

    class KeyringError(Exception):
        pass


SOCIAL_KEYRING_SERVICE = "SoraStudio.social"
SOCIAL_SIZE_OPTIONS = ("720x1280", "1024x1792")
SOCIAL_DEFAULT_SIZE = "1024x1792"
SOCIAL_CALLBACK_TIMEOUT = 180.0

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
TIKTOK_DIRECT_POST_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"

FACEBOOK_SCOPES = (
    "public_profile",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
)


class SocialIntegrationError(RuntimeError):
    pass


@dataclass
class OAuthFlowResult:
    redirect_uri: str
    params: dict[str, str]


class _OAuthCallbackServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], callback_path: str) -> None:
        super().__init__(server_address, _OAuthCallbackHandler)
        self.callback_path = callback_path.rstrip("/") or "/"
        self.payload: dict[str, str] = {}
        self.event = threading.Event()


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    server: _OAuthCallbackServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlparse(self.path)
        callback_path = parsed.path.rstrip("/") or "/"
        if callback_path != self.server.callback_path:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Callback not found.")
            return

        params = {
            key: values[0] if values else ""
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        }
        self.server.payload = params
        self.server.event.set()

        body = (
            "<html><body style='font-family:Segoe UI,Arial,sans-serif;background:#11181F;color:#E8EEF2;'>"
            "<h2>Connexion terminee</h2><p>Tu peux revenir dans SoraStudio.</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def dependencies_error() -> Optional[str]:
    missing: list[str] = []
    if httpx is None:
        missing.append("httpx")
    if keyring is None:
        missing.append("keyring")
    if not missing:
        return None
    return "Dependances manquantes pour les reseaux sociaux: " + ", ".join(missing)


def ensure_dependencies() -> None:
    error = dependencies_error()
    if error:
        raise SocialIntegrationError(error)


def ensure_http_dependency() -> None:
    if httpx is None:
        raise SocialIntegrationError("Dependance manquante pour les reseaux sociaux: httpx")


def ensure_keyring_dependency() -> None:
    if keyring is None:
        raise SocialIntegrationError("Dependance manquante pour les reseaux sociaux: keyring")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def compute_expiry(seconds: Any) -> str:
    try:
        numeric = int(seconds)
    except (TypeError, ValueError):
        return ""
    if numeric <= 0:
        return ""
    return (datetime.now() + timedelta(seconds=numeric)).isoformat(timespec="seconds")


def is_social_size(value: str) -> bool:
    return str(value or "").strip() in SOCIAL_SIZE_OPTIONS


def normalize_social_posts(raw_posts: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(raw_posts, list):
        return normalized

    for item in raw_posts:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "platform": str(item.get("platform") or ""),
                "target_id": str(item.get("target_id") or ""),
                "target_name": str(item.get("target_name") or ""),
                "caption": str(item.get("caption") or ""),
                "published_at": str(item.get("published_at") or ""),
                "status": str(item.get("status") or ""),
                "remote_id": str(item.get("remote_id") or item.get("publish_id") or ""),
                "publish_id": str(item.get("publish_id") or item.get("remote_id") or ""),
                "error": str(item.get("error") or ""),
            }
        )
    return normalized


def load_secret_json(secret_name: str) -> dict[str, Any]:
    ensure_keyring_dependency()
    try:
        raw = keyring.get_password(SOCIAL_KEYRING_SERVICE, secret_name)
    except KeyringError as exc:  # pragma: no cover - depends on OS backend
        raise SocialIntegrationError(f"Impossible de lire le coffre systeme: {exc}") from exc
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def save_secret_json(secret_name: str, payload: dict[str, Any]) -> None:
    ensure_keyring_dependency()
    try:
        keyring.set_password(
            SOCIAL_KEYRING_SERVICE,
            secret_name,
            json.dumps(payload, ensure_ascii=False),
        )
    except KeyringError as exc:  # pragma: no cover - depends on OS backend
        raise SocialIntegrationError(f"Impossible de sauvegarder le coffre systeme: {exc}") from exc


def delete_secret(secret_name: str) -> None:
    ensure_keyring_dependency()
    try:
        keyring.delete_password(SOCIAL_KEYRING_SERVICE, secret_name)
    except keyring.errors.PasswordDeleteError:  # type: ignore[attr-defined]
        return
    except KeyringError as exc:  # pragma: no cover - depends on OS backend
        raise SocialIntegrationError(f"Impossible de nettoyer le coffre systeme: {exc}") from exc


def _build_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _run_browser_callback_flow(
    port: int,
    callback_path: str,
    auth_url: str,
    timeout: float = SOCIAL_CALLBACK_TIMEOUT,
) -> OAuthFlowResult:
    ensure_http_dependency()
    try:
        server = _OAuthCallbackServer(("127.0.0.1", int(port)), callback_path)
    except OSError as exc:
        raise SocialIntegrationError(
            f"Le port OAuth {port} est indisponible. Ferme le processus qui l'utilise ou change la config."
        ) from exc

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()

    try:
        webbrowser.open(auth_url, new=1, autoraise=True)
        if not server.event.wait(timeout):
            raise SocialIntegrationError("Connexion annulee ou expiree avant retour OAuth.")
        params = server.payload
    finally:
        server.shutdown()
        server.server_close()

    if not params:
        raise SocialIntegrationError("Aucun parametre OAuth recu.")
    if params.get("error"):
        message = params.get("error_description") or params.get("error")
        raise SocialIntegrationError(f"Connexion refusee: {message}")

    redirect_uri = f"http://127.0.0.1:{int(port)}{callback_path}"
    return OAuthFlowResult(redirect_uri=redirect_uri, params=params)


def _require_value(name: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise SocialIntegrationError(f"Configuration manquante: {name}")
    return cleaned


def _http_response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        text = getattr(response, "text", "")
        raise SocialIntegrationError(f"Reponse API invalide: {text[:300]}") from exc
    if isinstance(payload, dict):
        return payload
    raise SocialIntegrationError("Reponse API inattendue.")


def _extract_tiktok_error(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("code") or "Erreur TikTok")
        detail = str(error.get("log_id") or "")
        return f"{message} {detail}".strip()

    message = payload.get("message") or payload.get("error_description") or payload.get("description")
    if message:
        return str(message)

    data = payload.get("data")
    if isinstance(data, dict):
        nested_error = data.get("error")
        if isinstance(nested_error, dict):
            return str(nested_error.get("message") or nested_error.get("code") or "Erreur TikTok")
    return "Erreur TikTok inconnue."


def _extract_meta_error(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        parts = [str(error.get("message") or "Erreur Facebook")]
        code = error.get("code")
        subcode = error.get("error_subcode")
        if code not in (None, ""):
            parts.append(f"(code {code})")
        if subcode not in (None, ""):
            parts.append(f"subcode {subcode}")
        return " ".join(parts).strip()
    if payload.get("message"):
        return str(payload["message"])
    return "Erreur Facebook inconnue."


class TikTokAPI:
    secret_name = "tiktok_tokens"

    def __init__(self, client_key: str, client_secret: str = "", redirect_port: int = 8765) -> None:
        self.client_key = _require_value("TIKTOK_CLIENT_KEY", client_key)
        self.client_secret = str(client_secret or "").strip()
        self.redirect_port = int(redirect_port)

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.redirect_port}/tiktok/callback"

    def _client(self) -> Any:
        ensure_http_dependency()
        return httpx.Client(timeout=60.0, follow_redirects=True)

    def connect(self) -> dict[str, Any]:
        state = secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        query = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": "video.publish",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": _build_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        auth_url = f"{TIKTOK_AUTH_URL}?{urlencode(query)}"
        result = _run_browser_callback_flow(self.redirect_port, "/tiktok/callback", auth_url)
        if result.params.get("state") != state:
            raise SocialIntegrationError("Etat OAuth TikTok invalide.")

        code = str(result.params.get("code") or "").strip()
        if not code:
            raise SocialIntegrationError("Code OAuth TikTok manquant.")
        return self.exchange_code(code, code_verifier, result.redirect_uri)

    def exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
        payload = {
            "client_key": self.client_key,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        with self._client() as client:
            response = client.post(TIKTOK_TOKEN_URL, data=payload)
        data = _http_response_json(response)
        if response.status_code >= 400 or data.get("error"):
            raise SocialIntegrationError(_extract_tiktok_error(data))
        token_data = data.get("data") if isinstance(data.get("data"), dict) else data
        return self._normalize_token_data(token_data)

    def refresh_tokens(self, token_payload: dict[str, Any]) -> dict[str, Any]:
        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        if not refresh_token:
            raise SocialIntegrationError("Refresh token TikTok manquant. Reconnecte le compte.")

        payload = {
            "client_key": self.client_key,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        with self._client() as client:
            response = client.post(TIKTOK_TOKEN_URL, data=payload)
        data = _http_response_json(response)
        if response.status_code >= 400 or data.get("error"):
            raise SocialIntegrationError(_extract_tiktok_error(data))
        token_data = data.get("data") if isinstance(data.get("data"), dict) else data
        normalized = self._normalize_token_data(token_data)
        if not normalized.get("refresh_token"):
            normalized["refresh_token"] = refresh_token
            normalized["refresh_expires_at"] = str(token_payload.get("refresh_expires_at") or "")
        return normalized

    def ensure_access_token(self, token_payload: dict[str, Any]) -> dict[str, Any]:
        expires_at = str(token_payload.get("access_expires_at") or "")
        if not expires_at:
            return token_payload
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            return token_payload
        if expiry > (datetime.now() + timedelta(minutes=2)):
            return token_payload
        return self.refresh_tokens(token_payload)

    def query_creator_info(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        with self._client() as client:
            response = client.post(TIKTOK_CREATOR_INFO_URL, headers=headers, json={})
        data = _http_response_json(response)
        if response.status_code >= 400 or data.get("error"):
            raise SocialIntegrationError(_extract_tiktok_error(data))

        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        creator = payload.get("creator_info") if isinstance(payload.get("creator_info"), dict) else payload
        privacy_levels = creator.get("privacy_level_options") if isinstance(creator, dict) else []
        if not isinstance(privacy_levels, list):
            privacy_levels = []

        return {
            "display_name": str(
                (creator.get("display_name") if isinstance(creator, dict) else "")
                or (creator.get("nickname") if isinstance(creator, dict) else "")
                or payload.get("creator_nickname")
                or payload.get("creator_username")
                or ""
            ),
            "username": str(
                (creator.get("username") if isinstance(creator, dict) else "")
                or payload.get("creator_username")
                or ""
            ),
            "open_id": str(payload.get("open_id") or ""),
            "privacy_level_options": [str(item) for item in privacy_levels if str(item).strip()],
            "raw": payload,
        }

    def init_direct_post(
        self,
        access_token: str,
        caption: str,
        privacy_level: str,
        file_size: int,
    ) -> dict[str, Any]:
        request_payload = {
            "post_mode": "DIRECT_POST",
            "post_info": {
                "title": caption,
                "privacy_level": privacy_level,
                "disable_comment": False,
                "disable_duet": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": int(file_size),
                "chunk_size": int(file_size),
                "total_chunk_count": 1,
            },
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        with self._client() as client:
            response = client.post(TIKTOK_DIRECT_POST_URL, headers=headers, json=request_payload)
        data = _http_response_json(response)
        if response.status_code >= 400 or data.get("error"):
            raise SocialIntegrationError(_extract_tiktok_error(data))

        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        upload_url = str(payload.get("upload_url") or "")
        if not upload_url and isinstance(payload.get("upload_info"), dict):
            upload_url = str(payload["upload_info"].get("upload_url") or "")
        if not upload_url:
            raise SocialIntegrationError("TikTok n'a pas renvoye d'URL d'upload.")

        publish_id = str(payload.get("publish_id") or payload.get("video_id") or "")
        return {"upload_url": upload_url, "publish_id": publish_id, "raw": payload}

    def upload_video(self, upload_url: str, file_path: str) -> None:
        last_error: Optional[str] = None
        with open(file_path, "rb") as handle:
            content = handle.read()

        headers = {"Content-Type": "video/mp4"}
        with self._client() as client:
            for method in ("PUT", "POST"):
                response = client.request(method, upload_url, headers=headers, content=content)
                if response.status_code < 400:
                    return
                try:
                    payload = _http_response_json(response)
                    last_error = _extract_tiktok_error(payload)
                except SocialIntegrationError:
                    last_error = response.text[:300]

        raise SocialIntegrationError(last_error or "Upload TikTok impossible.")

    def publish_video(
        self,
        token_payload: dict[str, Any],
        file_path: str,
        caption: str,
        privacy_level: str,
    ) -> dict[str, Any]:
        fresh_tokens = self.ensure_access_token(token_payload)
        access_token = str(fresh_tokens.get("access_token") or "").strip()
        if not access_token:
            raise SocialIntegrationError("Access token TikTok manquant. Reconnecte le compte.")

        file_size = int(__import__("os").path.getsize(file_path))
        init_result = self.init_direct_post(access_token, caption, privacy_level, file_size)
        self.upload_video(str(init_result["upload_url"]), file_path)
        return {
            "token_payload": fresh_tokens,
            "publish_id": str(init_result.get("publish_id") or ""),
            "remote_id": str(init_result.get("publish_id") or ""),
            "raw": init_result,
        }

    def _normalize_token_data(self, token_data: dict[str, Any]) -> dict[str, Any]:
        scopes = token_data.get("scope")
        if isinstance(scopes, str):
            scope_list = [scope.strip() for scope in scopes.split(",") if scope.strip()]
        elif isinstance(scopes, list):
            scope_list = [str(scope).strip() for scope in scopes if str(scope).strip()]
        else:
            scope_list = []

        return {
            "access_token": str(token_data.get("access_token") or ""),
            "refresh_token": str(token_data.get("refresh_token") or ""),
            "scope": scope_list,
            "open_id": str(token_data.get("open_id") or ""),
            "access_expires_at": compute_expiry(token_data.get("expires_in") or token_data.get("access_token_expires_in")),
            "refresh_expires_at": compute_expiry(token_data.get("refresh_expires_in")),
            "connected_at": now_iso(),
        }


class FacebookAPI:
    secret_name = "facebook_tokens"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        graph_version: str = "v23.0",
        redirect_port: int = 8766,
    ) -> None:
        self.app_id = _require_value("FACEBOOK_APP_ID", app_id)
        self.app_secret = _require_value("FACEBOOK_APP_SECRET", app_secret)
        self.graph_version = str(graph_version or "v23.0").strip()
        self.redirect_port = int(redirect_port)

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.redirect_port}/facebook/callback"

    @property
    def graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}"

    @property
    def dialog_url(self) -> str:
        return f"https://www.facebook.com/{self.graph_version}/dialog/oauth"

    def _client(self) -> Any:
        ensure_http_dependency()
        return httpx.Client(timeout=60.0, follow_redirects=True)

    def connect(self) -> dict[str, Any]:
        state = secrets.token_urlsafe(24)
        query = {
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": ",".join(FACEBOOK_SCOPES),
            "state": state,
        }
        auth_url = f"{self.dialog_url}?{urlencode(query)}"
        result = _run_browser_callback_flow(self.redirect_port, "/facebook/callback", auth_url)
        if result.params.get("state") != state:
            raise SocialIntegrationError("Etat OAuth Facebook invalide.")

        code = str(result.params.get("code") or "").strip()
        if not code:
            raise SocialIntegrationError("Code OAuth Facebook manquant.")
        return self.exchange_code(code, result.redirect_uri)

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        params = {
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        with self._client() as client:
            response = client.get(f"{self.graph_base}/oauth/access_token", params=params)
        payload = _http_response_json(response)
        if response.status_code >= 400 or payload.get("error"):
            raise SocialIntegrationError(_extract_meta_error(payload))

        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise SocialIntegrationError("Facebook n'a pas renvoye de jeton utilisateur.")

        profile = self.fetch_profile(access_token)
        pages = self.fetch_pages(access_token)
        if not pages:
            raise SocialIntegrationError("Aucune Page Facebook accessible pour ce compte.")

        page_tokens = {
            str(page.get("id") or ""): str(page.get("access_token") or "")
            for page in pages
            if str(page.get("id") or "").strip() and str(page.get("access_token") or "").strip()
        }
        visible_pages = [
            {"id": str(page.get("id") or ""), "name": str(page.get("name") or "")}
            for page in pages
            if str(page.get("id") or "").strip()
        ]
        return {
            "token_payload": {
                "user_access_token": access_token,
                "page_tokens": page_tokens,
                "connected_at": now_iso(),
            },
            "profile": profile,
            "pages": visible_pages,
        }

    def fetch_profile(self, access_token: str) -> dict[str, Any]:
        params = {"fields": "id,name", "access_token": access_token}
        with self._client() as client:
            response = client.get(f"{self.graph_base}/me", params=params)
        payload = _http_response_json(response)
        if response.status_code >= 400 or payload.get("error"):
            raise SocialIntegrationError(_extract_meta_error(payload))
        return {"id": str(payload.get("id") or ""), "name": str(payload.get("name") or "")}

    def fetch_pages(self, access_token: str) -> list[dict[str, Any]]:
        params = {"fields": "id,name,access_token", "access_token": access_token}
        with self._client() as client:
            response = client.get(f"{self.graph_base}/me/accounts", params=params)
        payload = _http_response_json(response)
        if response.status_code >= 400 or payload.get("error"):
            raise SocialIntegrationError(_extract_meta_error(payload))
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def publish_reel(
        self,
        page_id: str,
        page_access_token: str,
        caption: str,
        file_path: str,
    ) -> dict[str, Any]:
        page_id = _require_value("FACEBOOK_PAGE_ID", page_id)
        page_access_token = _require_value("FACEBOOK_PAGE_TOKEN", page_access_token)
        endpoint = f"{self.graph_base}/{page_id}/video_reels"
        file_name = __import__("os").path.basename(file_path)

        with self._client() as client:
            start_response = client.post(
                endpoint,
                data={"upload_phase": "start", "access_token": page_access_token},
            )
            start_payload = _http_response_json(start_response)
            if start_response.status_code < 400 and "upload_url" in start_payload:
                upload_url = str(start_payload.get("upload_url") or "")
                video_id = str(start_payload.get("video_id") or start_payload.get("id") or "")
                with open(file_path, "rb") as handle:
                    content = handle.read()
                headers = {
                    "Authorization": f"OAuth {page_access_token}",
                    "offset": "0",
                    "file_size": str(len(content)),
                    "Content-Type": "application/octet-stream",
                }
                transfer_ok = False
                last_transfer_error = ""
                for method in ("POST", "PUT"):
                    upload_response = client.request(method, upload_url, headers=headers, content=content)
                    if upload_response.status_code < 400:
                        transfer_ok = True
                        break
                    try:
                        last_transfer_error = _extract_meta_error(_http_response_json(upload_response))
                    except SocialIntegrationError:
                        last_transfer_error = upload_response.text[:300]
                if not transfer_ok:
                    raise SocialIntegrationError(last_transfer_error or "Upload Facebook impossible.")

                finish_response = client.post(
                    endpoint,
                    data={
                        "upload_phase": "finish",
                        "video_id": video_id,
                        "video_state": "PUBLISHED",
                        "description": caption,
                        "access_token": page_access_token,
                    },
                )
                finish_payload = _http_response_json(finish_response)
                if finish_response.status_code >= 400 or finish_payload.get("error"):
                    raise SocialIntegrationError(_extract_meta_error(finish_payload))
                remote_id = str(
                    finish_payload.get("video_id")
                    or finish_payload.get("success")
                    or video_id
                    or finish_payload.get("id")
                    or ""
                )
                return {"remote_id": remote_id, "raw": finish_payload}

            if start_response.status_code >= 400 and start_payload.get("error"):
                last_error = _extract_meta_error(start_payload)
            else:
                last_error = ""

            with open(file_path, "rb") as handle:
                fallback_response = client.post(
                    endpoint,
                    data={"description": caption, "access_token": page_access_token},
                    files={"source": (file_name, handle, "video/mp4")},
                )
            fallback_payload = _http_response_json(fallback_response)
            if fallback_response.status_code >= 400 or fallback_payload.get("error"):
                message = _extract_meta_error(fallback_payload)
                if last_error:
                    message = f"{last_error} / {message}"
                raise SocialIntegrationError(message)
            remote_id = str(
                fallback_payload.get("id")
                or fallback_payload.get("video_id")
                or fallback_payload.get("success")
                or ""
            )
            return {"remote_id": remote_id, "raw": fallback_payload}
