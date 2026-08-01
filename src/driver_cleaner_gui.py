import threading
from typing import Any, Dict, List

import customtkinter as ctk
from tkinter import messagebox

from src.driver_actions import build_deletion_summary, delete_selected_drivers, get_selected_infs
from src.driver_parser import DeletionResult, build_driver_rows, scan_driver_store

# --- Configuration ---
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

_TABLE_COLUMNS = 9  # Select, INF, Provider, Class, Class GUID, Date, Version, Signer, Reason
_KEPT_ROW_FONT = ("Arial", 12, "bold")


class DriverDeletionApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window settings
        self.title("Windows Driver Clean-up Utility")
        self.geometry("1450x680")

        # --- State ---
        self.rows: List[Dict[str, Any]] = []
        self.checkbox_vars: Dict[str, ctk.BooleanVar] = {}
        self._row_widgets: List[Any] = []  # widgets currently in the table/empty-state, for teardown on refresh
        self._busy = False  # guards against overlapping scan/delete operations
        self.show_all_var = ctk.BooleanVar(value=False)

        # 1. --- UI Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # The table area should expand

        # Header Label
        self.header_label = ctk.CTkLabel(self, text="Superseded Drivers Proposed for Deletion", font=("Arial", 20, "bold"))
        self.header_label.grid(row=0, column=0, pady=(20, 5), padx=20, sticky="w")

        # Transient status text ("Scanning...", "Deleting...") shown alongside the header.
        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.grid(row=0, column=0, pady=(20, 5), padx=20, sticky="e")

        # Toolbar: toggle between "duplicates only" and "every installed driver".
        self.toolbar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.toolbar_frame.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

        self.show_all_switch = ctk.CTkSwitch(
            self.toolbar_frame, text="Show all drivers (not just duplicates)",
            variable=self.show_all_var, command=self._on_toggle_show_all,
        )
        self.show_all_switch.grid(row=0, column=0)

        # 2. --- Scrollable Table Area ---
        self.scrollable_frame = ctk.CTkScrollableFrame(self, label_text="Duplicate Driver Packages")
        self.scrollable_frame.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")

        # Configure the table columns grid
        self.scrollable_frame.grid_columnconfigure(0, weight=0)  # Checkbox
        self.scrollable_frame.grid_columnconfigure(1, weight=1)  # INF Name
        self.scrollable_frame.grid_columnconfigure(2, weight=1)  # Provider
        self.scrollable_frame.grid_columnconfigure(3, weight=1)  # Device Class
        self.scrollable_frame.grid_columnconfigure(4, weight=1)  # Class GUID
        self.scrollable_frame.grid_columnconfigure(5, weight=0)  # Date
        self.scrollable_frame.grid_columnconfigure(6, weight=0)  # Version
        self.scrollable_frame.grid_columnconfigure(7, weight=1)  # Signer
        self.scrollable_frame.grid_columnconfigure(8, weight=2)  # Reason (Why kept / superseded)

        # 3. --- Buttons Area ---
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.grid(row=3, column=0, pady=20, padx=20, sticky="ew")

        self.button_frame.grid_columnconfigure(0, weight=1)  # Spacer

        self.cancel_button = ctk.CTkButton(self.button_frame, text="Cancel", fg_color="gray", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=10)

        self.approve_button = ctk.CTkButton(self.button_frame, text="Approve Deletion", fg_color="red", command=self.approve_deletion)
        self.approve_button.grid(row=0, column=2, padx=10)

        # 4. --- Initialization ---
        self.start_scan()

    # ----------------------------------------------------------------
    # Scanning
    # ----------------------------------------------------------------

    def _on_toggle_show_all(self):
        self.start_scan()

    def start_scan(self):
        """Kicks off a driver store scan on a background thread."""
        if self._busy:
            return
        self._set_busy(True, "Scanning driver store...")
        self._clear_rows()

        show_all = bool(self.show_all_var.get())
        threading.Thread(target=self._scan_worker, args=(show_all,), daemon=True).start()

    def _scan_worker(self, show_all: bool):
        """Runs off the main thread: never touch widgets here directly."""
        scan_result = scan_driver_store()
        rows = build_driver_rows(scan_result.drivers, include_non_duplicates=show_all) if not scan_result.error else []
        self.after(0, lambda: self._on_scan_complete(rows, scan_result.error, show_all))

    def _on_scan_complete(self, rows: List[Dict[str, Any]], error, show_all: bool):
        """Runs on the main thread via `after()`; safe to touch widgets here."""
        self._set_busy(False)

        if error:
            messagebox.showerror("Scan Failed", f"Could not scan the driver store:\n\n{error}")
            self._render_empty_state(f"Scan failed: {error}")
            return

        self.rows = rows
        if not rows:
            message = (
                "No drivers found." if show_all else
                "No duplicate or superseded driver packages found."
            )
            self._render_empty_state(message)
        else:
            self.populate_rows(rows)

    # ----------------------------------------------------------------
    # Table rendering
    # ----------------------------------------------------------------

    def _clear_rows(self):
        """Tears down whatever is currently in the table/empty-state area."""
        for widget in self._row_widgets:
            widget.destroy()
        self._row_widgets = []
        self.checkbox_vars = {}

    def _render_empty_state(self, message: str):
        self._clear_rows()
        label = ctk.CTkLabel(self.scrollable_frame, text=message)
        label.grid(row=0, column=0, columnspan=_TABLE_COLUMNS, padx=10, pady=20)
        self._row_widgets.append(label)

    def populate_rows(self, rows: List[Dict[str, Any]]):
        """
        Draws the table rows from build_driver_rows(). Each group's kept
        (newest) driver is rendered directly above the packages it
        superseded, with a disabled, permanently-unchecked checkbox --
        it's shown for context but is never selectable and never deleted.
        """
        self._clear_rows()

        headers = [
            ctk.CTkLabel(self.scrollable_frame, text="Select", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Original INF", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Provider", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Device Class", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Class GUID", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Date", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Version", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Signer", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Why Superseded", font=("Arial", 12, "bold")),
        ]
        for col, header in enumerate(headers):
            header.grid(row=0, column=col, padx=5, pady=5)
        self._row_widgets.extend(headers)

        for i, row in enumerate(rows):
            row_num = i + 1
            inf = row["target_inf"]
            is_kept = row.get("is_kept", False)

            if is_kept:
                # The retained driver is shown for context, never for deletion:
                # no BooleanVar, never added to checkbox_vars, disabled widget.
                cb = ctk.CTkCheckBox(self.scrollable_frame, text="", width=20, state="disabled")
                cb.deselect()
            else:
                var = ctk.BooleanVar(value=True)  # Default to checked
                self.checkbox_vars[inf] = var
                cb = ctk.CTkCheckBox(self.scrollable_frame, text="", variable=var, width=20)
            cb.grid(row=row_num, column=0, padx=5, pady=5)
            self._row_widgets.append(cb)

            cells = [
                inf,
                row.get("provider", "Unknown"),
                row.get("class", "Unknown"),
                row.get("class_guid", "Unknown"),
                row.get("date", "Unknown"),
                row.get("version", "Unknown"),
                row.get("signer", "Unknown"),
                row.get("reason", ""),
            ]
            label_kwargs = {"font": _KEPT_ROW_FONT} if is_kept else {}
            for col, text in enumerate(cells, start=1):
                label = ctk.CTkLabel(self.scrollable_frame, text=text, **label_kwargs)
                label.grid(row=row_num, column=col, padx=5, pady=5, sticky="w")
                self._row_widgets.append(label)

    # ----------------------------------------------------------------
    # Deletion
    # ----------------------------------------------------------------

    def approve_deletion(self):
        """Handles the approve button: confirms, then deletes selected packages on a background thread."""
        if self._busy:
            return

        selected_infs = get_selected_infs(self.checkbox_vars)
        if not selected_infs:
            messagebox.showwarning("No Selection", "Please select at least one driver package to delete.")
            return

        confirm = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete the following {len(selected_infs)} driver packages?\n\n"
            f"{', '.join(selected_infs)}\n\nThis cannot be undone.",
        )
        if not confirm:
            return

        self._set_busy(True, "Deleting selected driver packages...")
        threading.Thread(target=self._delete_worker, args=(selected_infs,), daemon=True).start()

    def _delete_worker(self, selected_infs: List[str]):
        """Runs off the main thread: never touch widgets here directly."""
        results = delete_selected_drivers(selected_infs)
        self.after(0, lambda: self._on_deletion_complete(results))

    def _on_deletion_complete(self, results: List[DeletionResult]):
        """Runs on the main thread via `after()`; safe to touch widgets here."""
        self._set_busy(False)

        summary = build_deletion_summary(results)
        if any(not r.success for r in results):
            messagebox.showwarning("Deletion Results", summary)
        else:
            messagebox.showinfo("Deletion Results", summary)

        # Reflect what's actually on the system now rather than assuming success.
        self.start_scan()

    # ----------------------------------------------------------------
    # Shared helpers
    # ----------------------------------------------------------------

    def _set_busy(self, busy: bool, status_text: str = ""):
        self._busy = busy
        self.approve_button.configure(state="disabled" if busy else "normal")
        self.show_all_switch.configure(state="disabled" if busy else "normal")
        self.status_label.configure(text=status_text if busy else "")


if __name__ == "__main__":
    app = DriverDeletionApp()
    app.mainloop()
