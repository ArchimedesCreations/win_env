import customtkinter as ctk
from tkinter import messagebox

# --- Configuration ---
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class DriverDeletionApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window settings
        self.title("Windows Driver Clean-up Utility")
        self.geometry("900x600")

        # --- Simulated Driver Data ---
        # In a real app, this would be parsed from `pnputil /enum-drivers`
        self.drivers = [
            {"inf": "oem1.inf", "provider": "NVIDIA", "date": "2024-01-10", "version": "31.0.15.5123", "class": "Display", "hw_id": "PCI\\VEN_10DE&DEV_2484"},
            {"inf": "oem2.inf", "provider": "Realtek", "date": "2023-11-05", "version": "6.0.9600.1", "class": "Audio", "hw_id": "HDAUDIO\\FUNC_01&VEN_10EC&DEV_0256"},
            {"inf": "oem3.inf", "provider": "NVIDIA", "date": "2023-09-15", "version": "31.0.15.3742", "class": "Display", "hw_id": "PCI\\VEN_10DE&DEV_2484"}, # Duplicate of oem1
            {"inf": "oem4.inf", "provider": "Intel", "date": "2024-02-01", "version": "22.250.1.2", "class": "Net", "hw_id": "PCI\\VEN_8086&DEV_0085"},
            {"inf": "oem5.inf", "provider": "NVIDIA", "date": "2022-08-01", "version": "30.0.14.7141", "class": "Display", "hw_id": "PCI\\VEN_10DE&DEV_2484"}, # Duplicate of oem1, oem3
            {"inf": "oem6.inf", "provider": "Realtek", "date": "2023-05-10", "version": "6.0.9500.1", "class": "Audio", "hw_id": "HDAUDIO\\FUNC_01&VEN_10EC&DEV_0256"}, # Duplicate of oem2
        ]

        # Structure to hold UI Checkbox states
        self.checkbox_vars = {} 
        
        # 1. --- UI Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # The table area should expand

        # Header Label
        self.header_label = ctk.CTkLabel(self, text="Superseded Drivers Proposed for Deletion", font=("Arial", 20, "bold"))
        self.header_label.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="w")

        # 2. --- Scrollable Table Area ---
        self.scrollable_frame = ctk.CTkScrollableFrame(self, label_text="Duplicate Driver Packages")
        self.scrollable_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        
        # Configure the table columns grid
        self.scrollable_frame.grid_columnconfigure(0, weight=0) # Checkbox
        self.scrollable_frame.grid_columnconfigure(1, weight=1) # INF Name
        self.scrollable_frame.grid_columnconfigure(2, weight=1) # Provider
        self.scrollable_frame.grid_columnconfigure(3, weight=1) # Version
        self.scrollable_frame.grid_columnconfigure(4, weight=0) # Why Button

        # 3. --- Buttons Area ---
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.grid(row=2, column=0, pady=20, padx=20, sticky="ew")
        
        self.button_frame.grid_columnconfigure(0, weight=1) # Spacer
        
        self.cancel_button = ctk.CTkButton(self.button_frame, text="Cancel", fg_color="gray", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=10)

        self.approve_button = ctk.CTkButton(self.button_frame, text="Approve Deletion", fg_color="red", command=self.approve_deletion)
        self.approve_button.grid(row=0, column=2, padx=10)

        # 4. --- Initialization ---
        self.populate_duplicates()

    def identify_duplicates(self):
        """Simple deterministic logic to group drivers by Hardware ID and flag older ones."""
        grouped = {}
        duplicates = []

        # Group by Hardware ID
        for drv in self.drivers:
            hwid = drv['hw_id']
            if hwid not in grouped:
                grouped[hwid] = []
            grouped[hwid].append(drv)

        # In each group, find the newest and flag others
        for hwid, pkg_list in grouped.items():
            if len(pkg_list) > 1:
                # Sort by date descending (newest first)
                pkg_list.sort(key=lambda x: x['date'], reverse=True)
                newest = pkg_list[0]
                
                # Others are superseded
                for superseded in pkg_list[1:]:
                    duplicates.append({
                        "superseded": superseded,
                        "reason": f"Superseded by {newest['inf']} ({newest['version']})\nHardware ID: {hwid}"
                    })
        return duplicates

    def populate_duplicates(self):
        """Identifies duplicates and draws the table rows."""
        dup_data = self.identify_duplicates()

        # Table Header Row
        ctk.CTkLabel(self.scrollable_frame, text="Select", font=("Arial", 12, "bold")).grid(row=0, column=0, padx=5, pady=5)
        ctk.CTkLabel(self.scrollable_frame, text="Original INF", font=("Arial", 12, "bold")).grid(row=0, column=1, padx=5, pady=5)
        ctk.CTkLabel(self.scrollable_frame, text="Provider", font=("Arial", 12, "bold")).grid(row=0, column=2, padx=5, pady=5)
        ctk.CTkLabel(self.scrollable_frame, text="Version", font=("Arial", 12, "bold")).grid(row=0, column=3, padx=5, pady=5)

        # Data Rows
        for i, item in enumerate(dup_data):
            drv = item['superseded']
            reason = item['reason']
            row_num = i + 1  # Offset for header row

            # -- Checkbox --
            # BooleanVar stores True/False state for this specific checkbox
            var = ctk.BooleanVar(value=True) # Default to checked
            self.checkbox_vars[drv['inf']] = var # Store var reference referenced by INF
            
            cb = ctk.CTkCheckBox(self.scrollable_frame, text="", variable=var, width=20)
            cb.grid(row=row_num, column=0, padx=5, pady=5)

            # -- Text Labels --
            ctk.CTkLabel(self.scrollable_frame, text=drv['inf']).grid(row=row_num, column=1, padx=5, pady=5, sticky="w")
            ctk.CTkLabel(self.scrollable_frame, text=drv['provider']).grid(row=row_num, column=2, padx=5, pady=5, sticky="w")
            ctk.CTkLabel(self.scrollable_frame, text=drv['version']).grid(row=row_num, column=3, padx=5, pady=5, sticky="w")

            # -- Why Button --
            # We use lambda to capture the specific `reason` string for THIS row
            why_btn = ctk.CTkButton(self.scrollable_frame, text="Why?", width=60, height=20, fg_color="transparent", border_width=1,
                                    command=lambda r=reason: self.show_reason(r))
            why_btn.grid(row=row_num, column=4, padx=5, pady=5)

    def show_reason(self, reason_text):
        """Displays a popup explaining why this driver is considered a duplicate."""
        messagebox.showinfo("Duplicate Analysis", reason_text)

    def approve_deletion(self):
        """Handles the approve button. Iterates through checkbox states."""
        selected_infs = []
        for inf_name, var in self.checkbox_vars.items():
            if var.get(): # Check if BooleanVar is True
                selected_infs.append(inf_name)

        if not selected_infs:
            messagebox.showwarning("No Selection", "Please select at least one driver package to delete.")
            return

        # Warning before simulation
        confirm = messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the following {len(selected_infs)} driver packages?\n\n{', '.join(selected_infs)}\n\nThis cannot be undone.")
        
        if confirm:
            print(f"--- SIMULATING DELETION ---")
            for inf in selected_infs:
                # IN A REAL APP, you would run the elevated command here:
                # subprocess.run(["pnputil", "/delete-driver", inf, "/uninstall"], check=True)
                print(f"SUCCESS: Simulated deletion of {inf}")
            print(f"--------------------------")
            messagebox.showinfo("Success", f"Simulated deletion of {len(selected_infs)} driver packages complete. Check console for output.")
            # Typically you would refresh the list here
            self.destroy()

if __name__ == "__main__":
    app = DriverDeletionApp()
    app.mainloop()