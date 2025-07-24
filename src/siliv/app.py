# src/siliv/app.py
# Manages the menu bar icon and VRAM logic using PyQt6.

import platform
import math # Needed for rounding/snapping

# PyQt6 Imports
from PyQt6.QtWidgets import (
     QApplication, QSystemTrayIcon, QMenu, QMessageBox,
     QWidgetAction, QCheckBox
 )
# Import QSettings
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QSettings
from PyQt6.QtGui import QIcon, QCursor, QAction

# Local Imports
from siliv import config # config.RESERVED_SYSTEM_RAM_MIN will be used for warning threshold
from siliv import utils
from siliv.ui import widgets

# --- Settings Constants ---
ORGANIZATION_NAME = "SilivProject" # Or your preferred organization name
APPLICATION_NAME = "Siliv"
SAVED_VRAM_KEY = "user/savedVramMb"
LAUNCH_AT_LOGIN_KEY = "user/launchAtLogin"
# --------------------------

class MenuBarApp(QObject):
    def __init__(self, icon_path, parent=None):
        super().__init__(parent)
        # --- State Variables ---
        self.total_ram_mb = 0
        self.current_vram_mb = 0
        self.reserved_ram_mb = 0
        self.target_vram_mb = 0 # Represents the value the slider/user wants
        self.macos_major_version = 0
        self.vram_key = None
        self.min_vram_mb = config.SLIDER_MIN_MB
        self.max_vram_mb = config.SLIDER_MIN_MB # Will be calculated
        self.is_operational = False
        self.preset_list_cache = []

        # --- UI Widget/Action References ---
        # ... (UI references remain the same) ...
        self.app_name_action = None
        self.ram_alloc_title_action = None
        self.ram_vram_bar_widget = None
        self.ram_vram_bar_widget_action = None
        self.total_ram_info_action = None
        self.reserved_ram_info_action = None
        self.allocated_vram_info_action = None
        self.default_action = None
        self.presets_menu = None
        self.preset_actions = {}
        self.custom_vram_title_action = None
        self.slider_widget = None
        self.slider_widget_action = None
        self.slider_value_action = None # The "Apply X GB" action
        self.refresh_action = None
        self.quit_action = None
        self.launch_at_login_checkbox = None
        self.launch_at_login_action = None

        # --- Application Setup ---
        self.app = QApplication.instance()
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)

        self.is_operational = self.perform_initial_checks()
        if not self.is_operational:
            print("App is not operational due to failed initial checks.")

        if self.total_ram_mb > 0:
             self.update_ram_values()
             self.target_vram_mb = self.current_vram_mb
             # --- Calculate slider range BEFORE creating menu actions ---
             self.calculate_slider_range()
             # ----------------------------------------------------------
             self.preset_list_cache = self.generate_presets_gb()
        else:
             print("[App Init] Critical: Could not determine total RAM. App state is limited.")
             self.current_vram_mb = 0
             self.target_vram_mb = 0
             self.min_vram_mb = config.SLIDER_MIN_MB
             self.max_vram_mb = config.SLIDER_MIN_MB

        # --- Tray Icon ---
        self.tray_icon = QSystemTrayIcon(QIcon(icon_path) if icon_path else QIcon(), self.app)
        self.tray_icon.setToolTip("Siliv VRAM Tool")
        self.tray_icon.activated.connect(self.handle_tray_activation)

        # --- Menu ---
        self.menu = QMenu()
        self.create_menu_actions() # Creates actions and connects signals

        if self.total_ram_mb > 0:
            self.tray_icon.show()
            print("[App] Tray icon created and shown.")
        else:
            print("[App] Tray icon not shown due to critical initialization failure.")

        self.update_menu_items()

        # --- Apply Saved VRAM on Startup ---
        if self.total_ram_mb > 0:
            self.apply_saved_vram_on_startup()
        # ---------------------------------

        # --- Refresh Timer ---
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_data_and_update_menu)
        self.refresh_timer.start(config.REFRESH_INTERVAL_MS)

    # --- Methods for setup, checks, calculations ---

    def perform_initial_checks(self):
        """Checks OS compatibility, retrieves RAM, and finds VRAM key."""
        print("Performing initial checks...")
        if platform.system() != "Darwin":
            self._show_error("Compatibility Error", "Siliv requires macOS.")
            return False

        self.macos_major_version = utils.get_macos_version()
        if self.macos_major_version == 0:
            self._show_error("Error", "Could not determine macOS version.")
        else:
            print(f"Detected macOS Version: {self.macos_major_version}")

        self.vram_key = utils.get_vram_sysctl_key()
        can_set_vram = self.vram_key is not None

        self.total_ram_mb = utils.get_total_ram_mb()
        if not self.total_ram_mb or self.total_ram_mb <= 0:
            self._show_error("Error", "Could not retrieve total system RAM.\nApplication cannot function correctly.")
            return False # This is critical

        print(f"Total System RAM: {self.total_ram_mb} MB")

        if not can_set_vram:
            self._show_warning("Unsupported OS or Permissions", f"macOS {self.macos_major_version} might not support VRAM control with this tool, or permissions are insufficient.\nFunctionality will be limited to displaying information.")
            print(f"Using VRAM sysctl key: '{self.vram_key}' (or None)")
            return False # Mark as not fully operational
        else:
             print(f"Using VRAM sysctl key: '{self.vram_key}'")
             print("Initial checks passed (VRAM control should be possible).")
             return True # Operational


    def calculate_slider_range(self):
        """Calculates the min/max allowable VRAM values for the slider."""
        if not self.total_ram_mb: return

        # Min VRAM from config
        self.min_vram_mb = config.SLIDER_MIN_MB

        # --- MODIFICATION: Max VRAM is now total system RAM ---
        self.max_vram_mb = self.total_ram_mb
        # ----------------------------------------------------

        # Ensure max is not less than min (handles very low RAM edge cases)
        if self.max_vram_mb < self.min_vram_mb:
            # If total RAM is somehow less than the configured min, use min as max
            print(f"Warning: Total RAM ({self.total_ram_mb}MB) is less than minimum VRAM ({self.min_vram_mb}MB). Adjusting max VRAM.")
            self.max_vram_mb = self.min_vram_mb

        print(f"VRAM Setting Range Calculated: Min={self.min_vram_mb}MB, Max={self.max_vram_mb}MB")

        # --- Update slider range if it already exists ---
        # This ensures that if this function is called later, the slider is updated
        if hasattr(self, 'slider_widget') and self.slider_widget:
             print("Updating existing slider widget range.")
             self.slider_widget.set_range(self.min_vram_mb, self.max_vram_mb)
        # ----------------------------------------------

    def generate_presets_gb(self):
        """
        Generates a list of sensible VRAM presets in GB tuples (GB, Label).
        Includes standard presets and 1GB increments near the maximum.
        """
        presets = []
        if not self.total_ram_mb or self.max_vram_mb <= self.min_vram_mb:
            print("[Presets] Cannot generate presets: Invalid RAM or VRAM range.")
            return []

        # Use calculated max allocatable VRAM based on reserve config
        max_preset_mb = self.max_vram_mb
        # Calculate the theoretical macOS default for comparison
        calculated_default_mb = utils.calculate_default_vram_mb(self.total_ram_mb)

        print(f"[Presets] Max allocatable MB: {max_preset_mb}, Calculated default MB: {calculated_default_mb}, Min allowed MB: {self.min_vram_mb}")

        # --- Standard Presets ---
        # Added 256 and 512 here
        potential_gbs = [4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 256, 512] # Base points
        labels = ["Basic", "Balanced", "More", "Gaming", "High", "Very High", "Extreme", "Insane"] # Labels for standard points (fallback used for higher values)
        label_idx = 0
        added_gbs = set() # Keep track of GB values added

        for gb in potential_gbs:
            mb = gb * 1024
            # Check if within valid range AND significantly different from default
            if self.min_vram_mb <= mb <= max_preset_mb and abs(mb - calculated_default_mb) > 1024:
                if gb not in added_gbs:
                    # Assign labels sequentially or use GB value as fallback
                    label = labels[label_idx] if label_idx < len(labels) else f"{gb} GB"
                    presets.append((gb, label))
                    added_gbs.add(gb)
                    # Only increment label_idx if we actually used a label from the list
                    if label_idx < len(labels):
                         label_idx += 1
        print(f"[Presets] After standard points: {presets}")

        # --- Near-Maximum 1GB Increment Presets ---
        max_alloc_gb = int(max_preset_mb / 1024) # The highest whole GB possible
        num_near_max_presets = 4 # How many 1GB steps to add below the max (including max)

        # Iterate downwards from the max possible GB
        for i in range(num_near_max_presets):
            gb = max_alloc_gb - i
            if gb <= 0: break # Stop if we go below 1GB

            mb = gb * 1024
            # Check conditions: within range, not too close to default, and not already added
            if gb not in added_gbs and self.min_vram_mb <= mb <= max_preset_mb and abs(mb - calculated_default_mb) > 1024:
                 print(f"[Presets] Adding near-max preset: {gb} GB")
                 presets.append((gb, f"{gb} GB")) # Use simple label for these
                 added_gbs.add(gb)

        # --- Final Sort ---
        presets.sort(key=lambda x: x[0]) # Sort all presets by GB value
        print(f"[Presets] Final generated list: {presets}")
        return presets
    # --- END PRESET MODIFICATION ---

    def create_menu_actions(self):
        """Creates and adds actions and widgets to the menu."""
        self.menu.clear()
        self.preset_actions.clear()

        # --- App Title ---
        self.app_name_action = QAction("Siliv VRAM Tool")
        font = self.app_name_action.font(); font.setBold(True); self.app_name_action.setFont(font)
        self.app_name_action.setEnabled(False)
        self.menu.addAction(self.app_name_action)
        self.menu.addSeparator()

        # --- RAM Allocation Info Section ---
        self.ram_alloc_title_action = QAction("RAM Allocation:")
        self.ram_alloc_title_action.setEnabled(False)
        self.menu.addAction(self.ram_alloc_title_action)

        self.ram_vram_bar_widget = widgets.RamVramBarWidget()
        self.ram_vram_bar_widget_action = QWidgetAction(self.menu)
        self.ram_vram_bar_widget_action.setDefaultWidget(self.ram_vram_bar_widget)
        self.menu.addAction(self.ram_vram_bar_widget_action)

        self.total_ram_info_action = QAction("Total System RAM: ...")
        self.total_ram_info_action.setEnabled(False)
        self.menu.addAction(self.total_ram_info_action)
        self.reserved_ram_info_action = QAction("Reserved System RAM: ...")
        self.reserved_ram_info_action.setEnabled(False)
        self.menu.addAction(self.reserved_ram_info_action)
        self.allocated_vram_info_action = QAction("Allocated VRAM: ...")
        self.allocated_vram_info_action.setEnabled(False)
        self.menu.addAction(self.allocated_vram_info_action)
        self.menu.addSeparator()

        # --- Control Actions ---
        self.default_action = QAction("Allocate Default VRAM")
        self.default_action.triggered.connect(self.set_default_vram)
        self.default_action.setEnabled(self.is_operational)
        self.menu.addAction(self.default_action)

        self.presets_menu = self.menu.addMenu("Presets")
        self.presets_menu.setEnabled(self.is_operational and bool(self.preset_list_cache))
        if not self.preset_list_cache:
            no_presets_action = QAction("No presets available")
            no_presets_action.setEnabled(False)
            self.presets_menu.addAction(no_presets_action)
        else:
            for gb, label_suffix in self.preset_list_cache:
                mb = gb * 1024
                action = QAction(f"Allocate {gb} GB VRAM ({label_suffix})")
                action.triggered.connect(lambda checked=False, m=mb: self.set_preset_vram(m))
                action.setEnabled(self.is_operational)
                self.presets_menu.addAction(action)
                self.preset_actions[mb] = action

        self.menu.addSeparator()

        # --- Custom Allocation Section ---
        self.custom_vram_title_action = QAction("Custom VRAM Allocation:")
        self.custom_vram_title_action.setEnabled(False)
        self.menu.addAction(self.custom_vram_title_action)

        # --- Initialize slider with the calculated range ---
        self.slider_widget = widgets.SliderWidget(min_val=self.min_vram_mb, max_val=self.max_vram_mb)
        self.slider_widget.setObjectName("SliderWidget")
        self.slider_widget.setEnabled(self.is_operational)
        # --------------------------------------------------

        self.slider_widget.valueChanged.connect(self.handle_slider_value_changed)
        self.slider_widget.sliderReleased.connect(self.handle_slider_snap_applied)

        self.slider_widget_action = QWidgetAction(self.menu)
        self.slider_widget_action.setDefaultWidget(self.slider_widget)
        self.menu.addAction(self.slider_widget_action)
 
        self.slider_value_action = QAction("Allocate ... GB VRAM")
        self.slider_value_action.setEnabled(False)
        self.slider_value_action.triggered.connect(self.apply_slider_value_from_action)
        self.menu.addAction(self.slider_value_action)

        # --- Launch at Login ---
        self.launch_at_login_checkbox = QCheckBox("Launch at Login")
        saved_launch_pref = self.settings.value(LAUNCH_AT_LOGIN_KEY, False, type=bool)
        self.launch_at_login_checkbox.setChecked(bool(saved_launch_pref))
        self.launch_at_login_checkbox.stateChanged.connect(self.handle_launch_at_login_toggled)
        self.launch_at_login_action = QWidgetAction(self.menu)
        self.launch_at_login_action.setDefaultWidget(self.launch_at_login_checkbox)
        self.menu.addAction(self.launch_at_login_action)

        self.menu.addSeparator()

        # --- Other Actions ---
        self.refresh_action = QAction("Refresh Info")
        self.refresh_action.triggered.connect(self._refresh_data_and_update_menu)
        self.refresh_action.setEnabled(True)
        self.menu.addAction(self.refresh_action)

        self.menu.addSeparator()
        self.quit_action = QAction("Quit Siliv")
        self.quit_action.triggered.connect(self.quit_app)
        self.menu.addAction(self.quit_action)

    def update_ram_values(self):
        """Fetches current VRAM using utils, recalculates reserved RAM. Returns True if VRAM changed."""
        if self.total_ram_mb <= 0: return False

        old_vram = self.current_vram_mb
        self.current_vram_mb = utils.get_current_vram_mb(self.total_ram_mb)

        if self.current_vram_mb > self.total_ram_mb:
            print(f"Warning: Reported current VRAM ({self.current_vram_mb}MB) exceeds total RAM ({self.total_ram_mb}MB). Clamping to total RAM.")
            self.current_vram_mb = self.total_ram_mb

        self.reserved_ram_mb = self.total_ram_mb - self.current_vram_mb
        if self.reserved_ram_mb < 0: self.reserved_ram_mb = 0

        vram_changed = (self.current_vram_mb != old_vram)
        if vram_changed:
            print(f"Current VRAM updated: {old_vram}MB -> {self.current_vram_mb}MB")

        return vram_changed

    def update_menu_items(self):
        """Updates the text and enabled state of all menu items based on current state."""
        if self.total_ram_mb <= 0:
            print("Cannot update menu items: Total RAM unknown.")
            if self.default_action: self.default_action.setEnabled(False)
            if self.presets_menu: self.presets_menu.setEnabled(False)
            if self.slider_widget: self.slider_widget.setEnabled(False)
            if self.slider_value_action: self.slider_value_action.setEnabled(False)
            return

        if self.ram_vram_bar_widget:
            self.ram_vram_bar_widget.update_values(self.total_ram_mb, self.current_vram_mb, self.target_vram_mb)

        total_ram_gb = self.total_ram_mb / 1024.0
        current_vram_gb = self.current_vram_mb / 1024.0
        current_reserved_ram_gb = (self.total_ram_mb - self.current_vram_mb) / 1024.0

        if self.total_ram_info_action: self.total_ram_info_action.setText(f"Total System RAM: {total_ram_gb:.1f} GB")
        if self.reserved_ram_info_action: self.reserved_ram_info_action.setText(f"Reserved System RAM: {current_reserved_ram_gb:.1f} GB")
        if self.allocated_vram_info_action: self.allocated_vram_info_action.setText(f"Allocated VRAM: {current_vram_gb:.1f} GB ({self.current_vram_mb} MB)")

        calculated_default_mb = utils.calculate_default_vram_mb(self.total_ram_mb)
        is_current_default = (self.current_vram_mb == calculated_default_mb)

        if self.default_action:
            self.default_action.setEnabled(self.is_operational and not is_current_default)
            self.default_action.setText(f"Allocate Default VRAM{' (Current)' if is_current_default else ''}")

        if self.presets_menu:
            self.presets_menu.setEnabled(self.is_operational and bool(self.preset_actions))
            for mb_key, action in self.preset_actions.items():
                is_current_preset = (self.current_vram_mb == mb_key)
                action.setEnabled(self.is_operational and not is_current_preset)
                original_text = action.text().split(" (Current)")[0]
                action.setText(f"{original_text}{' (Current)' if is_current_preset else ''}")

        if self.slider_widget:
             self.slider_widget.setEnabled(self.is_operational)
             if self.is_operational:
                 self.slider_widget.set_value(self.target_vram_mb)

        if self.slider_value_action:
            target_gb = self.target_vram_mb / 1024.0
            self.slider_value_action.setText(f"Allocate {target_gb:.1f} GB VRAM")
            can_apply_slider = (self.target_vram_mb != self.current_vram_mb)
            self.slider_value_action.setEnabled(self.is_operational and can_apply_slider)

    def _refresh_data_and_update_menu(self):
        """Refreshes RAM values and updates the menu display. Does NOT reset target."""
        print("[App] Refresh triggered...")
        vram_changed = self.update_ram_values()
        self.update_menu_items()
        if vram_changed:
             print("VRAM value changed since last check.")

    def handle_slider_value_changed(self, value_mb):
        """Updates ONLY the internal target VRAM state when slider moves (before release/snap)."""
        self.target_vram_mb = value_mb
        if self.slider_value_action:
            target_gb = self.target_vram_mb / 1024.0
            self.slider_value_action.setText(f"Allocate {target_gb:.1f} GB VRAM")
            can_apply_slider = (self.target_vram_mb != self.current_vram_mb)
            self.slider_value_action.setEnabled(self.is_operational and can_apply_slider)
        if self.ram_vram_bar_widget:
            self.ram_vram_bar_widget.update_values(self.total_ram_mb, self.current_vram_mb, self.target_vram_mb)


    def handle_slider_snap_applied(self):
        # ... (This method remains unchanged) ...
        print("[App] Slider snap applied (or release handled). Updating UI to final target.")
        final_snapped_value = self.slider_widget.get_value()

        if final_snapped_value != self.target_vram_mb:
             print(f"Aligning internal target ({self.target_vram_mb}) with final slider value ({final_snapped_value}) after snap.")
             self.target_vram_mb = final_snapped_value

        self.update_menu_items()


    def apply_slider_value_from_action(self):
        # ... (This method remains unchanged) ...
        target_mb_to_apply = self.target_vram_mb
        print(f"Applying slider target value via text action: {target_mb_to_apply} MB")
        if target_mb_to_apply != self.current_vram_mb:
            self._set_vram_and_update(target_mb_to_apply)
        else:
            print("Target value matches current VRAM, no change needed.")
            self._show_message("Info", "Selected VRAM matches current setting.")


    def _set_vram_and_update(self, value_mb):
        """Internal helper to attempt setting VRAM, including warning."""
        if not self.is_operational:
            self._show_error("Error", "Cannot set VRAM: Application is not operational (check macOS version or permissions).")
            return

        try:
            target_mb = int(value_mb)
        except (ValueError, TypeError):
             print(f"Error: Invalid value provided to _set_vram_and_update: {value_mb}")
             self._show_error("Error", f"Invalid VRAM value: {value_mb}")
             return

        clamped_mb = target_mb
        # Clamp the requested value (unless it's 0 for default) before sending to set_vram_mb
        if target_mb != 0:
             # Use the updated self.max_vram_mb which could be total RAM
             clamped_mb = max(self.min_vram_mb, min(target_mb, self.max_vram_mb))
             if clamped_mb != target_mb:
                 print(f"Requested VRAM {target_mb}MB clamped to range [{self.min_vram_mb}-{self.max_vram_mb}]: {clamped_mb}MB")
        else:
            print("Requesting reset to system default VRAM (passing 0 to sysctl).")
            calculated_default_mb = utils.calculate_default_vram_mb(self.total_ram_mb)
            self.target_vram_mb = calculated_default_mb
            self.update_menu_items()

        # --- ADD WARNING CHECK ---
        if clamped_mb != 0: # Don't warn if setting to default
            remaining_ram_mb = self.total_ram_mb - clamped_mb
            warning_threshold_mb = config.RESERVED_SYSTEM_RAM_MIN # Use config value (4096)

            if remaining_ram_mb < warning_threshold_mb:
                remaining_ram_gb = remaining_ram_mb / 1024.0
                warning_threshold_gb = warning_threshold_mb / 1024.0
                print(f"Warning condition met: Remaining RAM ({remaining_ram_gb:.1f} GB) < Threshold ({warning_threshold_gb:.1f} GB)")

                reply = QMessageBox.warning(None, 'Low System RAM Warning',
                             f"Setting VRAM to {clamped_mb} MB will leave only "
                             f"{remaining_ram_gb:.1f} GB of RAM for the System.\n\n"
                             f"Allocating less than {warning_threshold_gb:.1f} GB for the system "
                             f"may lead to instability or poor performance and a high swap usage "
                             f"when VRAM has filled up."
                             f"\n\nAre you sure you want to proceed?",
                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                             QMessageBox.StandardButton.Cancel) # Default to Cancel

                if reply == QMessageBox.StandardButton.Cancel:
                    print("User cancelled VRAM set due to low system RAM warning.")
                    # Reset target VRAM back to current to reflect cancellation
                    self.target_vram_mb = self.current_vram_mb
                    self.update_menu_items()
                    return # Abort the setting process
                else:
                    print("User confirmed VRAM set despite low system RAM warning.")
            else:
                 print(f"Remaining RAM check passed: {remaining_ram_mb / 1024.0:.1f} GB >= {warning_threshold_mb / 1024.0:.1f} GB")
        # --- END WARNING CHECK ---


        print(f"Calling utils.set_vram_mb with target: {clamped_mb}")
        success, message = utils.set_vram_mb(clamped_mb)

        if success:
            print(f"VRAM set command reported success via utils. Saving {clamped_mb} MB to settings.")
            self.settings.setValue(SAVED_VRAM_KEY, clamped_mb)
            self.settings.sync()
            QTimer.singleShot(1500, self._refresh_data_and_update_menu)
        else:
            print(f"Failed to set VRAM or action cancelled. Message from utils: {message}")
            self.target_vram_mb = self.current_vram_mb
            self.update_menu_items()


    # --- Tray Icon Interaction ---
    def handle_tray_activation(self, reason):
        # ... (This method remains unchanged) ...
        if reason == QSystemTrayIcon.ActivationReason.Trigger or reason == QSystemTrayIcon.ActivationReason.Context:
            print(f"[App] Tray icon activated (Reason: {reason}), showing menu.")
            vram_changed = self.update_ram_values()
            self.target_vram_mb = self.current_vram_mb
            self.update_menu_items()
            self.menu.popup(QCursor.pos())


    # --- Slot Methods for Actions ---
    def set_default_vram(self):
        # ... (This method remains unchanged) ...
        print(f"[App] User requested setting VRAM to System Default.")
        calculated_default_mb = utils.calculate_default_vram_mb(self.total_ram_mb)
        self.target_vram_mb = calculated_default_mb
        self.update_menu_items()
        self._set_vram_and_update(0) # Pass 0 to signify default

    def set_preset_vram(self, value_mb):
        # ... (This method remains unchanged) ...
        print(f"[App] User requested setting VRAM to Preset: {value_mb} MB")
        self.target_vram_mb = value_mb
        self.update_menu_items()
        self._set_vram_and_update(value_mb)

    # --- Launch at Login handler ---
    def handle_launch_at_login_toggled(self, state):
        """Enables/Disables autostart when checkbox is toggled."""
        enabled = (state == Qt.CheckState.Checked)
        success, message = utils.set_launch_at_login(enabled)
        if success:
            self.settings.setValue(LAUNCH_AT_LOGIN_KEY, enabled)
            self.settings.sync()
        else:
            QMessageBox.warning(None, "Launch at Login", message)
            # Revert state silently
            self.launch_at_login_checkbox.blockSignals(True)
            self.launch_at_login_checkbox.setChecked(not enabled)
            self.launch_at_login_checkbox.blockSignals(False)

    # --- Startup Application Method ---
    def apply_saved_vram_on_startup(self):
        # ... (This method remains unchanged from the previous version, but uses updated clamping) ...
        if not self.is_operational:
            print("[Startup Apply] Not operational, skipping saved VRAM check.")
            return

        saved_vram_mb_variant = self.settings.value(SAVED_VRAM_KEY, defaultValue=None)
        saved_vram_mb = None
        if saved_vram_mb_variant is not None:
            try:
                saved_vram_mb = int(saved_vram_mb_variant)
            except (ValueError, TypeError):
                print(f"[Startup Apply] Warning: Could not parse saved VRAM value '{saved_vram_mb_variant}'. Ignoring.")
                saved_vram_mb = None

        if saved_vram_mb is not None:
            print(f"[Startup Apply] Found saved VRAM setting: {saved_vram_mb} MB")
            print(f"[Startup Apply] Current VRAM setting is: {self.current_vram_mb} MB")

            if saved_vram_mb != self.current_vram_mb:
                print(f"[Startup Apply] Saved VRAM ({saved_vram_mb} MB) differs from current ({self.current_vram_mb} MB). Applying saved value.")

                # Use the current valid range [min_vram_mb, max_vram_mb] for clamping
                clamped_saved_vram = max(self.min_vram_mb, min(saved_vram_mb, self.max_vram_mb))
                if clamped_saved_vram != saved_vram_mb:
                     print(f"[Startup Apply] Warning: Clamping saved VRAM {saved_vram_mb}MB to current valid range [{self.min_vram_mb}-{self.max_vram_mb}]: {clamped_saved_vram}MB")

                # Apply directly on startup (will prompt for password if needed)
                # The warning check is now inside _set_vram_and_update, so it will trigger here too
                self.target_vram_mb = clamped_saved_vram
                self.update_menu_items()
                self._set_vram_and_update(clamped_saved_vram) # This call now includes the warning logic

            else:
                print("[Startup Apply] Saved VRAM matches current setting. No action needed.")
        else:
            print("[Startup Apply] No saved VRAM setting found.")


    # --- Utility Methods for User Feedback ---
    def _show_message(self, title, message):
        """Shows an informational message via the system tray."""
        if self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            print(f"INFO [{title}]: {message}")

    def _show_warning(self, title, message):
        """Shows a warning message dialog."""
        QMessageBox.warning(None, title, message)

    def _show_error(self, title, message):
        """Shows a critical error message dialog."""
        QMessageBox.critical(None, title, message)

    # --- Application Exit ---
    def quit_app(self):
        """Stops timers, hides tray icon, and quits the application."""
        print("[App] Quitting application...")
        self.refresh_timer.stop()
        self.tray_icon.hide()
        self.app.quit()
