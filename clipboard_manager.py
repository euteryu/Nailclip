#!/usr/bin/env python3

import gi
import subprocess
import os
import json
import sys
import time
import fcntl

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) # Directory of the script
HISTORY_FILE = os.path.expanduser("~/.local/src/Nailclip/.clipboard_history.json")
LOCK_FILE = os.path.expanduser("~/.local/src/Nailclip/.clipboard_manager.lock")
# Use an icon file placed in the same directory as the script
ICON_FILE = os.path.join(SCRIPT_DIR, "assets/nailclip_128x128.png")
MAX_HISTORY_ITEMS = 20

# --- Global State ---
CLIPBOARD = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
PRIMARY = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
history = {"pins": [], "history": []}
last_clipboard_content = None
win = None
lock_file_handle = None

# --- CSS Data (Unchanged) ---
CSS_DATA = b"""
#button-copy {
    background-image: none; background-color: #FFB6C1;
    border: 1px solid #A0A0A0; color: #000000;
}
#button-copy:hover { background-color: #FFA0B1; }
#button-pin {
    background-image: none; background-color: #FFFFE0;
    border: 1px solid #A0A0A0; color: #000000;
}
#button-pin:hover { background-color: #FFFFAA; }
#button-clear {
    background-image: none; background-color: #ADD8E6;
    border: 1px solid #A0A0A0; color: #000000;
}
#button-clear:hover { background-color: #9ACEEB; }
"""

# --- Lock File Management (Unchanged) ---
def acquire_lock():
    global lock_file_handle
    if os.path.exists(LOCK_FILE): # Check for stale lock
        try:
            pid_str = "";
            with open(LOCK_FILE, 'r') as f: pid_str = f.read().strip()
            if pid_str: os.kill(int(pid_str), 0)
        except (ValueError, ProcessLookupError):
            print(f"Stale lock (PID {pid_str}). Removing.")
            try: os.remove(LOCK_FILE)
            except OSError as e: print(f"Warn: rm stale lock failed: {e}")
        except Exception: pass
    try: # Acquire lock
        lock_file_handle = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file_handle.seek(0); lock_file_handle.truncate()
        lock_file_handle.write(str(os.getpid())); lock_file_handle.flush()
        print(f"PID {os.getpid()} acquired lock.")
        return True
    except (IOError, OSError):
        print(f"Lock busy/error. Another instance? Exiting.")
        if lock_file_handle: lock_file_handle.close(); lock_file_handle = None
        return False
    except Exception as e:
        print(f"Unexpected lock error: {e}")
        if lock_file_handle: lock_file_handle.close(); lock_file_handle = None
        return False

def release_lock():
    global lock_file_handle
    if lock_file_handle:
        print(f"PID {os.getpid()} releasing lock...")
        try:
            fcntl.flock(lock_file_handle, fcntl.LOCK_UN)
            lock_file_handle.close(); lock_file_handle = None
            print("Lock released.")
            try: os.remove(LOCK_FILE); print("Lock file removed.")
            except OSError as e: print(f"Warn: rm lock file failed: {e}")
        except Exception as e: print(f"Error releasing lock: {e}")
    else: print("Lock release called, but no handle held.")

# --- Helper Functions (Unchanged) ---
def load_history():
    global history, last_clipboard_content
    history = {"pins": [], "history": []}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f: loaded_data = json.load(f)
            if isinstance(loaded_data, dict):
                pins=loaded_data.get("pins",[])
                hist=loaded_data.get("history",[])
                history["pins"] = [
                    str(i) for i in pins if isinstance(i, str) and i.strip()
                ][:MAX_HISTORY_ITEMS*2]
                history["history"] = [
                    str(i) for i in hist if isinstance(i, str) and i.strip()
                ][:MAX_HISTORY_ITEMS]
        except Exception as e: print(f"Error loading history: {e}.")
    try: # Get initial state
        current_text = CLIPBOARD.wait_for_text()
        last_clipboard_content = current_text if current_text else None
        lc_len = len(last_clipboard_content) if last_clipboard_content else 0
        print(f"Initial clip content (len={lc_len}) read.")
    except Exception as e:
        print(f"Warn: Initial clipboard read failed: {e}")
        last_clipboard_content = None

def save_history():
    history["history"] = [
        i for i in history["history"] if isinstance(i, str) and i.strip()
    ][:MAX_HISTORY_ITEMS]
    history["pins"] = [
        i for i in history["pins"] if isinstance(i, str) and i.strip()
    ]
    try:
        with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=2)
    except Exception as e: print(f"Error saving history: {e}")

# --- Core Logic Functions (Unchanged) ---
def add_clipboard_text(text):
    if not isinstance(text, str) or not text.strip(): return
    if text in history["pins"]: return
    if text in history["history"]: history["history"].remove(text)
    history["history"].insert(0, text)
    while len(history["history"]) > MAX_HISTORY_ITEMS: history["history"].pop()
    save_history()
    if win and not win.is_destroyed(): GLib.idle_add(win.refresh_items)

