"""
Integration tests for src.driver_cleaner_gui.

These create real `DriverDeletionApp` instances with real `customtkinter`
widgets (this box has a display available via WSLg). `subprocess.run` and
`tkinter.messagebox` are mocked so nothing shells out to a real `pnputil`
and no blocking modal dialogs pop up. Background work is driven
deterministically: worker methods are called directly (instead of via a
real `threading.Thread`) and `app.update()` flushes the `after(0, ...)`
callback they schedule, exercising the real Tk cross-thread-update
mechanism without any actual thread races.
"""

import subprocess
from unittest.mock import MagicMock, patch

import customtkinter as ctk
import pytest

from src.driver_cleaner_gui import DriverDeletionApp
from src.driver_parser import DeletionResult
from tests.mock_pnputil_output import (
    MULTIPLE_SUPERSEDED_OUTPUT,
    NO_DUPLICATES_OUTPUT,
    SINGLE_DUPLICATE_OUTPUT,
)


def _completed_process(stdout: str) -> MagicMock:
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.stdout = stdout
    completed.returncode = 0
    return completed


def _run_target_synchronously(target=None, args=(), **kwargs):
    """A fake threading.Thread whose .start() runs the target immediately."""
    thread = MagicMock()
    thread.start.side_effect = lambda: target(*args)
    return thread


def _run_scan(app: DriverDeletionApp, stdout: str):
    """Drives a full scan synchronously against mocked pnputil stdout."""
    with patch("src.driver_parser.subprocess.run", return_value=_completed_process(stdout)):
        app._scan_worker()
    app.update()


