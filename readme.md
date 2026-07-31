# Windows Driver Clean-up Utility

An interactive desktop application for Windows that scans the Driver Store using `pnputil`, identifies superseded or duplicate OEM driver packages (`oem*.inf`), and allows users to safely select and delete them via a modern GUI.

---

## Features

* **PnP Store Scanning:** Queries native Windows `pnputil /enum-drivers` to extract installed third-party drivers.
* **Deterministic Duplicate Detection:** Groups drivers by Provider, Device Class, and Original Name to flag older versions superseded by newer releases.
* **Interactive UI:** Built with `CustomTkinter` featuring scrollable lists, checkboxes for multi-selection, and explicit "Why?" breakdown buttons for each candidate.
* **Safety & Execution:** Prevents accidental deletion via confirmation dialogs and requires explicit administrative privileges before staging uninstallation.

---

## Repository Structure

```text
.
├── .venv/                         # Local Python virtual environment
├── .gitignore                     # Git exclusion rules
├── README.md                      # Project documentation
├── requirements.txt               # Dependencies (customtkinter)
└── src/                           # Application source code
    ├── __init__.py                # Package initializer
    ├── driver_cleaner_gui.py      # Main CustomTkinter GUI interface
    └── driver_parser.py           # Core pnputil execution & duplicate matching logic
```

---

## Prerequisites & Installation

### 1. Requirements
* **Operating System:** Windows 10/11 (or WSL2 with PowerShell Interop)
* **Python:** Python 3.10+
* **Permissions:** Administrator privileges (required by `pnputil` for driver removal)

### 2. Environment Setup

Clone the repository and set up a virtual environment:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment (Linux / WSL)
source .venv/bin/activate

# Activate virtual environment (Windows PowerShell)
# .venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Running the GUI Application (Elevated)

Driver uninstallation requires Administrator privileges. Run the main entry point from an elevated terminal session.

#### Option A: Running from Elevated PowerShell (Windows Native)
```powershell
python src\driver_cleaner_gui.py
```

#### Option B: Triggering from WSL
```bash
powershell.exe -Command "Start-Process python -ArgumentList 'src\driver_cleaner_gui.py' -Verb RunAs"
```

---

### Command-Line Parser Test

To test driver parsing and duplicate detection without launching the GUI:

```bash
python src/driver_parser.py
```

---

## Duplicate Identification Logic

A driver package is flagged for deletion if:
1. It shares a matching **Provider Name**, **Class Name**, and **Original INF Name** with another installed driver.
2. Its **Driver Date** or **Driver Version** is strictly older than the highest version installed for that matching group.

---

## Safety Considerations

* **System Restore Point:** It is recommended to create a Windows System Restore Point prior to removing driver packages.
* **Active Hardware Locks:** `pnputil` will reject deletion if a target driver package is actively bound to plugged-in hardware unless forced.