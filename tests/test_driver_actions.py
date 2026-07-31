"""
Unit tests for src.driver_actions.

This module has no tkinter dependency, so these tests need no display and
no real subprocess calls (driver_parser.delete_driver is mocked).
"""

from unittest.mock import patch

from src.driver_actions import build_deletion_summary, delete_selected_drivers, get_selected_infs
from src.driver_parser import DeletionResult


class _FakeVar:
    """Stand-in for a tkinter.BooleanVar -- just needs a `.get()`."""

    def __init__(self, value: bool):
        self._value = value

    def get(self) -> bool:
        return self._value


class TestGetSelectedInfs:
    def test_returns_only_checked_entries(self):
        checkbox_vars = {
            "oem1.inf": _FakeVar(True),
            "oem2.inf": _FakeVar(False),
            "oem3.inf": _FakeVar(True),
        }
        assert get_selected_infs(checkbox_vars) == ["oem1.inf", "oem3.inf"]

    def test_empty_dict_returns_empty_list(self):
        assert get_selected_infs({}) == []

    def test_none_checked_returns_empty_list(self):
        checkbox_vars = {"oem1.inf": _FakeVar(False), "oem2.inf": _FakeVar(False)}
        assert get_selected_infs(checkbox_vars) == []


class TestDeleteSelectedDrivers:
    def test_calls_delete_driver_once_per_inf_in_order(self):
        infs = ["oem1.inf", "oem2.inf", "oem3.inf"]

        with patch("src.driver_actions.delete_driver") as mock_delete:
            mock_delete.side_effect = lambda inf: DeletionResult(inf, True, "ok")
            results = delete_selected_drivers(infs)

        assert [c.args[0] for c in mock_delete.call_args_list] == infs
        assert [r.published_name for r in results] == infs
        assert all(r.success for r in results)

    def test_empty_selection_calls_nothing(self):
        with patch("src.driver_actions.delete_driver") as mock_delete:
            results = delete_selected_drivers([])

        mock_delete.assert_not_called()
        assert results == []

    def test_preserves_individual_failures(self):
        infs = ["oem1.inf", "oem2.inf"]

        def fake_delete(inf):
            if inf == "oem2.inf":
                return DeletionResult(inf, False, "Access is denied.")
            return DeletionResult(inf, True, "ok")

        with patch("src.driver_actions.delete_driver", side_effect=fake_delete):
            results = delete_selected_drivers(infs)

        assert results[0].success is True
        assert results[1].success is False
        assert results[1].message == "Access is denied."


class TestBuildDeletionSummary:
    def test_no_results(self):
        assert "no driver packages were deleted" in build_deletion_summary([]).lower()

    def test_all_succeeded(self):
        results = [DeletionResult("oem1.inf", True, "ok"), DeletionResult("oem2.inf", True, "ok")]
        summary = build_deletion_summary(results)

        assert "successfully deleted 2" in summary.lower()
        assert "oem1.inf" in summary
        assert "oem2.inf" in summary

    def test_all_failed(self):
        results = [DeletionResult("oem1.inf", False, "Access is denied.")]
        summary = build_deletion_summary(results)

        assert "failed to delete 1" in summary.lower()
        assert "oem1.inf" in summary
        assert "Access is denied." in summary

    def test_mixed_results_mentions_both_groups(self):
        results = [
            DeletionResult("oem1.inf", True, "ok"),
            DeletionResult("oem2.inf", False, "In use by hardware."),
        ]
        summary = build_deletion_summary(results)

        assert "1 of 2" in summary
        assert "oem1.inf" in summary
        assert "oem2.inf" in summary
        assert "In use by hardware." in summary
