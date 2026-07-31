"""
Unit tests for src.driver_parser.

All tests run against mocked `subprocess.run` output, so nothing here ever
shells out to a real `pnputil` or requires Windows/admin rights.
"""

import subprocess
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.driver_parser import (
    delete_driver,
    find_duplicate_drivers,
    get_installed_oem_drivers,
    scan_driver_store,
)
from tests.mock_pnputil_output import (
    EMPTY_OUTPUT,
    LEGACY_DATE_AND_VERSION_LABEL_OUTPUT,
    MALFORMED_OUTPUT,
    MULTIPLE_SUPERSEDED_OUTPUT,
    NO_DUPLICATES_OUTPUT,
    NO_ENTRIES_STRAY_BLOCK_OUTPUT,
    SINGLE_DUPLICATE_OUTPUT,
)


def _completed_process(stdout: str) -> MagicMock:
    """Builds a fake `subprocess.run` return value carrying the given stdout."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.stdout = stdout
    completed.returncode = 0
    return completed


def _mocked_drivers(stdout: str):
    """Calls get_installed_oem_drivers() with subprocess.run mocked to return stdout."""
    with patch("src.driver_parser.subprocess.run", return_value=_completed_process(stdout)) as mock_run:
        drivers = get_installed_oem_drivers()
    mock_run.assert_called_once()
    return drivers


# --------------------------------------------------------------------------
# get_installed_oem_drivers: environment / subprocess failure handling
# --------------------------------------------------------------------------

class TestGetInstalledOemDrivers:
    def test_pnputil_not_found_returns_empty_list(self):
        with patch("src.driver_parser.subprocess.run", side_effect=FileNotFoundError):
            assert get_installed_oem_drivers() == []

    def test_pnputil_permission_denied_returns_empty_list(self):
        with patch("src.driver_parser.subprocess.run", side_effect=PermissionError):
            assert get_installed_oem_drivers() == []

    def test_pnputil_times_out_returns_empty_list(self):
        timeout_error = subprocess.TimeoutExpired(cmd="pnputil", timeout=30)
        with patch("src.driver_parser.subprocess.run", side_effect=timeout_error):
            assert get_installed_oem_drivers() == []

    def test_pnputil_nonzero_exit_returns_empty_list(self):
        error = subprocess.CalledProcessError(returncode=1, cmd="pnputil", stderr="Access is denied.")
        with patch("src.driver_parser.subprocess.run", side_effect=error):
            assert get_installed_oem_drivers() == []

    def test_unexpected_os_error_returns_empty_list(self):
        with patch("src.driver_parser.subprocess.run", side_effect=OSError("boom")):
            assert get_installed_oem_drivers() == []

    def test_empty_output_returns_empty_list(self):
        assert _mocked_drivers(EMPTY_OUTPUT) == []

    def test_none_stdout_returns_empty_list(self):
        # Defensive case: a CompletedProcess with no stdout captured.
        assert _mocked_drivers(None) == []

    def test_stray_block_without_published_name_is_ignored(self):
        assert _mocked_drivers(NO_ENTRIES_STRAY_BLOCK_OUTPUT) == []

    def test_parses_expected_driver_count(self):
        drivers = _mocked_drivers(NO_DUPLICATES_OUTPUT)
        assert len(drivers) == 3
        assert {d["published_name"] for d in drivers} == {"oem0.inf", "oem1.inf", "oem2.inf"}

    def test_parses_provider_class_date_and_version(self):
        drivers = _mocked_drivers(NO_DUPLICATES_OUTPUT)
        nvidia = next(d for d in drivers if d["published_name"] == "oem0.inf")

        assert nvidia["provider"] == "NVIDIA"
        assert nvidia["class"] == "Display adapters"
        assert nvidia["original_name"] == "nvcvi.inf"
        assert nvidia["version_str"] == "31.0.15.5123"
        assert nvidia["date"] == datetime(2024, 1, 10)

    def test_parses_signer_name(self):
        drivers = _mocked_drivers(NO_DUPLICATES_OUTPUT)
        nvidia = next(d for d in drivers if d["published_name"] == "oem0.inf")

        assert nvidia["signer"] == "Microsoft Windows Hardware Compatibility Publisher"

    def test_supports_legacy_driver_date_and_version_label(self):
        # Some Windows builds label this field "Driver Date and Version:"
        # instead of "Driver Version:" -- both must parse identically.
        drivers = _mocked_drivers(LEGACY_DATE_AND_VERSION_LABEL_OUTPUT)

        assert len(drivers) == 2
        assert all(d["date"] != datetime.min for d in drivers)
        assert all(d["version_str"] != "Unknown" for d in drivers)


# --------------------------------------------------------------------------
# find_duplicate_drivers: duplicate / supersession detection
# --------------------------------------------------------------------------

class TestFindDuplicateDrivers:
    def test_no_duplicates_present(self):
        drivers = _mocked_drivers(NO_DUPLICATES_OUTPUT)
        assert find_duplicate_drivers(drivers) == []

    def test_no_drivers_returns_no_duplicates(self):
        assert find_duplicate_drivers([]) == []

    def test_single_driver_in_group_is_not_a_duplicate(self):
        drivers = _mocked_drivers(NO_DUPLICATES_OUTPUT)[:1]
        assert find_duplicate_drivers(drivers) == []

    def test_single_duplicate_with_clear_version_difference(self):
        drivers = _mocked_drivers(SINGLE_DUPLICATE_OUTPUT)
        duplicates = find_duplicate_drivers(drivers)

        assert len(duplicates) == 1
        dup = duplicates[0]
        assert dup["target_inf"] == "oem3.inf"   # older version, flagged
        assert dup["kept_inf"] == "oem4.inf"     # newer version, kept
        assert dup["version"] == "31.0.15.3742"
        assert dup["kept_version"] == "31.0.15.5123"

    def test_duplicate_entry_shape_and_reason_text(self):
        drivers = _mocked_drivers(SINGLE_DUPLICATE_OUTPUT)
        dup = find_duplicate_drivers(drivers)[0]

        expected_keys = {
            "target_inf", "original_name", "provider", "class", "signer",
            "version", "date", "kept_version", "kept_inf", "reason",
        }
        assert expected_keys.issubset(dup.keys())
        assert dup["kept_inf"] in dup["reason"]
        assert dup["kept_version"] in dup["reason"]
        assert dup["signer"] == "Microsoft Windows Hardware Compatibility Publisher"

    def test_multiple_superseded_versions_of_same_hardware(self):
        drivers = _mocked_drivers(MULTIPLE_SUPERSEDED_OUTPUT)
        duplicates = find_duplicate_drivers(drivers)

        nvidia_dups = {d["target_inf"] for d in duplicates if d["provider"] == "NVIDIA"}
        realtek_dups = {d["target_inf"] for d in duplicates if d["provider"] == "Realtek"}

        # 3 NVIDIA entries -> newest (oem7) kept, older 2 flagged.
        assert nvidia_dups == {"oem5.inf", "oem6.inf"}
        assert all(d["kept_inf"] == "oem7.inf" for d in duplicates if d["provider"] == "NVIDIA")

        # 2 Realtek entries -> newest (oem9) kept, older 1 flagged.
        assert realtek_dups == {"oem8.inf"}
        assert all(d["kept_inf"] == "oem9.inf" for d in duplicates if d["provider"] == "Realtek")

        assert len(duplicates) == 3

    def test_malformed_or_missing_date_and_version_entries(self):
        drivers = _mocked_drivers(MALFORMED_OUTPUT)
        # The main assertion here is implicit: parsing 5 malformed/partial
        # entries must not raise before we even get this far.
        duplicates = find_duplicate_drivers(drivers)
        by_target = {d["target_inf"]: d for d in duplicates}

        # oem30 (unparsable date, partially non-numeric version) is
        # correctly superseded by the well-formed oem31.
        assert by_target["oem30.inf"]["kept_inf"] == "oem31.inf"

        # oem32 (Driver Version line missing entirely) is superseded by
        # oem33, which has a valid date/version.
        assert by_target["oem32.inf"]["kept_inf"] == "oem33.inf"

        # oem34 has a blank Provider Name field. It must not crash the
        # parser, and must not be silently merged into an unrelated group
        # just because both fall back to "Unknown".
        assert "oem34.inf" not in by_target

    def test_blank_field_falls_back_to_unknown_not_empty_string(self):
        drivers = _mocked_drivers(MALFORMED_OUTPUT)
        blank_provider_drv = next(d for d in drivers if d["published_name"] == "oem34.inf")

        # A field present in the output but with no value must not leave an
        # empty-string artifact that silently groups differently from a
        # driver where the field was absent entirely.
        assert blank_provider_drv.get("provider") is None


# --------------------------------------------------------------------------
# scan_driver_store: same scan as get_installed_oem_drivers, but reports
# *why* it came back empty instead of swallowing the failure.
# --------------------------------------------------------------------------

class TestScanDriverStore:
    def test_success_has_no_error_and_correct_drivers(self):
        with patch("src.driver_parser.subprocess.run", return_value=_completed_process(NO_DUPLICATES_OUTPUT)):
            result = scan_driver_store()

        assert result.error is None
        assert len(result.drivers) == 3

    def test_pnputil_not_found_reports_error(self):
        with patch("src.driver_parser.subprocess.run", side_effect=FileNotFoundError):
            result = scan_driver_store()

        assert result.drivers == []
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_permission_denied_reports_error(self):
        with patch("src.driver_parser.subprocess.run", side_effect=PermissionError):
            result = scan_driver_store()

        assert result.drivers == []
        assert "permission" in result.error.lower()

    def test_timeout_reports_error(self):
        timeout_error = subprocess.TimeoutExpired(cmd="pnputil", timeout=30)
        with patch("src.driver_parser.subprocess.run", side_effect=timeout_error):
            result = scan_driver_store()

        assert result.drivers == []
        assert "timed out" in result.error.lower()

    def test_nonzero_exit_reports_stderr_in_error(self):
        error = subprocess.CalledProcessError(returncode=1, cmd="pnputil", stderr="Access is denied.")
        with patch("src.driver_parser.subprocess.run", side_effect=error):
            result = scan_driver_store()

        assert result.drivers == []
        assert "Access is denied." in result.error


# --------------------------------------------------------------------------
# delete_driver: `pnputil /delete-driver <name> /uninstall`
# --------------------------------------------------------------------------

class TestDeleteDriver:
    def test_success_returns_success_result(self):
        with patch("src.driver_parser.subprocess.run", return_value=_completed_process("Driver package deleted successfully.")):
            result = delete_driver("oem3.inf")

        assert result.success is True
        assert result.published_name == "oem3.inf"
        assert "deleted successfully" in result.message.lower()

    def test_permission_denied_returns_failure_result(self):
        error = subprocess.CalledProcessError(returncode=1, cmd="pnputil", stderr="Access is denied.")
        with patch("src.driver_parser.subprocess.run", side_effect=error):
            result = delete_driver("oem3.inf")

        assert result.success is False
        assert result.published_name == "oem3.inf"
        assert "Access is denied." in result.message

    def test_pnputil_not_found_returns_failure_result(self):
        with patch("src.driver_parser.subprocess.run", side_effect=FileNotFoundError):
            result = delete_driver("oem3.inf")

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_timeout_returns_failure_result(self):
        timeout_error = subprocess.TimeoutExpired(cmd="pnputil", timeout=30)
        with patch("src.driver_parser.subprocess.run", side_effect=timeout_error):
            result = delete_driver("oem3.inf")

        assert result.success is False
        assert "timed out" in result.message.lower()

    def test_builds_expected_command_without_force(self):
        with patch("src.driver_parser.subprocess.run", return_value=_completed_process("OK")) as mock_run:
            delete_driver("oem3.inf")

        args = mock_run.call_args[0][0]
        assert args == ["pnputil", "/delete-driver", "oem3.inf", "/uninstall"]

    def test_force_flag_appends_force_argument(self):
        with patch("src.driver_parser.subprocess.run", return_value=_completed_process("OK")) as mock_run:
            delete_driver("oem3.inf", force=True)

        args = mock_run.call_args[0][0]
        assert args == ["pnputil", "/delete-driver", "oem3.inf", "/uninstall", "/force"]
