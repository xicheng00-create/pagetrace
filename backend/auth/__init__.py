"""stdlib-only password, HS256 token, and request identity helpers."""

import base64
import hashlib
import hmac
import json
import math
import secrets
import time

from flask import current_app, g, jsonify, request

ITERATIONS = 310000
SENTINEL_PASSWORD_HASH = "!BOOTSTRAP_PASSWORD_REQUIRED!"


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)

    def b64(b):
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    return f"pbkdf2_sha256${ITERATIONS}${b64(salt)}${b64(digest)}"


def verify_password(password, encoded):
    try:
        alg, it, salt, digest = encoded.split("$")
        def dec(s):
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

        return alg == "pbkdf2_sha256" and hmac.compare_digest(
            hashlib.pbkdf2_hmac("sha256", password.encode(), dec(salt), int(it)), dec(digest)
        )
    except (ValueError, TypeError):
        return False


def issue_token(user):
    secret = current_app.config.get("JWT_SECRET") or current_app.config.get("APP_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")

    def enc(x):
        return base64.urlsafe_b64encode(x).decode().rstrip("=")

    head = enc(b'{"alg":"HS256","typ":"JWT"}')
    body = enc(
        json.dumps(
            {
                "sub": user["id"],
                "username": user["username"],
                "role": user["role"],
                "exp": int(time.time()) + int(current_app.config.get("JWT_TTL_HOURS", 720)) * 3600,
            },
            separators=(",", ":"),
        ).encode()
    )
    msg = f"{head}.{body}"
    sig = enc(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest())
    return f"{msg}.{sig}"


def decode_token(token):
    try:
        head, body, sig = token.split(".")
        secret = current_app.config.get("JWT_SECRET") or current_app.config.get("APP_SECRET")
        expected = (
            base64.urlsafe_b64encode(
                hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
            )
            .decode()
            .rstrip("=")
        )

        def dec(s):
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

        if not hmac.compare_digest(sig, expected):
            return None
        header = json.loads(dec(head))
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            return None
        claims = json.loads(dec(body))
        if not isinstance(claims, dict):
            return None
        if type(claims.get("sub")) is not int or claims["sub"] <= 0:
            return None
        if not isinstance(claims.get("username"), str):
            return None
        if claims.get("role") not in ("owner", "member"):
            return None
        expiry = claims.get("exp")
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or not expiry > time.time():
            return None
        return claims
    except Exception:
        return None


def current_user_id():
    return getattr(g, "user_id", None)


def require_user():
    token = request.cookies.get("access_token")
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    claims = decode_token(token) if token else None
    if not claims:
        return None
    from data.db import get_db

    user = get_db().execute(
        "SELECT id,username,role FROM users WHERE id=?", (claims["sub"],)
    ).fetchone()
    if user is None:
        return None
    claims.update(sub=user["id"], username=user["username"], role=user["role"])
    g.user_id = claims["sub"]
    g.user = claims
    return claims


def unauthorized():
    return jsonify({"code": 401, "msg": "需要登录"}), 401
