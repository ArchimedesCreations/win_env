"""
Core logic for scanning the Windows Driver Store via `pnputil` and
identifying duplicate / superseded third-party (OEM) driver packages.
"""

import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# pnputil can hang if the driver store is locked by another process or an
# elevation prompt is pending; bound how long we're willing to wait for it.
PNPUTIL_TIMEOUT_SECONDS = 30

# Accepted date formats for the "Driver Version" field's date component.
# %m/%d/%Y is the documented format, but pnputil's exact locale/build
# behavior isn't guaranteed, so a couple of close variants are also tried.
_DATE_FORMATS = ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d")

_VERSION_PART_RE = re.compile(r"-?\d+")


@dataclass
class ScanResult:
    """Outcome of a driver store scan: either drivers, or a reason it failed."""
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class DeletionResult:
    """Outcome of attempting to delete a single driver package."""
    published_name: str
    success: bool
    message: str


def _run_pnputil(args: List[str], timeout: float) -> Tuple[Optional[str], Optional[str]]:
    """
    Runs `pnputil <args>` and returns (stdout, None) on success or
    (None, error_message) on failure. Never raises -- every failure mode
    pnputil/subprocess can produce is translated into a human-readable
    error message instead.
    """
    try:
        result = subprocess.run(
            ["pnputil", *args],
            capture_output=True,
            text=True,
            errors="replace",  # never crash on an undecodable byte from a localized console
            timeout=timeout,
            check=True,
        )
        return result.stdout, None
    except FileNotFoundError:
        return None, "'pnputil' not found. This utility must be run on Windows."
    except PermissionError:
        return None, "Permission denied while launching 'pnputil'. Try running as Administrator."
    except subprocess.TimeoutExpired:
        return None, f"'pnputil' timed out after {timeout} seconds."
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        return None, f"'pnputil' exited with code {e.returncode}{detail}"
    except OSError as e:
        return None, f"Unexpected OS error while launching 'pnputil': {e}"


def scan_driver_store(timeout: float = PNPUTIL_TIMEOUT_SECONDS) -> ScanResult:
    """
    Executes 'pnputil /enum-drivers' and parses the output into structured
    dictionaries. Unlike `get_installed_oem_drivers`, failures are reported
    via `ScanResult.error` rather than swallowed, so a caller (e.g. the GUI)
    can tell "no drivers found" apart from "the scan itself failed" (e.g.
    pnputil missing, or a permissions error) and surface that to the user.
    """
    raw_output, error = _run_pnputil(["/enum-drivers"], timeout)
    if error:
        logger.error(error)
        return ScanResult(drivers=[], error=error)

    return ScanResult(drivers=_parse_pnputil_output(raw_output), error=None)


def get_installed_oem_drivers(timeout: float = PNPUTIL_TIMEOUT_SECONDS) -> List[Dict[str, Any]]:
    """
    Executes 'pnputil /enum-drivers' and parses the output into structured dictionaries.

    Returns an empty list (rather than raising) whenever the scan cannot be
    completed -- missing binary, insufficient permissions, timeout, or a
    non-zero exit -- so callers that only care about the driver list (e.g.
    the CLI entry point below) can treat "no drivers found" and "scan
    failed" uniformly. Callers that need to tell those two cases apart
    (e.g. the GUI) should use `scan_driver_store` instead.
    """
    return scan_driver_store(timeout).drivers


def delete_driver(
    published_name: str, force: bool = False, timeout: float = PNPUTIL_TIMEOUT_SECONDS
) -> DeletionResult:
    """
    Deletes a single driver package via `pnputil /delete-driver <name> /uninstall`.
    Requires administrator privileges on Windows. `force=True` adds `/force`,
    which allows removal even if the package is still bound to hardware
    (see README "Safety Considerations").
    """
    args = ["/delete-driver", published_name, "/uninstall"]
    if force:
        args.append("/force")

    raw_output, error = _run_pnputil(args, timeout)
    if error:
        logger.error("Failed to delete %s: %s", published_name, error)
        return DeletionResult(published_name=published_name, success=False, message=error)

    message = (raw_output or "").strip() or "Driver package removed successfully."
    return DeletionResult(published_name=published_name, success=True, message=message)


