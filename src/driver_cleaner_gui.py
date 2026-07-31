import threading
from typing import Any, Dict, List

import customtkinter as ctk
from tkinter import messagebox

from src.driver_actions import build_deletion_summary, delete_selected_drivers, get_selected_infs
from src.driver_parser import DeletionResult, find_duplicate_drivers, scan_driver_store

# --- Configuration ---
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

_TABLE_COLUMNS = 5  # Select, INF, Provider, Version, Why?


class DriverDeletionApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window settings
        self.title("Windows Driver Clean-up Utility")
        self.geometry("900x600")

        # --- State ---
        self.duplicates: List[Dict[str, Any]] = []
        self.checkbox_vars: Dict[str, ctk.BooleanVar] = {}
        self._row_widgets: List[Any] = []  # widgets currently in the table/empty-state, for teardown on refresh
        self._busy = False  # guards against overlapping scan/delete operations

        # 1. --- UI Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # The table area should expand

        # Header Label
        self.header_label = ctk.CTkLabel(self, text="Superseded Drivers Proposed for Deletion", font=("Arial", 20, "bold"))
        self.header_label.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="w")

        # Transient status text ("Scanning...", "Deleting...") shown alongside the header.
        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="e")

        # 2. --- Scrollable Table Area ---
        self.scrollable_frame = ctk.CTkScrollableFrame(self, label_text="Duplicate Driver Packages")
        self.scrollable_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        # Configure the table columns grid
        self.scrollable_frame.grid_columnconfigure(0, weight=0)  # Checkbox
        self.scrollable_frame.grid_columnconfigure(1, weight=1)  # INF Name
        self.scrollable_frame.grid_columnconfigure(2, weight=1)  # Provider
        self.scrollable_frame.grid_columnconfigure(3, weight=1)  # Version
        self.scrollable_frame.grid_columnconfigure(4, weight=0)  # Why Button

        # 3. --- Buttons Area ---
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.grid(row=2, column=0, pady=20, padx=20, sticky="ew")

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

    def start_scan(self):
        """Kicks off a driver store scan on a background thread."""
        if self._busy:
            return
        self._set_busy(True, "Scanning driver store...")
        self._clear_rows()

        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        """Runs off the main thread: never touch widgets here directly."""
        scan_result = scan_driver_store()
        duplicates = find_duplicate_drivers(scan_result.drivers) if not scan_result.error else []
        self.after(0, lambda: self._on_scan_complete(duplicates, scan_result.error))

    def _on_scan_complete(self, duplicates: List[Dict[str, Any]], error):
        """Runs on the main thread via `after()`; safe to touch widgets here."""
        self._set_busy(False)

        if error:
            messagebox.showerror("Scan Failed", f"Could not scan the driver store:\n\n{error}")
            self._render_empty_state(f"Scan failed: {error}")
            return

        self.duplicates = duplicates
        if not duplicates:
            self._render_empty_state("No duplicate or superseded driver packages found.")
        else:
            self.populate_duplicates(duplicates)

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

    def populate_duplicates(self, duplicates: List[Dict[str, Any]]):
        """Draws the table rows for a list of duplicates from find_duplicate_drivers()."""
        self._clear_rows()

        headers = [
            ctk.CTkLabel(self.scrollable_frame, text="Select", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Original INF", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Provider", font=("Arial", 12, "bold")),
            ctk.CTkLabel(self.scrollable_frame, text="Version", font=("Arial", 12, "bold")),
        ]
        for col, header in enumerate(headers):
            header.grid(row=0, column=col, padx=5, pady=5)
        self._row_widgets.extend(headers)

        for i, dup in enumerate(duplicates):
            row_num = i + 1
            inf = dup["target_inf"]

            var = ctk.BooleanVar(value=True)  # Default to checked
            self.checkbox_vars[inf] = var

            cb = ctk.CTkCheckBox(self.scrollable_frame, text="", variable=var, width=20)
            cb.grid(row=row_num, column=0, padx=5, pady=5)

            inf_label = ctk.CTkLabel(self.scrollable_frame, text=inf)
            inf_label.grid(row=row_num, column=1, padx=5, pady=5, sticky="w")

            provider_label = ctk.CTkLabel(self.scrollable_frame, text=dup.get("provider", "Unknown"))
            provider_label.grid(row=row_num, column=2, padx=5, pady=5, sticky="w")

            version_label = ctk.CTkLabel(self.scrollable_frame, text=dup.get("version", "Unknown"))
            version_label.grid(row=row_num, column=3, padx=5, pady=5, sticky="w")

            why_btn = ctk.CTkButton(
                self.scrollable_frame, text="Why?", width=60, height=20, fg_color="transparent", border_width=1,
                command=lambda r=dup.get("reason", ""): self.show_reason(r),
            )
            why_btn.grid(row=row_num, column=4, padx=5, pady=5)

            self._row_widgets.extend([cb, inf_label, provider_label, version_label, why_btn])

    def show_reason(self, reason_text: str):
        """Displays a popup explaining why this driver is considered a duplicate."""
        messagebox.showinfo("Duplicate Analysis", reason_text)

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
        self.status_label.configure(text=status_text if busy else "")


if __name__ == "__main__":
    app = DriverDeletionApp()
    app.mainloop()
