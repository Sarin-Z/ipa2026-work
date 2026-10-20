import json
import os
import subprocess
from ipaddress import IPv4Interface
from pathlib import Path

from app.backends.common import (
    applied_response,
    exception_response,
    router_credentials,
)

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"
PLAYBOOK_TIMEOUT = 120


# ---------- real runner (used only when no callable is injected) ----------

def _run_playbook(variables):
    """Run ansible/apply_interface.yml; raise the built-in error for each failure type."""
    user, password = router_credentials()

    extra_vars = dict(variables)
    extra_vars["ansible_host"] = variables["router"]

    env = dict(os.environ)
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    env["ANSIBLE_NOCOLOR"] = "1"
    env["ROUTER_USER"] = user
    env["ROUTER_PASS"] = password

    try:
        proc = subprocess.run(
            [
                "ansible-playbook",
                "-i", str(ANSIBLE_DIR / "inventory.ini"),
                str(ANSIBLE_DIR / "apply_interface.yml"),
                "--extra-vars", json.dumps(extra_vars),
            ],
            capture_output=True,
            text=True,
            timeout=PLAYBOOK_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError("ansible-playbook timed out") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ansible-playbook is not installed") from exc

    if proc.returncode == 0:
        return

    output = (proc.stdout + proc.stderr).lower()

    if any(
        text in output
        for text in (
            "authentication failed",
            "invalid/incorrect password",
            "permission denied",
            "authentication fail",
        )
    ):
        raise PermissionError("router rejected the credentials")

    if proc.returncode == 4 or any(
        text in output
        for text in (
            "unreachable",
            "timed out",
            "connection refused",
            "no route to host",
            "unable to connect",
        )
    ):
        raise ConnectionError("router is unreachable")

    raise RuntimeError("ansible playbook failed")


# ---------- apply ----------

def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    run_playbook = run_playbook or _run_playbook

    try:
        ipv4 = IPv4Interface(desired_interface["ipv4"])

        variables = {
            "router": router,
            "interface_name": desired_interface["name"],
            "description": desired_interface["description"],
            "ipv4_address": str(ipv4.ip),
            "netmask": str(ipv4.network.netmask),
            "shutdown": desired_interface["admin_state"] == "down",
        }

        run_playbook(variables)
        return applied_response()
    except Exception as exc:
        return exception_response(exc)