def _parse_pnputil_output(raw_output: Optional[str]) -> List[Dict[str, Any]]:
    """Parses raw `pnputil /enum-drivers` stdout into a list of driver dicts."""
    if not raw_output or not raw_output.strip():
        return []

    drivers: List[Dict[str, Any]] = []
    # Driver entries are separated by a blank line in real output.
    blocks = raw_output.strip().split("\n\n")

    for block in blocks:
        if "published name" not in block.lower():
            continue

        try:
            driver_info = _parse_driver_block(block)
        except Exception:
            # A single malformed/unexpected block must never take down the
            # whole scan -- skip it and keep parsing the rest.
            logger.warning("Skipping unparsable driver block:\n%s", block, exc_info=True)
            continue

        if driver_info.get("published_name"):
            drivers.append(driver_info)

    return drivers


def _parse_driver_block(block: str) -> Dict[str, Any]:
    """Parses a single 'Published Name: ...' block into a driver dict."""
    driver_info: Dict[str, Any] = {}

    for line in block.splitlines():
        if ":" not in line:
            continue

        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()

        if not val:
            # A recognised field with no value is treated as "not provided"
            # rather than an empty string, so downstream `.get(key, default)`
            # fallbacks behave consistently instead of grouping on "".
            continue

        if "published name" in key:
            driver_info["published_name"] = val
        elif "original name" in key:
            driver_info["original_name"] = val
        elif "provider name" in key:
            driver_info["provider"] = val
        elif "class name" in key:
            driver_info["class"] = val
        elif "class guid" in key:
            driver_info["class_guid"] = val
        elif "signer name" in key:
            driver_info["signer"] = val
        elif "driver" in key and "version" in key:
            # Observed labels across Windows builds: "Driver Version:" and
            # the older/longer "Driver Date and Version:". Match loosely
            # rather than pinning to one exact label.
            driver_info.update(_parse_date_and_version(val))

    return driver_info


def _parse_date_and_version(val: str) -> Dict[str, Any]:
    """Parses a 'Driver Version' value, e.g. '01/10/2024 31.0.15.5123'."""
    parts = val.split()

    if len(parts) < 2:
        return {"date_str": "Unknown", "version_str": val or "Unknown", "date": datetime.min}

    date_str, version_str = parts[0], parts[1]
    return {"date_str": date_str, "version_str": version_str, "date": _parse_date(date_str)}


