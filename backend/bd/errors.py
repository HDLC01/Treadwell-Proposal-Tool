"""BD's error envelope, for every failure a BD route can produce, and ONLY for BD routes.

    { "ok": false, "error": "not_found", "message": "That contact does not exist." }
    { "ok": false, "error": "bad_request", "message": "Some fields need fixing.",
      "fields": { "name": "Required." } }

In a BD route, raise one of these (never return an error dict by hand):

    raise errors.not_found("That contact does not exist.")
    raise errors.bad_request("Some fields need fixing.", {"name": "Type the person's name."})
    raise errors.forbidden("Only the assistant can clear a duplicate flag.")
    raise errors.conflict("That task is already done.")
    raise errors.unavailable("The phone system is not answering.")
    raise errors.ApiError(429, "Too many AI requests. Wait a minute.")

NOTHING HERE IS REGISTERED ON THE APP (#806). BD lives on the proposal tool's FastAPI app, whose own
404, 422 and 500 answers keep their shapes. BD's router applies the envelope itself: its route class
(bd/web.py) passes every exception a BD route raises to handle() below, so the envelope appears
under /api/bd/ and nowhere else.

handle(request, exc) answers:
  * ApiError                       -> its status / code / message / fields
  * HTTPException (FastAPI's and Starlette's) -> the status's code; a str detail becomes the
    message. A 405 is answered as BD always answered it: 400 bad_request
    "<METHOD> is not allowed on <path>."
  * RequestValidationError (FastAPI's 422) -> 400 bad_request with "fields": {name: sentence}
  * a value Postgres cannot hold (psycopg.DataError, UnicodeEncodeError) -> 400, never a 500
  * db.Unavailable (BD's database cannot serve this request now) -> 503
  * anything else                  -> 500 "error", logged with its traceback, nothing leaked
"""
from __future__ import annotations

import logging
import re

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("bd.errors")

# HTTP status -> the contract's `error` code (docs/bd/api-contract.md "Errors").
STATUS_CODE = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    # Not a contract code: a wrong method on a known path is a 400 bad_request (review C7).
    405: "bad_request",
    409: "conflict",
    413: "bad_request",
    415: "bad_request",
    422: "bad_request",
    429: "rate_limited",
    500: "error",
    503: "unavailable",
}

DEFAULT_MESSAGE = {
    400: "That request could not be read.",
    401: "Sign in again to continue.",
    403: "Your role can't do that.",
    404: "That does not exist.",
    405: "That action is not allowed here.",
    409: "That is not possible right now.",
    429: "Too many requests. Wait a minute and try again.",
    500: "The server had a problem. Try again in a minute.",
    503: "That part is not available right now. Try again in a minute.",
}

DB_UNAVAILABLE = "The BD CRM's database is not answering. Try again in a minute."
DB_BUSY = "The BD CRM is busy. Try again in a moment."


_UNSAFE_IN_MESSAGE = re.compile(r"[^A-Za-z0-9/._~-]")


def reflect(text: str) -> str:
    """A request's own method or path, made safe to quote back in a message: anything but letters,
    digits and / . _ ~ - becomes "?". The path arrives percent-DECODED, so "%3Cb%3E" is a real "<b>"
    here; an error message never repeats markup, quotes or line breaks a caller chose
    (tests/test_bd_hardening.py). Real routes use only the safe set."""
    return _UNSAFE_IN_MESSAGE.sub("?", text)


def code_for(status: int) -> str:
    if status in STATUS_CODE:
        return STATUS_CODE[status]
    return "bad_request" if 400 <= status < 500 else "error"


class ApiError(Exception):
    """A failure with the contract's shape. `code` defaults from the status."""

    def __init__(self, status: int, message: str | None = None, code: str | None = None,
                 fields: dict | None = None, headers: dict | None = None):
        self.status = int(status)
        self.code = code or code_for(self.status)
        self.message = message or DEFAULT_MESSAGE.get(self.status, "Something went wrong.")
        self.fields = fields
        self.headers = headers
        super().__init__(self.message)


def bad_request(message: str = "Some fields need fixing.", fields: dict | None = None) -> ApiError:
    return ApiError(400, message, fields=fields)


def unauthenticated(message: str = "Sign in again to continue.") -> ApiError:
    return ApiError(401, message)


def forbidden(message: str = "Your role can't do that.") -> ApiError:
    return ApiError(403, message)


def not_found(message: str = "That does not exist.") -> ApiError:
    return ApiError(404, message)


def conflict(message: str) -> ApiError:
    return ApiError(409, message)


def rate_limited(message: str = "Too many requests. Wait a minute and try again.") -> ApiError:
    return ApiError(429, message)


def unavailable(message: str = "That part is not available right now. Try again in a minute.") -> ApiError:
    return ApiError(503, message)


def envelope(status: int, message: str | None = None, code: str | None = None,
             fields: dict | None = None) -> dict:
    body = {"ok": False, "error": code or code_for(status),
            "message": message or DEFAULT_MESSAGE.get(status, "Something went wrong.")}
    if fields:
        body["fields"] = fields
    return body


def response(status: int, message: str | None = None, code: str | None = None,
             fields: dict | None = None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope(status, message, code, fields),
                        headers=headers)


