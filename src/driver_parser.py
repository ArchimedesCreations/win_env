"""
Core logic for scanning the Windows Driver Store via `pnputil` and
identifying duplicate / superseded third-party (OEM) driver packages.
"""

import logging
import re
import subprocess
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


def get_installed_oem_drivers(timeout: float = PNPUTIL_TIMEOUT_SECONDS) -> List[Dict[str, Any]]:
    """
    Executes 'pnputil /enum-drivers' and parses the output into structured dictionaries.

    Returns an empty list (rather than raising) whenever the scan cannot be
    completed -- missing binary, insufficient permissions, timeout, or a
    non-zero exit -- so callers (e.g. the GUI) can treat "no drivers found"
    and "scan failed" uniformly and keep running.
    """
    try:
        result = subprocess.run(
            ["pnputil", "/enum-drivers"],
            capture_output=True,
            text=True,
            errors="replace",  # never crash on an undecodable byte from a localized console
            timeout=timeout,
            check=True,
        )
        raw_output = result.stdout
    except FileNotFoundError:
        logger.error("'pnputil' not found. This utility must be run on Windows.")
        return []
    except PermissionError:
        logger.error("Permission denied while launching 'pnputil'. Try running as Administrator.")
        return []
    except subprocess.TimeoutExpired:
        logger.error("'pnputil /enum-drivers' timed out after %s seconds.", timeout)
        return []
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        logger.error("'pnputil' exited with code %s%s", e.returncode, detail)
        return []
    except OSError as e:
        logger.error("Unexpected OS error while launching 'pnputil': %s", e)
        return []

    return _parse_pnputil_output(raw_output)


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


def find_duplicate_drivers(drivers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Groups drivers by (Provider, Device Class, Original Name) and flags every
    package but the newest in each group as superseded. "Newest" is decided
    by driver date first, then driver version as a tiebreaker (or as the
    sole signal when the date is missing/malformed on tied entries).
    """
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    for drv in drivers:
        provider = drv.get("provider") or "Unknown"
        dev_class = drv.get("class") or "Unknown"
        orig_name = drv.get("original_name") or ""

        group_key = (provider, dev_class, orig_name)
        grouped.setdefault(group_key, []).append(drv)

    duplicates: List[Dict[str, Any]] = []

    for pkg_list in grouped.values():
        if len(pkg_list) <= 1:
            continue

        pkg_list.sort(key=_sort_key, reverse=True)

        newest = pkg_list[0]
        older_versions = pkg_list[1:]

        for superseded in older_versions:
            duplicates.append({
                "target_inf": superseded["published_name"],
                "original_name": superseded.get("original_name", "N/A"),
                "provider": superseded.get("provider", "Unknown"),
                "class": superseded.get("class", "Unknown"),
                "version": superseded.get("version_str", "Unknown"),
                "date": superseded.get("date_str", "Unknown"),
                "kept_version": newest.get("version_str", "Unknown"),
                "kept_inf": newest["published_name"],
                "reason": (
                    f"Superseded by {newest['published_name']} "
                    f"(v{newest.get('version_str', 'Unknown')} - {newest.get('date_str', 'Unknown')})"
                ),
            })

    return duplicates


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
