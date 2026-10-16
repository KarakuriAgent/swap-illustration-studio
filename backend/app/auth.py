"""アクセストークン（LAN 越しに公開するとき）。

- ``HOST`` が 127.0.0.1 / localhost 以外（= スマホなどから LAN 越しに使う）のときは ``.env`` の
  ``ACCESS_TOKEN`` が必須。画面は初回にトークンを聞き、HttpOnly の Cookie に保存する。
- /api/* はトークン（Cookie または ``Authorization: Bearer``）が無いと 401。画面のシェル（HTML・JS・
  アイコン）は認証なしで返す（ログイン画面を出すため。データは含まない）。
"""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import access_token, token_required

COOKIE = "swap_token"
#: トークンなしで呼べる API
PUBLIC_API = {"/api/auth/status", "/api/auth/login", "/api/auth/logout"}


def token_ok(request: Request) -> bool:
    if not token_required():
        return True
    want = access_token()
    got = request.cookies.get(COOKIE, "")
    if not got:
        h = request.headers.get("authorization", "")
        if h.lower().startswith("bearer "):
            got = h[7:].strip()
    return bool(want) and hmac.compare_digest(got.encode(), want.encode())


def check_login(token: str) -> bool:
    want = access_token()
    return bool(want) and hmac.compare_digest(token.strip().encode(), want.encode())


async def middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API and not token_ok(request):
        return JSONResponse({"detail": "アクセストークンが必要です"}, status_code=401)
    return await call_next(request)


def is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"