def perform_quit_sequence():
    print("Initiating clean quit sequence...")
    release_lock()
    print("Quitting Gtk main loop..."); Gtk.main_quit(); print("Quit sent.")

def copy_text_to_clipboard(text_to_copy):
    global last_clipboard_content
    if not isinstance(text_to_copy, str): return
    try:
        print(f"Copying to clipboard: {text_to_copy[:50]}...")
        CLIPBOARD.set_text(text_to_copy, -1); CLIPBOARD.store()
        PRIMARY.set_text(text_to_copy, -1)
        print("Clipboard text set by copy button.")
        last_clipboard_content = text_to_copy # Update tracker
    except Exception as e: print(f"Error setting clipboard text: {e}")

# --- GUI Class ---
class ClipboardWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Nailclip")
        self.set_border_width(10)
        self.set_default_size(500, 400)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_transient_for(None); self.set_skip_taskbar_hint(True)
        self.set_decorated(True); self.set_position(Gtk.WindowPosition.CENTER)

        # --- Set Window Icon --- <<< NEW SECTION >>>
        if os.path.exists(ICON_FILE):
            try:
                self.set_icon_from_file(ICON_FILE)
                print(f"Window icon set from: {ICON_FILE}")
            except GLib.Error as e:
                print(f"Error setting window icon from {ICON_FILE}: {e}")
            except Exception as e:
                print(f"Unexpected error setting icon: {e}")
        else:
            print(f"Warn: Icon file not found at {ICON_FILE}. Using default.")
            # Optional: Set a fallback icon name from the theme
            # self.set_icon_name("accessories-clipboard")

        # --- Apply CSS Styling Safely ---
        # print("Attempting to apply CSS styles to screen...") # Less verbose
        css_provider = Gtk.CssProvider()
        try:
            css_provider.load_from_data(CSS_DATA)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            # print("CSS styles applied successfully to screen.") # Less verbose
        except GLib.Error as e:
             print(f"ERROR loading/applying CSS: {e}. Styling disabled.")
        except Exception as e:
            print(f"UNEXPECTED ERROR applying CSS: {e}. Styling disabled.")

        # Widgets
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.listbox)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.pack_start(scroller, True, True, 0)
        instructions = Gtk.Label(label="Click Copy button. Esc to close.")
        vbox.pack_start(instructions, False, False, 5)
        self.add(vbox)

        # Signal Connections
        self.connect("delete-event", self.on_close_request)
        self.connect("key-press-event", self.on_key_press)
        self.connect("map-event", self.on_map_event)
        self.connect("destroy", Gtk.main_quit)

        self.refresh_items()

    # --- Methods (on_map_event, on_close_request, etc. - unchanged) ---
    def on_map_event(self, widget, event):
        # print("Window mapped, attempting focus grab.") # Less verbose
        self.present()

    def on_close_request(self, widget, event):
        print("'X' button clicked. Quitting.")
        perform_quit_sequence(); return True

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            print("Escape key pressed. Quitting.")
            perform_quit_sequence(); return True
        return False

    def is_destroyed(self):
        try: return not self.get_window()
        except (AttributeError, gi.repository.Gtk.DestroyedError): return True

    def on_copy_button_clicked(self, button_widget, text_to_copy):
        copy_text_to_clipboard(text_to_copy)

    def refresh_items(self):
        if self.is_destroyed(): return
        pins = history.get("pins", [])
        hists = history.get("history", [])
        # print(f"Refreshing list (Pins: {len(pins)}, Hist: {len(hists)})")

        for child in self.listbox.get_children(): self.listbox.remove(child)

        # Helper function to create a row
        def add_row_widget(text, is_pinned):
            row = Gtk.ListBoxRow(); row.set_activatable(False)
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.add(hbox)
            # Label
            display_text = text.replace('\n', ' ')[:80]
            if len(text) > 80: display_text += "..."
            label = Gtk.Label(label=display_text, xalign=0)
            label.set_tooltip_text(text); label.set_selectable(True)
            label.set_can_focus(False)
            hbox.pack_start(label, True, True, 0)
            # Copy Button
            button_copy = Gtk.Button.new_with_mnemonic("_Copy")
            button_copy.set_name("button-copy") # CSS ID
            button_copy.connect("clicked", self.on_copy_button_clicked, text)
            button_copy.set_can_focus(True)
            hbox.pack_start(button_copy, False, False, 0)
            # Pin/Unpin Button
            if is_pinned: pin_label, pin_action = "_Unpin", unpin
            else: pin_label, pin_action = "_Pin", pin
            button_pin = Gtk.Button.new_with_mnemonic(pin_label)
            button_pin.set_name("button-pin") # CSS ID
            button_pin.connect("clicked", self.on_action_button_clicked,
                               pin_action, text)
            button_pin.set_can_focus(True)
            hbox.pack_start(button_pin, False, False, 0)
            # Clear Button
            button_clear = Gtk.Button.new_with_mnemonic("_Clear")
            button_clear.set_name("button-clear") # CSS ID
            button_clear.connect("clicked", self.on_action_button_clicked,
                                clear_entry, text, is_pinned)
            button_clear.set_can_focus(True)
            hbox.pack_start(button_clear, False, False, 0)
            self.listbox.add(row)
        # End helper ---

        # Populate Listbox
        for item in pins: add_row_widget(item, is_pinned=True)
        if pins and hists: # Separator
            sep_row=Gtk.ListBoxRow(); sep=Gtk.Separator(); sep_row.add(sep)
            sep_row.set_activatable(False); sep_row.set_selectable(False)
            self.listbox.add(sep_row)
        for item in hists: add_row_widget(item, is_pinned=False)
        if not pins and not hists: # Placeholder
             ph_row = Gtk.ListBoxRow(); ph_lbl = Gtk.Label("History is empty.")
             ph_lbl.set_halign(Gtk.Align.CENTER); ph_row.add(ph_lbl)
             ph_row.set_activatable(False); ph_row.set_selectable(False)
             self.listbox.add(ph_row)
        self.show_all()
        # print("Listbox refresh complete.")

    def on_action_button_clicked(self, widget, action_func, *args):
        action_func(*args) # Call pin/unpin/clear

