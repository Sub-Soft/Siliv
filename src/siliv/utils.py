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
    """Sets the VRAM limit using the appropriate sysctl key via osascript.

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
    except ValueError:
        return False, f"Invalid VRAM value: {value_mb}"

    # Construct the shell command to be run with administrator privileges
    command_to_run = f'/usr/sbin/sysctl -w {vram_key}={target_value}'

    # Escape the command for embedding within the AppleScript string
    escaped_command = command_to_run.replace('"', '\\"')

    # Construct the full osascript command
    osascript_cmd = f"osascript -e 'do shell script \"{escaped_command}\" with administrator privileges'"

    print(f"Attempting to set {vram_key} to {target_value} via osascript...")

    try:
        # Run the osascript command
        process = subprocess.Popen(osascript_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()

        # Check the result
        if process.returncode == 0:
            print(f"Successfully set {vram_key} to {target_value}.")
            return True, "Success"
        else:
            # Handle potential errors, including user cancellation
            error_message = stderr.strip()
            if "User canceled" in error_message or "(-128)" in error_message:
                 print("VRAM setting canceled by user.")
                 return False, "Cancelled by user."
            else:
                print(f"Failed to set {vram_key}. Return code: {process.returncode}, Stderr: {error_message}")
                # Provide a more user-friendly error if possible
                if "operation not permitted" in error_message.lower():
                    friendly_error = "Failed to set VRAM: Operation not permitted.\nEnsure you have administrator rights."
                else:
                    friendly_error = f"Failed to set VRAM.\nError: {error_message}"
                # Display error to user via MessageBox
                QMessageBox.warning(None, "VRAM Set Failed", friendly_error)
                return False, friendly_error

    except Exception as e:
        error_msg = f"An exception occurred trying to set VRAM: {e}"
        print(error_msg)
        QMessageBox.critical(None, "VRAM Set Error", error_msg)
        return False, error_msg

# ---------------------------------------------------------------------------
# Launch at Login helpers
# ---------------------------------------------------------------------------
def set_launch_at_login(enabled):
    """
    Enables or disables launching Siliv automatically when the user logs in
    by creating or removing a LaunchAgent plist in the user's LaunchAgents
    folder.

    Args:
        enabled (bool): True to enable autostart, False to disable.

    Returns:
        tuple(bool success, str message)
    """
    if platform.system() != "Darwin":
        return False, "Launch at login only supported on macOS."

    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_path = os.path.join(plist_dir, "com.siliv.vramtool.plist")

    # Determine executable path: when bundled with PyInstaller this resolves
    # to the deployed binary; during development it will be the Python script.
    exec_path = os.path.abspath(sys.argv[0])

    if enabled:
        try:
            os.makedirs(plist_dir, exist_ok=True)
            plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.siliv.vramtool</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exec_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>'''
            with open(plist_path, "w", encoding="utf-8") as fp:
                fp.write(plist_content)
            # Load the agent; ignore non-zero exit codes if already loaded
            subprocess.run(["launchctl", "load", plist_path], check=False)
            return True, "Enabled launch at login"
        except Exception as e:
            return False, f"Failed to enable launch at login: {e}"
    else:
        try:
            subprocess.run(["launchctl", "unload", plist_path], check=False)
            if os.path.exists(plist_path):
                os.remove(plist_path)
            return True, "Disabled launch at login"
        except Exception as e:
            return False, f"Failed to disable launch at login: {e}"
