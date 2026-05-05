# src/siliv/utils.py
# Utility functions for macOS interaction (sysctl, version checks).

import sys
import subprocess
import platform
import os
from PyQt6.QtWidgets import QMessageBox # For showing errors related to util failures

def run_command(command):
    """Executes a shell command and returns its output."""
    try:
        # Use sysctl path directly
        result = subprocess.run(f"/usr/sbin/{command}", capture_output=True, text=True, check=True, shell=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Ignore "unknown oid" errors which can happen during version checks
        if "unknown oid" not in e.stderr.lower():
            print(f"Error running command '{command}': {e}\nStderr: {e.stderr}")
        return None
    except FileNotFoundError:
        print(f"Error: Command '/usr/sbin/sysctl' not found.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred running command '{command}': {e}")
        return None

def get_macos_version():
    """Gets the major macOS version number."""
    if platform.system() != "Darwin":
        return 0
    try:
        # platform.mac_ver() returns ('14.4.1', ('', '', ''), 'arm64') on Sonoma ARM
        version_str = platform.mac_ver()[0]
        major_version = int(version_str.split('.')[0])
        return major_version
    except Exception as e:
        print(f"Could not determine macOS version: {e}")
        return 0

def get_vram_sysctl_key():
    """Returns the correct sysctl key based on macOS version."""
    major_version = get_macos_version()
    if major_version >= 15: # Sequoia and later (assuming key stays same for now)
        return "iogpu.wired_limit_mb"
    elif major_version == 14: # Sonoma
        return "iogpu.wired_limit_mb"
    elif major_version == 13: # Ventura
        return "debug.iogpu.wired_limit"
    else:
        # Older versions might use different keys or not support it
        print(f"Warning: Unsupported macOS version {major_version} for VRAM control.")
        return None

def get_total_ram_mb():
    """Gets total system RAM in MB."""
    if platform.system() != "Darwin":
        return None
    output = run_command("sysctl -n hw.memsize")
    if output:
        try:
            ram_bytes = int(output)
            return int(ram_bytes / (1024 * 1024))
        except ValueError:
            print(f"Could not parse RAM size: {output}")
    return None

def calculate_default_vram_mb(total_ram_mb):
    """Calculates the default macOS VRAM allocation based on total RAM."""
    if not total_ram_mb or total_ram_mb <= 0:
        return 0 # Cannot calculate without total RAM

    # Apple's typical default logic (approximated)
    total_ram_gb = total_ram_mb / 1024.0
    if total_ram_gb <= 36:
        # Typically 2/3 for systems up to 36GB? (This is a common heuristic)
        default_vram_mb = int(total_ram_mb * (2/3))
    else:
        # Typically 3/4 for systems above 36GB? (Another heuristic)
        default_vram_mb = int(total_ram_mb * (3/4))

    # Ensure it's not negative
    return max(0, default_vram_mb)

def get_current_vram_mb(total_ram_mb):
    """Gets the currently effective VRAM limit in MB."""
    if platform.system() != "Darwin":
        return 0 # Not on macOS

    vram_key = get_vram_sysctl_key()
    if vram_key is None:
        print("Cannot get VRAM: No valid sysctl key found for this macOS version.")
        # Attempt to return a calculated default as a fallback guess
        return calculate_default_vram_mb(total_ram_mb)

    output = run_command(f"sysctl -n {vram_key}")
    current_limit_mb = 0
    if output:
        try:
            current_limit_mb = int(output)
        except ValueError:
            print(f"Could not parse VRAM size from {vram_key}: {output}")
            # Fallback if parsing fails but key exists
            current_limit_mb = 0 # Indicate we couldn't read it

    # If the sysctl key returns 0, it usually means macOS is using its internal default
    if current_limit_mb == 0:
        default_vram_mb = calculate_default_vram_mb(total_ram_mb)
        # print(f"Current VRAM key '{vram_key}' returned 0, using calculated default: {default_vram_mb} MB")
        return default_vram_mb
    else:
        # print(f"Current VRAM read from '{vram_key}': {current_limit_mb} MB")
        return current_limit_mb

def set_vram_mb(value_mb):
    """Set the macOS VRAM limit using sysctl through sudo.

    This function intentionally invokes `/usr/bin/sudo` directly instead of
    AppleScript's `do shell script ... with administrator privileges` grammar.
    Keeping privilege escalation in the subprocess call avoids nested
    AppleScript/shell quoting and removes the dependency on osascript for this
    operation.

    Args:
        value_mb: Requested VRAM limit in megabytes. The value must be coercible
            to an integer before it is passed to sysctl.

    Returns:
        tuple: (bool: success, str: message)
    """
    if platform.system() != "Darwin":
        return False, "Not running on macOS"

    vram_key = get_vram_sysctl_key()
    if vram_key is None:
        return False, "Cannot set VRAM on this macOS version."

    try:
        target_value = int(value_mb)
    except (TypeError, ValueError):
        return False, f"Invalid VRAM value: {value_mb}"

    command = ["/usr/bin/sudo", "/usr/sbin/sysctl", "-w", f"{vram_key}={target_value}"]

    print(f"Attempting to set {vram_key} to {target_value} via sudo...")

    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        if process.returncode == 0:
            print(f"Successfully set {vram_key} to {target_value}.")
            return True, stdout or "Success"

        error_message = stderr or stdout or "Unknown error"
        print(
            f"Failed to set {vram_key}. "
            f"Return code: {process.returncode}, Error: {error_message}"
        )

        lower_error = error_message.lower()
        if "a password is required" in lower_error or "no tty present" in lower_error:
            friendly_error = (
                "Failed to set VRAM: sudo requires an interactive password prompt.\n"
                "Run this command from a terminal session with sudo available, or use "
                "a privileged helper for GUI execution."
            )
        elif "incorrect password" in lower_error or "sorry, try again" in lower_error:
            friendly_error = "Failed to set VRAM: Incorrect sudo password."
        elif "operation not permitted" in lower_error:
            friendly_error = (
                "Failed to set VRAM: Operation not permitted.\n"
                "Ensure the process has administrator privileges."
            )
        else:
            friendly_error = f"Failed to set VRAM.\nError: {error_message}"

        QMessageBox.warning(None, "VRAM Set Failed", friendly_error)
        return False, friendly_error

    except FileNotFoundError:
        error_msg = "Failed to set VRAM: /usr/bin/sudo was not found."
        print(error_msg)
        QMessageBox.critical(None, "VRAM Set Error", error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"An exception occurred trying to set VRAM: {e}"
        print(error_msg)
        QMessageBox.critical(None, "VRAM Set Error", error_msg)
        return False, error_msg