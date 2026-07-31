"""
Raw string fixtures shaped like real `pnputil /enum-drivers` stdout, used by
the driver_parser test suite. Kept as plain strings (not fixtures/objects)
so they can be dropped straight into a mocked `subprocess.run` result.
"""

# Every real invocation starts with this banner before the driver blocks.
_PREAMBLE = "Microsoft PnP Utility\n\n"


# --- No duplicates: three unrelated drivers, one per group. ---
NO_DUPLICATES_OUTPUT = _PREAMBLE + """\
Published Name:     oem0.inf
Original Name:      nvcvi.inf
Provider Name:      NVIDIA
Class Name:          Display adapters
Class GUID:          {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:      01/10/2024 31.0.15.5123
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem1.inf
Original Name:      hdxrt.inf
Provider Name:      Realtek
Class Name:          Sound, video and game controllers
Class GUID:          {4d36e96c-e325-11ce-bfc1-08002be10318}
Driver Version:      11/05/2023 6.0.9600.1
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem2.inf
Original Name:      netwew04.inf
Provider Name:      Intel
Class Name:          Network adapters
Class GUID:          {4d36e972-e325-11ce-bfc1-08002be10318}
Driver Version:      02/01/2024 22.250.1.2
Signer Name:          Microsoft Windows Hardware Compatibility Publisher
"""


# --- Single duplicate: two entries, same group, clear version/date winner. ---
SINGLE_DUPLICATE_OUTPUT = _PREAMBLE + """\
Published Name:     oem3.inf
Original Name:      nvcvi.inf
Provider Name:      NVIDIA
Class Name:          Display adapters
Class GUID:          {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:      09/15/2023 31.0.15.3742
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem4.inf
Original Name:      nvcvi.inf
Provider Name:      NVIDIA
Class Name:          Display adapters
Class GUID:          {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:      01/10/2024 31.0.15.5123
Signer Name:          Microsoft Windows Hardware Compatibility Publisher
"""


# --- Multiple superseded: two separate groups, each with >1 old version. ---
MULTIPLE_SUPERSEDED_OUTPUT = _PREAMBLE + """\
Published Name:     oem5.inf
Original Name:      nvcvi.inf
Provider Name:      NVIDIA
Class Name:          Display adapters
Class GUID:          {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:      08/01/2022 30.0.14.7141
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem6.inf
Original Name:      nvcvi.inf
Provider Name:      NVIDIA
Class Name:          Display adapters
Class GUID:          {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:      09/15/2023 31.0.15.3742
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem7.inf
Original Name:      nvcvi.inf
Provider Name:      NVIDIA
Class Name:          Display adapters
Class GUID:          {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:      01/10/2024 31.0.15.5123
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem8.inf
Original Name:      hdxrt.inf
Provider Name:      Realtek
Class Name:          Sound, video and game controllers
Class GUID:          {4d36e96c-e325-11ce-bfc1-08002be10318}
Driver Version:      05/10/2023 6.0.9500.1
Signer Name:          Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem9.inf
Original Name:      hdxrt.inf
Provider Name:      Realtek
Class Name:          Sound, video and game controllers
Class GUID:          {4d36e96c-e325-11ce-bfc1-08002be10318}
Driver Version:      11/05/2023 6.0.9600.1
Signer Name:          Microsoft Windows Hardware Compatibility Publisher
"""


# --- Legacy field label: some Windows builds emit "Driver Date and Version:"
#     instead of "Driver Version:" -- both must parse identically. ---
LEGACY_DATE_AND_VERSION_LABEL_OUTPUT = _PREAMBLE + """\
Published Name:     oem20.inf
Original Name:      prnms003.inf
Provider Name:      Microsoft
Class Name:          Printers
Class GUID:          {4d36e979-e325-11ce-bfc1-08002be10318}
Driver Date and Version:      06/21/2020 10.0.10240.16384
Signer Name:          Microsoft Windows

Published Name:     oem21.inf
Original Name:      prnms003.inf
Provider Name:      Microsoft
Class Name:          Printers
Class GUID:          {4d36e979-e325-11ce-bfc1-08002be10318}
Driver Date and Version:      06/21/2023 10.0.19041.1
Signer Name:          Microsoft Windows
"""


# --- Malformed / missing fields: must not crash, must degrade sensibly. ---
MALFORMED_OUTPUT = _PREAMBLE + """\
Published Name:     oem30.inf
Original Name:      badver.inf
Provider Name:      Contoso
Class Name:          Net
Class GUID:          {4d36e972-e325-11ce-bfc1-08002be10318}
Driver Version:      not-a-date 1.2.a.4
Signer Name:          Contoso Ltd

Published Name:     oem31.inf
Original Name:      badver.inf
Provider Name:      Contoso
Class Name:          Net
Class GUID:          {4d36e972-e325-11ce-bfc1-08002be10318}
Driver Version:      03/01/2024 2.0.0.0
Signer Name:          Contoso Ltd

Published Name:     oem32.inf
Original Name:      nodrv.inf
Provider Name:      Fabrikam
Class Name:          Net
Class GUID:          {4d36e972-e325-11ce-bfc1-08002be10318}
Signer Name:          Fabrikam Inc

Published Name:     oem33.inf
Original Name:      nodrv.inf
Provider Name:      Fabrikam
Class Name:          Net
Class GUID:          {4d36e972-e325-11ce-bfc1-08002be10318}
Driver Version:      04/01/2024 1.0.0.1
Signer Name:          Fabrikam Inc

Published Name:     oem34.inf
Original Name:      blankfields.inf
Provider Name:
Class Name:          Net
Class GUID:          {4d36e972-e325-11ce-bfc1-08002be10318}
Driver Version:      04/01/2024 1.0.0.0
Signer Name:          Fabrikam Inc
"""


# --- No drivers installed at all: just the banner, no entries. ---
EMPTY_OUTPUT = _PREAMBLE


# --- A summary line that superficially resembles a block but has no
#     "Published Name" field; must be ignored rather than mis-parsed. ---
NO_ENTRIES_STRAY_BLOCK_OUTPUT = _PREAMBLE + """\
Published Driver Packages: 0
"""
