from ipaddress import IPv4Interface, IPv4Network

from app.backends.common import (
    applied_response,
    error_response,
    exception_response,
    not_found_response,
    router_credentials,
)
from app.backends.planning import plan_interface as build_interface_plan

TIMEOUT = 10


# ---------- real transport (used only when no callable is injected) ----------

def _request_kwargs():
    user, password = router_credentials()
    return {"auth": (user, password), "verify": False, "timeout": TIMEOUT}


def _http_get(url):
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return requests.get(
        url,
        headers={"Accept": "application/yang-data+json"},
        **_request_kwargs(),
    )


def _http_put(url, json):
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return requests.put(
        url,
        json=json,
        headers={
            "Accept": "application/yang-data+json",
            "Content-Type": "application/yang-data+json",
        },
        **_request_kwargs(),
    )


# ---------- status ----------

def _normalize(interface):
    ipv4 = None
    addresses = (interface.get("ietf-ip:ipv4") or {}).get("address") or []
    if isinstance(addresses, dict):
        addresses = [addresses]
    if addresses:
        first = addresses[0]
        prefix = IPv4Network(f"0.0.0.0/{first['netmask']}").prefixlen
        ipv4 = f"{first['ip']}/{prefix}"

    return {
        "name": interface["name"],
        "ipv4": ipv4,
        "description": interface.get("description"),
        "admin_state": "up" if interface.get("enabled") else "down",
    }


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    http_get = http_get or _http_get
    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )

    try:
        response = http_get(url)
        code = response.status_code

        if code == 404:
            return not_found_response()
        if code in (401, 403):
            return error_response("authentication_failed")
        if code != 200:
            return error_response("backend_failed")

        interface = response.json()["ietf-interfaces:interface"]
        return {
            "status": "ok",
            "result": "found",
            "interface": _normalize(interface),
        }
    except Exception as exc:
        return exception_response(exc)


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return build_interface_plan(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get),
    )


# ---------- apply ----------

def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    http_put = http_put or _http_put

    try:
        number = int(desired_interface["name"][len("Loopback"):])
        ipv4 = IPv4Interface(desired_interface["ipv4"])

        payload = {
            "name": number,
            "description": desired_interface["description"],
            "ip": {
                "address": {
                    "primary": {
                        "address": str(ipv4.ip),
                        "mask": str(ipv4.network.netmask),
                    }
                }
            },
        }
        if desired_interface["admin_state"] == "down":
            payload["shutdown"] = [None]

        url = (
            f"https://{router}/restconf/data/"
            f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
        )
        response = http_put(url, json={"Cisco-IOS-XE-native:Loopback": payload})
        code = response.status_code

        if code in (200, 201, 204):
            return applied_response()
        if code in (401, 403):
            return error_response("authentication_failed")
        return error_response("backend_failed")
    except Exception as exc:
        return exception_response(exc)