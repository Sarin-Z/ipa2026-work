from app.planner import build_plan


def plan_interface(
    router,
    desired_interface,
    get_interface_state,
):
    """Build a Part 2 plan from backend status."""
    status = get_interface_state(router, desired_interface["name"])

    # A backend error is returned unchanged.
    if status["status"] != "ok":
        return status

    if status["result"] == "found":
        current_interface = status["interface"]
    else:  # not_found
        current_interface = None

    return build_plan(desired_interface, current_interface)