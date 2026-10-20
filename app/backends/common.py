"""Shared helpers for the Part 3 backends (no router logic here)."""
import logging
import os

logger = logging.getLogger(__name__)


def error_response(code):
    return {"status": "error", "result": code}


def not_found_response():
    return {"status": "ok", "result": "not_found", "interface": None}


def applied_response():
    return {"status": "ok", "result": "applied"}


def router_credentials():
    """Common router credentials, supplied at runtime through the environment."""
    user = os.environ.get("ROUTER_USER")
    password = os.environ.get("ROUTER_PASS")
    if not user or not password:
        raise PermissionError("ROUTER_USER / ROUTER_PASS are not set")
    return user, password


_AUTH_NAMES = {
    "AuthenticationError",
    "AuthenticationException",
    "BadAuthenticationType",
    "NetmikoAuthenticationException",
}

_CONNECTION_NAMES = {
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
    "NetmikoTimeoutException",
    "SSHError",
    "SSHUnknownHostError",
    "TransportError",
    "SessionCloseError",
    "TimeoutExpiredError",
    "NoValidConnectionsError",
}


def classify_exception(exc):
    """
    Map an exception (built-in or from requests / ncclient / netmiko /
    paramiko) to one of the three backend error codes.
    """
    names = {cls.__name__ for cls in type(exc).__mro__}

    if isinstance(exc, PermissionError) or names & _AUTH_NAMES:
        return "authentication_failed"

    if isinstance(exc, (ConnectionError, TimeoutError)) or names & _CONNECTION_NAMES:
        return "connection_failed"

    # Other requests errors (bad URL, bad status, ...) are not connection
    # problems even though RequestException derives from OSError.
    if "RequestException" in names:
        return "backend_failed"

    if isinstance(exc, OSError):  # e.g. socket.gaierror, unreachable network
        return "connection_failed"

    return "backend_failed"  # RuntimeError, RPC errors, parse errors, ...


def exception_response(exc):
    code = classify_exception(exc)
    # Log the real cause (the JSON reply only carries the generic code).
    logger.warning("backend error -> %s: %r", code, exc, exc_info=exc)
    return error_response(code)