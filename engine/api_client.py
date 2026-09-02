from __future__ import annotations

import json
import ssl
from typing import Any, Callable

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.ssl_ import create_urllib3_context

from engine.consts import DEBUG_DIR, DEFAULT_LANGUAGE, HTTP_TIMEOUT
from engine.helpers import authorization_header

urllib3.disable_warnings(InsecureRequestWarning)

REDACT_HEADER_KEYS = {"authorization", "x-otp-ticket"}
REDACT_BODY_KEYS = {
    "otp",
    "code",
    "code_verifier",
    "access_token",
    "refresh_token",
    "id_token",
}
REDACT_VALUE = "***"


class InsecureTLSAdapter(HTTPAdapter):
    """Python 3.13+ OpenSSL rejects Mashcal certs (missing AKID) even with Session.verify=False."""

    def _ssl_context(self) -> ssl.SSLContext:
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["ssl_context"] = self._ssl_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["ssl_context"] = self._ssl_context()
        return super().proxy_manager_for(*args, **kwargs)


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _redact_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (headers or {}).items():
        out[key] = REDACT_VALUE if key.lower() in REDACT_HEADER_KEYS else value
    return out


def _redact_mapping(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: REDACT_VALUE if str(key).lower() in REDACT_BODY_KEYS else _redact_mapping(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_mapping(item) for item in obj]
    return obj


def _response_body(resp: requests.Response) -> Any:
    if not resp.content:
        return None
    try:
        return _redact_mapping(resp.json())
    except ValueError:
        return resp.text


class ApiClient:
    def __init__(
        self,
        base_url: str,
        language: str = DEFAULT_LANGUAGE,
        session: requests.Session | None = None,
        tokens_provider: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.language = language or DEFAULT_LANGUAGE
        self.session = session or requests.Session()
        self.session.verify = False
        self.session.mount("https://", InsecureTLSAdapter())
        self.tokens_provider = tokens_provider
        self.on_unauthorized: Callable[[], bool] | None = None

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def headers(self, extra: dict[str, str] | None = None, auth: bool = False) -> dict[str, str]:
        out = {"Accept-Language": self.language, "lang": self.language}
        if extra:
            out.update(extra)
        if auth:
            tokens = self.tokens_provider() if self.tokens_provider else None
            if tokens and tokens.get("access_token"):
                out["Authorization"] = authorization_header(tokens)
        return out

    def raise_for_status(self, resp: requests.Response, action: str) -> None:
        if not resp.ok:
            raise ApiError(
                f"{action} failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
                body=resp.text,
            )

    def _dump(
        self,
        debug_name: str | None,
        request_meta: dict[str, Any],
        resp: requests.Response | None,
        error: str | None,
    ) -> None:
        if not debug_name:
            return
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        response: dict[str, Any] | None = None
        if resp is not None:
            response = {
                "status": resp.status_code,
                "headers": _redact_headers(dict(resp.headers)),
                "body": _response_body(resp),
            }
        payload = {
            "name": debug_name,
            "request": request_meta,
            "response": response,
            "error": error,
        }
        path = DEBUG_DIR / f"{debug_name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _retry_after_401(self, auth: bool, retried: bool, resp: requests.Response) -> bool:
        if retried or not auth or resp.status_code != 401:
            return False
        if self.on_unauthorized is None:
            return False
        return bool(self.on_unauthorized())

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
        debug_name: str | None = None,
    ) -> requests.Response:
        url = self.url(path)
        retried = False
        while True:
            headers = self.headers(extra_headers, auth=auth)
            request_meta = {
                "method": "GET",
                "url": url,
                "headers": _redact_headers(headers),
                "params": _redact_mapping(params) if params else None,
            }
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=HTTP_TIMEOUT, verify=False
                )
            except Exception as exc:
                self._dump(debug_name, request_meta, None, str(exc))
                raise
            self._dump(debug_name, request_meta, resp, None)
            if self._retry_after_401(auth, retried, resp):
                retried = True
                continue
            self.raise_for_status(resp, action or path)
            return resp

    def post_json(
        self,
        path: str,
        payload: Any,
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
        debug_name: str | None = None,
    ) -> requests.Response:
        url = self.url(path)
        retried = False
        while True:
            headers = self.headers(extra_headers, auth=auth)
            request_meta = {
                "method": "POST",
                "url": url,
                "headers": _redact_headers(headers),
                "json": _redact_mapping(payload),
            }
            try:
                resp = self.session.post(
                    url, json=payload, headers=headers, timeout=HTTP_TIMEOUT, verify=False
                )
            except Exception as exc:
                self._dump(debug_name, request_meta, None, str(exc))
                raise
            self._dump(debug_name, request_meta, resp, None)
            if self._retry_after_401(auth, retried, resp):
                retried = True
                continue
            self.raise_for_status(resp, action or path)
            return resp

    def post_form(
        self,
        path: str,
        form: dict[str, str],
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
        debug_name: str | None = None,
    ) -> requests.Response:
        url = self.url(path)
        headers = self.headers(extra_headers, auth=auth)
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        request_meta = {
            "method": "POST",
            "url": url,
            "headers": _redact_headers(headers),
            "form": _redact_mapping(form),
        }
        try:
            resp = self.session.post(
                url, data=form, headers=headers, timeout=HTTP_TIMEOUT, verify=False
            )
        except Exception as exc:
            self._dump(debug_name, request_meta, None, str(exc))
            raise
        self._dump(debug_name, request_meta, resp, None)
        self.raise_for_status(resp, action or path)
        return resp
