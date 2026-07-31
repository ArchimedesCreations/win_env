"""
Controller logic shared by the GUI for turning a selection of checked driver
packages into real deletions and a human-readable summary.

Deliberately has no `customtkinter` / `tkinter` import: everything here is
plain Python operating on duck-typed inputs (anything with a `.get()` that
returns a bool), so it can be unit tested without a display or GUI toolkit,
and reused if a different front end is ever added.
"""

from typing import Any, Dict, List

from src.driver_parser import DeletionResult, delete_driver


def get_selected_infs(checkbox_vars: Dict[str, Any]) -> List[str]:
    """
    Returns the published names (INF file names) whose checkbox is checked.
    `checkbox_vars` maps an INF name to any object exposing `.get() -> bool`
    (a real `tkinter.BooleanVar`, or a plain test fake).
    """
    return [inf for inf, var in checkbox_vars.items() if var.get()]


def delete_selected_drivers(infs: List[str]) -> List[DeletionResult]:
    """Deletes each selected driver package in turn, collecting the results."""
    return [delete_driver(inf) for inf in infs]


def build_deletion_summary(results: List[DeletionResult]) -> str:
    """Formats a human-readable summary of a batch deletion for a message box."""
    if not results:
        return "No driver packages were deleted."

    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    if not failed:
        names = ", ".join(r.published_name for r in succeeded)
        return f"Successfully deleted {len(succeeded)} driver package(s):\n\n{names}"

    if not succeeded:
        lines = "\n".join(f"- {r.published_name}: {r.message}" for r in failed)
        return f"Failed to delete {len(failed)} driver package(s):\n\n{lines}"

    succeeded_names = ", ".join(r.published_name for r in succeeded)
    failed_lines = "\n".join(f"- {r.published_name}: {r.message}" for r in failed)
    return (
        f"Deleted {len(succeeded)} of {len(results)} driver package(s).\n\n"
        f"Succeeded: {succeeded_names}\n\n"
        f"Failed:\n{failed_lines}"
    )