def _parse_date(date_str: str) -> datetime:
    """Best-effort date parsing; unparsable dates sort as the oldest possible."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    logger.debug("Could not parse driver date %r; treating as unknown.", date_str)
    return datetime.min


def _parse_version_tuple(version_str: Optional[str]) -> Tuple[int, ...]:
    """
    Converts a version string like '31.0.15.5123' into (31, 0, 15, 5123) for
    ordering. Non-numeric or malformed segments become 0 rather than raising,
    and a completely unparsable string sorts as the lowest possible version.
    """
    if not version_str:
        return (0,)

    segments = re.split(r"[.,]", version_str.strip())
    numbers = [
        int(match.group()) if (match := _VERSION_PART_RE.match(segment)) else 0
        for segment in segments
    ]

    return tuple(numbers) if numbers else (0,)


def _sort_key(drv: Dict[str, Any]) -> Tuple[datetime, Tuple[int, ...]]:
    """Newest-first ordering: driver date first, driver version as a tiebreaker."""
    return (drv.get("date", datetime.min), _parse_version_tuple(drv.get("version_str")))


def _group_drivers(drivers: List[Dict[str, Any]]) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
    """Groups drivers by (Provider, Device Class, Original Name)."""
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    for drv in drivers:
        provider = drv.get("provider") or "Unknown"
        dev_class = drv.get("class") or "Unknown"
        orig_name = drv.get("original_name") or ""

        group_key = (provider, dev_class, orig_name)
        grouped.setdefault(group_key, []).append(drv)

    return grouped


def _build_row(drv: Dict[str, Any], is_kept: bool, kept: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "target_inf": drv.get("published_name", "Unknown"),
        "original_name": drv.get("original_name", "N/A"),
        "provider": drv.get("provider", "Unknown"),
        "class": drv.get("class", "Unknown"),
        "class_guid": drv.get("class_guid", "Unknown"),
        "signer": drv.get("signer", "Unknown"),
        "version": drv.get("version_str", "Unknown"),
        "date": drv.get("date_str", "Unknown"),
        "is_kept": is_kept,
        "kept_inf": kept.get("published_name", "Unknown"),
        "kept_version": kept.get("version_str", "Unknown"),
        "reason": reason,
    }


def build_driver_rows(drivers: List[Dict[str, Any]], include_non_duplicates: bool = False) -> List[Dict[str, Any]]:
    """
    Groups drivers the same way `find_duplicate_drivers` does, but returns a
    row for EVERY member of each group -- the newest ("kept") driver first,
    followed by any older superseded drivers -- instead of only the
    superseded ones. Each row is tagged `is_kept` so a caller (e.g. the GUI)
    can render the kept driver as a non-deletable reference row directly
    above the packages it superseded, and never offer it up for selection.

    By default (`include_non_duplicates=False`) groups with nothing
    superseded are omitted entirely, matching the original "duplicates
    only" view. Pass `include_non_duplicates=True` for a full inventory of
    every installed driver, kept or not (the "show all drivers" view).
    """
    rows: List[Dict[str, Any]] = []

    for pkg_list in _group_drivers(drivers).values():
        pkg_list = sorted(pkg_list, key=_sort_key, reverse=True)
        newest, older_versions = pkg_list[0], pkg_list[1:]

        if not older_versions and not include_non_duplicates:
            continue

        rows.append(_build_row(
            newest, is_kept=True, kept=newest,
            reason=(
                "Newest version in this group; superseded packages listed below."
                if older_versions else
                "No duplicate or superseded versions found for this package."
            ),
        ))

        for superseded in older_versions:
            rows.append(_build_row(
                superseded, is_kept=False, kept=newest,
                reason=(
                    f"Superseded by {newest['published_name']} "
                    f"(v{newest.get('version_str', 'Unknown')} - {newest.get('date_str', 'Unknown')})"
                ),
            ))

    return rows


def find_duplicate_drivers(drivers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Groups drivers by (Provider, Device Class, Original Name) and flags every
    package but the newest in each group as superseded. "Newest" is decided
    by driver date first, then driver version as a tiebreaker (or as the
    sole signal when the date is missing/malformed on tied entries).

    Returns only the superseded (deletable) rows. See `build_driver_rows`
    for a version that also includes the kept driver in each group.
    """
    return [row for row in build_driver_rows(drivers, include_non_duplicates=False) if not row["is_kept"]]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("--- Scanning Driver Store via pnputil ---")
    all_drivers = get_installed_oem_drivers()
    print(f"Total Third-Party (OEM) Drivers Found: {len(all_drivers)}\n")

    dups = find_duplicate_drivers(all_drivers)
    print(f"Duplicates/Superseded Packages Detected: {len(dups)}\n")

    for idx, dup in enumerate(dups, 1):
        print(f"[{idx}] Target Deletion: {dup['target_inf']} ({dup['original_name']})")
        print(f"    Provider: {dup['provider']} | Class: {dup['class']}")
        print(f"    Target Version: {dup['version']} ({dup['date']})")
        print(f"    Reason: {dup['reason']}")
        print("-" * 60)