@pytest.fixture
def app():
    """
    A real DriverDeletionApp with real widgets, but with the automatic
    __init__ scan neutralised (threading.Thread.start() is a no-op here) so
    each test drives scanning/deletion deterministically instead of racing
    a real background thread from construction.
    """
    with patch("src.driver_cleaner_gui.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value = MagicMock()  # .start() does nothing
        instance = DriverDeletionApp()
    yield instance
    instance.destroy()


class TestScanning:
    def test_populates_checkbox_rows_for_each_duplicate(self, app):
        _run_scan(app, MULTIPLE_SUPERSEDED_OUTPUT)

        assert len(app.duplicates) == 3
        assert set(app.checkbox_vars.keys()) == {"oem5.inf", "oem6.inf", "oem8.inf"}
        # Default-checked: every real BooleanVar should read back True.
        assert all(var.get() for var in app.checkbox_vars.values())

    def test_no_duplicates_renders_empty_state_not_rows(self, app):
        _run_scan(app, NO_DUPLICATES_OUTPUT)

        assert app.duplicates == []
        assert app.checkbox_vars == {}
        # A single label for the empty-state message, no checkbox rows.
        assert len(app._row_widgets) == 1

    def test_scan_failure_shows_error_with_real_reason_and_empty_state(self, app):
        with patch("src.driver_parser.subprocess.run", side_effect=FileNotFoundError), \
             patch("src.driver_cleaner_gui.messagebox.showerror") as mock_showerror:
            app._scan_worker()
            app.update()

        assert app.checkbox_vars == {}
        mock_showerror.assert_called_once()
        assert "not found" in mock_showerror.call_args[0][1].lower()

    def test_rescanning_clears_previous_rows_instead_of_accumulating(self, app):
        _run_scan(app, MULTIPLE_SUPERSEDED_OUTPUT)
        first_scan_widget_count = len(app._row_widgets)

        _run_scan(app, SINGLE_DUPLICATE_OUTPUT)

        assert set(app.checkbox_vars.keys()) == {"oem3.inf"}
        # If old widgets weren't torn down, this would only grow.
        assert len(app._row_widgets) < first_scan_widget_count

    def test_busy_flag_cleared_after_scan_completes(self, app):
        assert app._busy is True  # left busy by __init__'s neutralised start_scan
        _run_scan(app, NO_DUPLICATES_OUTPUT)
        assert app._busy is False

    def test_reason_and_extra_fields_shown_inline_without_a_click(self, app):
        _run_scan(app, SINGLE_DUPLICATE_OUTPUT)
        dup = app.duplicates[0]

        label_texts = {w.cget("text") for w in app._row_widgets if isinstance(w, ctk.CTkLabel)}

        # The "why" text is readable directly in the table now.
        assert dup["reason"] in label_texts
        # Device Class, Date, and Signer are all rendered as columns too.
        assert dup["class"] in label_texts
        assert dup["date"] in label_texts
        assert dup["signer"] in label_texts

        # No clickable "Why?" affordance should exist anymore.
        assert not any(isinstance(w, ctk.CTkButton) for w in app._row_widgets)
        assert not hasattr(app, "show_reason")


class TestApproveDeletionGuards:
    def test_no_selection_warns_and_does_not_delete(self, app):
        _run_scan(app, NO_DUPLICATES_OUTPUT)  # leaves checkbox_vars empty

        with patch("src.driver_cleaner_gui.messagebox.showwarning") as mock_warn, \
             patch("src.driver_actions.delete_driver") as mock_delete:
            app.approve_deletion()

        mock_warn.assert_called_once()
        mock_delete.assert_not_called()

    def test_user_declines_confirmation_does_not_delete(self, app):
        _run_scan(app, SINGLE_DUPLICATE_OUTPUT)

        with patch("src.driver_cleaner_gui.messagebox.askyesno", return_value=False), \
             patch("src.driver_actions.delete_driver") as mock_delete:
            app.approve_deletion()

        mock_delete.assert_not_called()


class TestApproveDeletionConfirmedFlow:
    def test_confirmed_deletion_calls_delete_driver_and_refreshes(self, app):
        _run_scan(app, SINGLE_DUPLICATE_OUTPUT)
        assert set(app.checkbox_vars.keys()) == {"oem3.inf"}

        with patch("src.driver_cleaner_gui.threading.Thread", side_effect=_run_target_synchronously), \
             patch("src.driver_cleaner_gui.messagebox.askyesno", return_value=True), \
             patch("src.driver_cleaner_gui.messagebox.showinfo") as mock_showinfo, \
             patch("src.driver_actions.delete_driver", return_value=DeletionResult("oem3.inf", True, "ok")) as mock_delete, \
             patch.object(app, "start_scan") as mock_start_scan:
            app.approve_deletion()
            app.update()  # flush the after(0, _on_deletion_complete) callback

        mock_delete.assert_called_once_with("oem3.inf")
        mock_showinfo.assert_called_once()
        # Per the requested UX: refresh the list, don't just close the app.
        mock_start_scan.assert_called_once()

    def test_confirmed_deletion_with_failure_shows_warning_not_info(self, app):
        _run_scan(app, SINGLE_DUPLICATE_OUTPUT)

        with patch("src.driver_cleaner_gui.threading.Thread", side_effect=_run_target_synchronously), \
             patch("src.driver_cleaner_gui.messagebox.askyesno", return_value=True), \
             patch("src.driver_cleaner_gui.messagebox.showwarning") as mock_showwarning, \
             patch("src.driver_cleaner_gui.messagebox.showinfo") as mock_showinfo, \
             patch("src.driver_actions.delete_driver", return_value=DeletionResult("oem3.inf", False, "Access is denied.")), \
             patch.object(app, "start_scan"):
            app.approve_deletion()
            app.update()

        mock_showwarning.assert_called_once()
        mock_showinfo.assert_not_called()
        assert "Access is denied." in mock_showwarning.call_args[0][1]

    def test_busy_during_deletion_blocks_reentrant_approve(self, app):
        _run_scan(app, SINGLE_DUPLICATE_OUTPUT)
        app._busy = True

        with patch("src.driver_cleaner_gui.messagebox.askyesno") as mock_ask, \
             patch("src.driver_actions.delete_driver") as mock_delete:
            app.approve_deletion()

        mock_ask.assert_not_called()
        mock_delete.assert_not_called()