# ── FastAPI's 422 in plain words ─────────────────────────────────────────────────────────────
_SENTENCES = {
    "missing": "Required.",
    "int_parsing": "Use a whole number.",
    "int_type": "Use a whole number.",
    "int_from_float": "Use a whole number.",
    "float_parsing": "Use a number.",
    "float_type": "Use a number.",
    "bool_parsing": "Use true or false.",
    "bool_type": "Use true or false.",
    "string_type": "Use text.",
    "date_parsing": "Use a date (YYYY-MM-DD).",
    "date_from_datetime_parsing": "Use a date (YYYY-MM-DD).",
    "date_from_datetime_inexact": "Use a date (YYYY-MM-DD).",
    "date_type": "Use a date (YYYY-MM-DD).",
    "datetime_parsing": "Use a date and time (ISO 8601).",
    "datetime_from_date_parsing": "Use a date and time (ISO 8601).",
    "datetime_type": "Use a date and time (ISO 8601).",
    "list_type": "Use a list.",
    "dict_type": "Use an object.",
    "model_type": "Use an object.",
    "model_attributes_type": "Use an object.",
    "json_invalid": "The request body is not valid JSON.",
    "json_type": "The request body is not valid JSON.",
    "extra_forbidden": "Not a field this accepts.",
    "string_too_short": "Too short.",
    "string_too_long": "Too long.",
}


def _sentence(err: dict) -> str:
    kind = str(err.get("type") or "")
    if kind in _SENTENCES:
        return _SENTENCES[kind]
    if kind in ("literal_error", "enum"):
        expected = (err.get("ctx") or {}).get("expected")
        return ("Use one of: %s." % expected) if expected else "Pick one of the listed values."
    if kind in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        ctx = err.get("ctx") or {}
        word = {"greater_than": "more than", "greater_than_equal": "at least",
                "less_than": "less than", "less_than_equal": "at most"}[kind]
        limit = next(iter(ctx.values()), None)
        return "Use a number %s %s." % (word, limit) if limit is not None else "That number is out of range."
    msg = str(err.get("msg") or "That value is not right.").strip()
    if msg.lower().startswith("value error, "):
        msg = msg[len("value error, "):]
    msg = msg[:1].upper() + msg[1:]
    return msg if msg.endswith((".", "?", "!")) else msg + "."


def _field_name(loc) -> str:
    """("body", "company", "name") -> "company.name"; ("query", "limit") -> "limit";
    ("body",) or a JSON position -> "body"."""
    parts = [str(p) for p in (loc or ()) if not isinstance(p, int)]
    if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
        parts = parts[1:]
    return ".".join(parts) or "body"


def validation_fields(exc: RequestValidationError) -> dict:
    fields: dict = {}
    for err in exc.errors():
        if err.get("type") in ("json_invalid", "json_type"):
            fields["body"] = _SENTENCES["json_invalid"]
            continue
        fields.setdefault(_field_name(err.get("loc")), _sentence(err))
    return fields


# ── the one entry point: the BD route class hands every exception here ───────────────────────
def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else None
    status = exc.status_code
    if status == 405:
        return response(400, "%s is not allowed on %s." % (reflect(request.method),
                                                           reflect(request.url.path.rstrip("/")) or "/"),
                        "bad_request")
    # Starlette's own words ("Not Found", "Method Not Allowed") are replaced by a sentence.
    if detail in ("Not Found", "Method Not Allowed", "Bad Request", "Unauthorized", "Forbidden"):
        detail = None
    if status == 404 and detail is None:
        detail = "That page or record does not exist."
    return response(status, detail, None, None, getattr(exc, "headers", None))


def _validation_error(exc: RequestValidationError) -> JSONResponse:
    fields = validation_fields(exc)
    if list(fields) == ["body"] and fields["body"] == _SENTENCES["json_invalid"]:
        message = "The request body is not valid JSON."
    else:
        message = "Some fields need fixing."
    return response(400, message, "bad_request", fields)


def _unsaveable_text(request: Request, exc: Exception) -> JSONResponse:
    """A value Postgres cannot hold (a NUL byte, a lone surrogate, a number out of range) is a caller's
    mistake, not a server fault: a 400 in the contract's words, never a 500 with a stack trace.
    Only the class and SQLSTATE are logged (the message can repeat what the caller typed)."""
    log.warning("unsaveable value on %s %r: %s %s", request.method, request.url.path, type(exc).__name__,
                getattr(exc, "sqlstate", None))
    return response(400, "Some of that text has characters that can't be saved. Remove them and try again.",
                    "bad_request")


def handle(request: Request, exc: Exception) -> JSONResponse:
    """The envelope for an exception a BD route raised. Never raises."""
    import psycopg

    from . import db

    if isinstance(exc, ApiError):
        return response(exc.status, exc.message, exc.code, exc.fields, exc.headers)
    if isinstance(exc, StarletteHTTPException):
        return _http_error(request, exc)
    if isinstance(exc, RequestValidationError):
        return _validation_error(exc)
    if isinstance(exc, db.Busy):
        return response(503, DB_BUSY, "unavailable")
    if isinstance(exc, db.Unavailable):
        return response(503, DB_UNAVAILABLE, "unavailable")
    if isinstance(exc, (psycopg.DataError, UnicodeEncodeError)):
        return _unsaveable_text(request, exc)
    # %r, never %s: the path arrives percent-DECODED, so a control character in it would otherwise
    # break or forge a log line (CWE-117).
    log.error("unhandled error on %s %r", request.method, request.url.path, exc_info=exc)
    return response(500)