# --- Action Functions (Unchanged) ---
def pin(text):
    if not isinstance(text, str) or not text.strip() or text in history["pins"]: return
    if text in history["history"]: history["history"].remove(text)
    history["pins"].insert(0, text)
    print(f"Pinned: {text[:50]}..."); save_history()
    if win and not win.is_destroyed(): GLib.idle_add(win.refresh_items)
def unpin(text):
    if not isinstance(text, str) or not text.strip() or text not in history["pins"]: return
    history["pins"].remove(text)
    if text not in history["history"]:
        history["history"].insert(0, text)
        while len(history["history"]) > MAX_HISTORY_ITEMS: history["history"].pop()
    print(f"Unpinned: {text[:50]}..."); save_history()
    if win and not win.is_destroyed(): GLib.idle_add(win.refresh_items)
def clear_entry(text, is_pinned):
    global last_clipboard_content
    if not isinstance(text, str) or not text.strip(): return
    cleared = False
    if is_pinned and text in history["pins"]: history["pins"].remove(text); cleared = True
    elif not is_pinned and text in history["history"]: history["history"].remove(text); cleared = True
    if cleared:
        print(f"Cleared: {text[:50]}...")
        if text == last_clipboard_content:
            print("Cleared item matched tracker."); last_clipboard_content = None
        save_history()
        if win and not win.is_destroyed(): GLib.idle_add(win.refresh_items)

# --- Clipboard Monitoring (EVENT-DRIVEN - Unchanged) ---
def on_text_received(clipboard_obj, text, user_data):
    global last_clipboard_content
    if not win or win.is_destroyed(): return
    current_content = text; local_last_content = last_clipboard_content
    is_valid = isinstance(current_content, str) and current_content.strip()
    is_different = current_content != local_last_content
    if is_valid and is_different:
        # print(f"Clipboard changed (owner signal). New content detected.")
        if current_content in history["pins"]:
             last_clipboard_content = current_content # Update tracker only
        else:
            add_clipboard_text(current_content) # Add to history
            last_clipboard_content = current_content # Update tracker AFTER add
    elif not is_valid and local_last_content is not None:
        # print("Clipboard likely cleared.")
        last_clipboard_content = None # Reset tracker

def on_clipboard_owner_change(clipboard, event):
    # print(f"Clipboard owner changed (Reason: {event.reason}). Requesting text...")
    clipboard.request_text(on_text_received, None)

# --- Main Execution Block ---
if __name__ == "__main__":
    if not acquire_lock(): sys.exit(1)
    main_loop_running = False
    try:
        session_type = os.environ.get('XDG_SESSION_TYPE','unknown').lower()
        print(f"Session Type: {session_type}")
        load_history()
        win = ClipboardWindow() # Create GUI

        # Setup Clipboard Monitoring
        # print("Connecting to clipboard owner-change signal...") # Less verbose
        CLIPBOARD.connect("owner-change", on_clipboard_owner_change)
        # print("Clipboard signal connected.") # Less verbose
        # print("Requesting initial clipboard text asynchronously...") # Less verbose
        CLIPBOARD.request_text(on_text_received, None) # Populate initial

        # Run GTK
        win.show_all(); win.present()
        main_loop_running = True
        print(f"Manager started (PID {os.getpid()}). Listening for events.")
        Gtk.main() # Blocks until quit

    except KeyboardInterrupt: # Handle Ctrl+C
        print("\nKeyboardInterrupt received.")
        if main_loop_running and win and not win.is_destroyed():
            perform_quit_sequence()
    except Exception as e: # Catch all other errors
        print("\n--- UNHANDLED EXCEPTION IN MAIN ---")
        import traceback; traceback.print_exc(); print("---")
        if main_loop_running and Gtk.main_level() > 0:
            GLib.idle_add(perform_quit_sequence); time.sleep(0.5)
        sys.exit(1) # Exit with error
    finally: # Ensures lock release on ANY exit path
        print("Main block 'finally' reached. Releasing lock...")
        release_lock()
    print(f"Nailclip clipboard manager (PID: {os.getpid()}) exiting cleanly.")