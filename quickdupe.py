import keyboard
import subprocess
import ctypes
import sys
import threading
import json
import os
import time
import hashlib
import random
import string
import tkinter as tk
from tkinter import ttk, filedialog
import logging

# Setup logging to file
LOG_FILE = os.path.join(os.environ.get('APPDATA', '.'), "QuickDupe", "debug.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("QuickDupe")
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button as MouseButton, Controller as MouseController

# vgamepad loaded lazily to avoid crash if ViGEmBus not installed
vg = None

# pynput controllers
pynput_keyboard = KeyboardController()
pynput_mouse = MouseController()

# Virtual Xbox controller - initialize once at startup
_gamepad = None
_vigem_warned = False

def install_vigem():
    """Run the bundled ViGEmBus installer"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    installer_path = os.path.join(base_path, "ViGEmBus_1.22.0_x64_x86_arm64.exe")

    if os.path.exists(installer_path):
        print("[INSTALL] Launching ViGEmBus installer...")
        # Launch installer normally so user can see/interact with it
        subprocess.Popen([installer_path])
        return True
    else:
        print(f"[ERROR] Installer not found at: {installer_path}")
        return False

def init_gamepad():
    """Initialize gamepad once at startup, auto-install driver if needed"""
    global _gamepad, _vigem_warned, vg

    # Try to import and create gamepad
    try:
        import vgamepad as vgamepad_module
        vg = vgamepad_module
        _gamepad = vg.VX360Gamepad()
        _gamepad.reset()  # Clear any phantom button state
        _gamepad.update()
        print("[GAMEPAD] Virtual Xbox controller initialized")
        return True
    except Exception as e:
        # Driver not installed or not working
        print(f"[GAMEPAD] ViGEmBus error: {e}")
        print("[GAMEPAD] Attempting auto-install...")
        if install_vigem():
            print("[GAMEPAD] ViGEmBus installed! Restart app to use keydoor macro.")
        else:
            print("[WARNING] Install ViGEmBus manually: https://github.com/nefarius/ViGEmBus/releases")
        _vigem_warned = True
        return False

def get_gamepad():
    """Return the pre-initialized gamepad"""
    return _gamepad

# Packet drop via WinDivert
import pydivert

_handle = None
_on = False

def start_packet_drop(outbound=True, inbound=True):
    """DROP PACKETS NOW"""
    global _handle, _on
    if _on:
        return

    # Match Clumsy's exact filter syntax
    if outbound and inbound:
        filt = "outbound or inbound"  # Clumsy's exact filter
    elif outbound:
        filt = "outbound"
    else:
        filt = "inbound"

    try:
        _handle = pydivert.WinDivert(filt)
        _handle.open()
        _on = True
        threading.Thread(target=_drop_loop, daemon=True).start()
        time.sleep(0.015)  # Match Clumsy's keypress toggle delay
    except:
        _on = False
        _handle = None

def _drop_loop():
    global _on
    while _on:
        try:
            if _handle:
                _handle.recv()  # recv but don't send = drop
            else:
                break
        except:
            break
    _on = False

def stop_packet_drop():
    """STOP DROPPING NOW"""
    global _handle, _on
    if not _on:
        return
    # Close handle FIRST to unblock recv(), then set flag
    h = _handle
    _handle = None
    _on = False
    if h:
        try:
            h.close()
        except:
            pass
    time.sleep(0.05)  # Give thread time to exit

def is_dropping():
    return _on

# Tamper packet functionality
_tamper_handle = None
_tamper_on = False
_tamper_patterns = [0x64, 0x13, 0x88, 0x40, 0x1F, 0xA0, 0xAA, 0x55]

def start_packet_tamper(outbound=True, inbound=True):
    """Start tampering packets - corrupt data but still send"""
    global _tamper_handle, _tamper_on
    if _tamper_on:
        return

    if outbound and inbound:
        filt = "outbound or inbound"
    elif outbound:
        filt = "outbound"
    else:
        filt = "inbound"

    try:
        _tamper_handle = pydivert.WinDivert(filt)
        _tamper_handle.open()
        _tamper_on = True
        threading.Thread(target=_tamper_loop, daemon=True).start()
        print(f"[TAMPER] Started tampering packets ({filt})")
    except Exception as e:
        print(f"[TAMPER] Failed to start: {e}")
        _tamper_on = False
        _tamper_handle = None

def _tamper_loop():
    global _tamper_on
    while _tamper_on and _tamper_handle:
        try:
            packet = _tamper_handle.recv()
            if packet and packet.payload:
                # Tamper the payload data
                payload = bytearray(packet.payload)
                for i in range(len(payload)):
                    payload[i] ^= _tamper_patterns[i % 8]
                packet.payload = bytes(payload)
                # pydivert auto-recalculates checksums
            _tamper_handle.send(packet)
        except:
            break

def stop_packet_tamper():
    """Stop tampering packets"""
    global _tamper_handle, _tamper_on
    if not _tamper_on:
        return
    _tamper_on = False
    if _tamper_handle:
        try:
            _tamper_handle.close()
        except:
            pass
        _tamper_handle = None
    print("[TAMPER] Stopped")

def is_tampering():
    return _tamper_on

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

CONFIG_FILE = os.path.join(os.environ.get('APPDATA', '.'), "QuickDupe", "config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)


class QuickDupeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("QD 1.4.0")
        self.root.geometry("442x800")
        self.root.resizable(False, True)  # Allow vertical resize
        self.root.overrideredirect(True)  # Remove Windows title bar

        # Force show in taskbar despite overrideredirect
        self.root.after(10, self._fix_taskbar)

        # Dark mode colors (dark greys)
        self.colors = {
            'bg': '#1e1e1e',
            'bg_light': '#2d2d2d',
            'accent': '#3c3c3c',
            'text': '#e0e0e0',
            'text_dim': '#808080',
            'highlight': '#e94560',
            'success': '#00d26a',
            'warning': '#ff9f1c'
        }

        # Apply dark theme
        self.root.configure(bg=self.colors['bg'])
        self.setup_dark_theme()

        # Set AppUserModelID for Windows taskbar icon
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('QuickDupe.QuickDupe.1')
        except:
            pass

        # Set window icon
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            png_path = os.path.join(base_path, "icon.png")
            ico_path = os.path.join(base_path, "icon.ico")
            if os.path.exists(png_path):
                self.icon_image = tk.PhotoImage(file=png_path)
                self.root.wm_iconphoto(True, self.icon_image)
            elif os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
        except:
            pass

        self.config = load_config()

        # Restore window position if saved and reasonable
        saved_x = self.config.get("window_x")
        saved_y = self.config.get("window_y")
        if saved_x is not None and saved_y is not None:
            # Check if position is on screen (reasonable)
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            if 0 <= saved_x < screen_w - 100 and 0 <= saved_y < screen_h - 100:
                self.root.geometry(f"+{saved_x}+{saved_y}")

        # State
        self.dc_hotkey_registered = None
        self.throwable_hotkey_registered = None
        self.triggernade_hotkey_registered = None
        self.disconnected = False
        self.throwable_running = False
        self.throwable_stop = False
        self.keydoor_running = False
        self.keydoor_stop = False
        self.triggernade_running = False
        self.triggernade_stop = False
        self.triggernade_m1_count = 13  # ~13 M1s before reconnect
        self.triggernade_dc_delay = 0.050  # Delay before disconnect (seconds)
        self.triggernade_run_count = 0  # Track runs for randomizing delay
        self.mine_running = False
        self.mine_stop = False
        self.mine_hotkey_registered = None
        self.espam_running = False
        self.espam_stop = False
        self.espam_hotkey_registered = None
        self.escape_hotkey_registered = None
        # Ammo state
        self.untitled1_running = False
        self.untitled1_stop = False
        self.untitled1_hotkey_registered = None
        self.recording_untitled1 = False
        # Quick disconnect state
        self.test_disconnected = False
        self.tampering = False
        self.dc_both_hotkey_registered = None
        self.dc_outbound_hotkey_registered = None
        self.dc_inbound_hotkey_registered = None
        self.tamper_hotkey_registered = None
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_mine = False
        self.recording_espam = False
        self.recording_drag = False
        self.drag_mouse_listener = None
        self.listening = True  # Always listening

        # Overlay
        self.overlay_window = None
        self.overlay_hide_id = None

        # Window handle for minimize (set in _fix_taskbar)
        self.hwnd = None

        # Tray icon
        self.tray_icon = None

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _add_tooltip(self, widget, text):
        """Add hover tooltip to a widget"""
        def show_tooltip(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_attributes('-topmost', True)
            tooltip.configure(bg='#333333')
            label = tk.Label(tooltip, text=text, justify='left', bg='#333333', fg='#e0e0e0',
                           relief='solid', borderwidth=1, padx=8, pady=6, font=('Segoe UI', 9))
            label.pack()
            tooltip.update_idletasks()

            # Smart positioning - flip to left if near right edge
            tip_width = tooltip.winfo_width()
            screen_width = tooltip.winfo_screenwidth()
            x = event.x_root + 20
            if x + tip_width > screen_width:
                x = event.x_root - tip_width - 10
            tooltip.wm_geometry(f"+{x}+{event.y_root + 20}")
            widget._tooltip = tooltip

        def hide_tooltip(event):
            if hasattr(widget, '_tooltip') and widget._tooltip:
                widget._tooltip.destroy()
                widget._tooltip = None

        widget.bind('<Enter>', show_tooltip)
        widget.bind('<Leave>', hide_tooltip)

    def vary(self, ms):
        """Apply random variance to a single timing value (in ms). Returns ms."""
        variance_pct = self.timing_variance_var.get()
        if variance_pct == 0:
            return ms
        max_delta = ms * variance_pct / 100.0
        delta = random.uniform(-max_delta, max_delta)
        return max(1, ms + delta)  # Never go below 1ms

    def vsleep(self, ms):
        """Sleep for ms with variance applied. Takes ms, handles conversion to seconds."""
        time.sleep(self.vary(ms) / 1000.0)

    def vary_balanced(self, ms, count):
        """Generate 'count' delays that each vary but sum to exactly ms*count.
        This makes loops look human while keeping total timing identical."""
        variance_pct = self.timing_variance_var.get()
        if variance_pct == 0 or count <= 1:
            return [ms] * count

        # Generate random variations
        max_delta = ms * variance_pct / 100.0
        deltas = [random.uniform(-max_delta, max_delta) for _ in range(count)]

        # Adjust so they sum to zero (balanced)
        avg_delta = sum(deltas) / count
        deltas = [d - avg_delta for d in deltas]

        # Apply to base timing, ensure minimum 1ms
        return [max(1, ms + d) for d in deltas]

    def _show_vigembus_help(self):
        """Show popup with clickable links for ViGEmBus help"""
        import webbrowser

        popup = tk.Toplevel(self.root)
        popup.title("ViGEmBus Setup")
        popup.configure(bg='#1e1e1e')
        popup.geometry("450x380")
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()

        # Center on parent
        popup.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (225)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (140)
        popup.geometry(f"+{x}+{y}")

        tk.Label(popup, text="ViGEmBus is preferred for consistency.",
                 bg='#1e1e1e', fg='#e0e0e0', font=('Segoe UI', 10, 'bold')).pack(pady=(15, 10))

        tk.Label(popup, text="Step 1: Install ViGEmBus driver",
                 bg='#1e1e1e', fg='#e0e0e0', font=('Segoe UI', 9)).pack(pady=(5, 2))
        link1 = tk.Label(popup, text="https://github.com/nefarius/ViGEmBus/releases",
                        bg='#1e1e1e', fg='#4da6ff', cursor='hand2', font=('Segoe UI', 9, 'underline'))
        link1.pack()
        link1.bind('<Button-1>', lambda e: webbrowser.open("https://github.com/nefarius/ViGEmBus/releases"))

        tk.Label(popup, text="\nStep 2: If still not working, also install:",
                 bg='#1e1e1e', fg='#e0e0e0', font=('Segoe UI', 9)).pack(pady=(5, 2))
        link2 = tk.Label(popup, text="Xbox 360 Accessories Software",
                        bg='#1e1e1e', fg='#4da6ff', cursor='hand2', font=('Segoe UI', 9, 'underline'))
        link2.pack()
        link2.bind('<Button-1>', lambda e: webbrowser.open("https://community.pcgamingwiki.com/files/file/2630-xbox-360-accessories-software-v12/"))

        tk.Label(popup, text="\nStep 3: If STILL not working:",
                 bg='#1e1e1e', fg='#e0e0e0', font=('Segoe UI', 9)).pack(pady=(5, 2))
        tk.Label(popup, text="Check the drag & drop box and record\ndrag paths for every macro you use.",
                 bg='#1e1e1e', fg='#aaaaaa', font=('Segoe UI', 9)).pack()

        ttk.Button(popup, text="Close", command=popup.destroy).pack(pady=15)

    def _fix_taskbar(self):
        """Make window show in taskbar despite overrideredirect"""
        # Constants
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        SWP_FRAMECHANGED = 0x0020
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        HWND_NOTOPMOST = -2

        # Ensure window is fully created
        self.root.update()

        # Try multiple methods to get the window handle
        try:
            # Method 1: wm_frame() returns hex string like "0x12345"
            frame = self.root.wm_frame()
            if frame:
                hwnd = int(frame, 16)
            else:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        except:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

        if not hwnd:
            hwnd = self.root.winfo_id()

        self.hwnd = hwnd  # Save for minimize
        print(f"[TASKBAR] Window handle: {hwnd} (0x{hwnd:x})")

        # Get and modify extended style
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        print(f"[TASKBAR] Current style: 0x{style:x}")

        # Remove TOOLWINDOW flag, add APPWINDOW flag
        new_style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        print(f"[TASKBAR] New style: 0x{new_style:x}")

        result = ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        print(f"[TASKBAR] SetWindowLongW result: {result}")

        # Force Windows to update the window frame
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED
        )

        # Hide and show to force taskbar refresh
        self.root.withdraw()
        self.root.after(100, self._show_window)

    def _show_window(self):
        """Show window after taskbar fix"""
        self.root.deiconify()
        self.root.update()

    def minimize_window(self):
        """Minimize window using Windows API (works with overrideredirect)"""
        if self.hwnd:
            SW_MINIMIZE = 6
            ctypes.windll.user32.ShowWindow(self.hwnd, SW_MINIMIZE)
        else:
            # Fallback - just hide it
            self.root.withdraw()

    def minimize_to_tray(self):
        """Minimize to system tray"""
        # Don't create multiple tray icons
        if self.tray_icon:
            return
        self.root.withdraw()
        self._create_tray_icon()

    def _create_tray_icon(self):
        """Create system tray icon"""
        try:
            import pystray
            from PIL import Image

            # Load icon
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))

            icon_path = os.path.join(base_path, "icon.png")
            if os.path.exists(icon_path):
                image = Image.open(icon_path)
            else:
                # Create a simple icon if file not found
                image = Image.new('RGB', (64, 64), color='#e94560')

            menu = pystray.Menu(
                pystray.MenuItem("Show", self._restore_from_tray, default=True),
                pystray.MenuItem("Exit", self._exit_from_tray)
            )

            self.tray_icon = pystray.Icon("QD 1.4.0", image, "QD 1.4.0", menu)
            # Run in thread so it doesn't block
            import threading
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except ImportError:
            # pystray not available, just minimize normally
            print("[TRAY] pystray not installed, using normal minimize")
            self.minimize_window()

    def _restore_from_tray(self, icon=None, item=None):
        """Restore window from tray"""
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.after(0, self._do_restore)

    def _do_restore(self):
        """Actually restore the window (must be called from main thread)"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _exit_from_tray(self, icon=None, item=None):
        """Exit from tray"""
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.after(0, self.on_close)

    def setup_dark_theme(self):
        """Configure ttk styles for dark mode"""
        style = ttk.Style()
        style.theme_use('clam')

        # Configure colors
        style.configure('.', background=self.colors['bg'], foreground=self.colors['text'])
        style.configure('TFrame', background=self.colors['bg'])
        style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['text'])
        style.configure('TButton', background=self.colors['accent'], foreground=self.colors['text'],
                        borderwidth=0, relief='flat', focuscolor='')
        style.map('TButton', background=[('active', self.colors['highlight'])])
        style.configure('TCheckbutton', background=self.colors['bg'], foreground=self.colors['text'],
                        indicatorbackground='#404040', indicatorforeground='white',
                        indicatorsize=16)
        style.map('TCheckbutton', background=[('active', self.colors['bg'])])
        style.configure('TEntry', fieldbackground=self.colors['bg_light'], foreground=self.colors['text'],
                        borderwidth=0, relief='flat', padding=2)
        style.configure('TSeparator', background=self.colors['accent'])

        # Scrollbar styling - use 'alt' theme element (no grip lines)
        style.element_create('NoGrip.Scrollbar.thumb', 'from', 'alt')
        style.layout('NoGrip.Vertical.TScrollbar', [
            ('Vertical.Scrollbar.trough', {
                'sticky': 'ns',
                'children': [
                    ('NoGrip.Scrollbar.thumb', {'sticky': 'nswe', 'expand': True})
                ]
            })
        ])
        style.configure('NoGrip.Vertical.TScrollbar',
                        background='#404040',
                        troughcolor='#1e1e1e',
                        borderwidth=0,
                        relief='flat',
                        width=10)
        style.map('NoGrip.Vertical.TScrollbar',
                  background=[('active', '#505050'), ('pressed', '#505050')])

        # Scale (slider) styling - no grip lines, no outlines
        style.configure('TScale',
                        background='#404040',
                        troughcolor=self.colors['bg_light'],
                        sliderlength=20,
                        borderwidth=0,
                        relief='flat',
                        gripcount=0,
                        lightcolor='#404040',
                        darkcolor='#404040',
                        bordercolor='#404040',
                        focuscolor='',
                        highlightthickness=0)
        style.configure('Horizontal.TScale',
                        background='#404040',
                        lightcolor='#404040',
                        darkcolor='#404040',
                        bordercolor='#404040',
                        troughcolor=self.colors['bg_light'])

        # Section header style
        style.configure('Header.TLabel',
                        background=self.colors['bg'],
                        foreground=self.colors['highlight'],
                        font=('Arial', 11, 'bold'))

        # Dim text style
        style.configure('Dim.TLabel',
                        background=self.colors['bg'],
                        foreground=self.colors['text_dim'])

    def build_ui(self):
        # Custom title bar
        title_bar = tk.Frame(self.root, bg=self.colors['bg_light'], height=32)
        title_bar.pack(fill='x', side='top')
        title_bar.pack_propagate(False)

        # Drag functionality (define first so we can use it)
        def start_drag(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def drag(event):
            x = self.root.winfo_x() + event.x - self._drag_x
            y = self.root.winfo_y() + event.y - self._drag_y
            self.root.geometry(f"+{x}+{y}")

        # Icon in title bar
        try:
            if hasattr(self, 'icon_image'):
                # Resize icon for title bar
                w, h = self.icon_image.width(), self.icon_image.height()
                factor = max(1, min(w, h) // 20)
                small_icon = self.icon_image.subsample(factor, factor)
                self.title_icon = small_icon  # Keep reference
                icon_label = tk.Label(title_bar, image=small_icon, bg=self.colors['bg_light'])
                icon_label.pack(side='left', padx=(8, 2))
                icon_label.bind('<Button-1>', start_drag)
                icon_label.bind('<B1-Motion>', drag)
        except:
            pass

        # Title label
        title_label = tk.Label(title_bar, text="QD 1.4.0", bg=self.colors['bg_light'],
                               fg=self.colors['text'], font=('Arial', 10, 'bold'))
        title_label.pack(side='left', padx=2)


        # Close button (rightmost)
        close_btn = tk.Label(title_bar, text=" ✕ ", bg=self.colors['bg_light'],
                            fg=self.colors['text'], font=('Arial', 12), cursor='hand2')
        close_btn.pack(side='right', padx=2)
        close_btn.bind('<Button-1>', lambda e: self.on_close())
        close_btn.bind('<Enter>', lambda e: close_btn.config(bg=self.colors['highlight']))
        close_btn.bind('<Leave>', lambda e: close_btn.config(bg=self.colors['bg_light']))

        # Minimize to tray button (down triangle) - middle
        tray_btn = tk.Label(title_bar, text=" ▼ ", bg=self.colors['bg_light'],
                           fg=self.colors['text'], font=('Arial', 10), cursor='hand2')
        tray_btn.pack(side='right', padx=2)
        tray_btn.bind('<Button-1>', lambda e: self.minimize_to_tray())
        tray_btn.bind('<Enter>', lambda e: tray_btn.config(bg=self.colors['accent']))
        tray_btn.bind('<Leave>', lambda e: tray_btn.config(bg=self.colors['bg_light']))

        # Minimize button (leftmost)
        min_btn = tk.Label(title_bar, text=" ─ ", bg=self.colors['bg_light'],
                          fg=self.colors['text'], font=('Arial', 12), cursor='hand2')
        min_btn.pack(side='right', padx=2)
        min_btn.bind('<Button-1>', lambda e: self.minimize_window())
        min_btn.bind('<Enter>', lambda e: min_btn.config(bg=self.colors['accent']))
        min_btn.bind('<Leave>', lambda e: min_btn.config(bg=self.colors['bg_light']))

        # Bind drag to title bar and label
        title_bar.bind('<Button-1>', start_drag)
        title_bar.bind('<B1-Motion>', drag)
        title_label.bind('<Button-1>', start_drag)
        title_label.bind('<B1-Motion>', drag)

        # Create main container with scrollbar
        container = ttk.Frame(self.root)
        container.pack(fill='both', expand=True)

        # Canvas for scrolling
        self.canvas = tk.Canvas(container, bg=self.colors['bg'], highlightthickness=0)

        # Custom minimal scrollbar using Canvas (no grip lines, clean look)
        self.scrollbar_canvas = tk.Canvas(container, width=10, bg='#1e1e1e', highlightthickness=0, bd=0)
        self.scrollbar_thumb = None
        self.scrollbar_dragging = False
        self.scrollbar_drag_start = 0

        def update_scrollbar(*args):
            if len(args) == 2:
                top, bottom = float(args[0]), float(args[1])
                height = self.scrollbar_canvas.winfo_height()
                thumb_top = int(top * height)
                thumb_bottom = int(bottom * height)
                thumb_height = max(30, thumb_bottom - thumb_top)  # Min thumb size
                self.scrollbar_canvas.delete('thumb')
                self.scrollbar_canvas.create_rectangle(
                    2, thumb_top, 8, thumb_top + thumb_height,
                    fill='#404040', outline='', tags='thumb'
                )

        def on_scrollbar_click(event):
            self.scrollbar_dragging = True
            self.scrollbar_drag_start = event.y

        def on_scrollbar_drag(event):
            if self.scrollbar_dragging:
                delta = event.y - self.scrollbar_drag_start
                self.scrollbar_drag_start = event.y
                height = self.scrollbar_canvas.winfo_height()
                self.canvas.yview_moveto(self.canvas.yview()[0] + delta / height)

        def on_scrollbar_release(event):
            self.scrollbar_dragging = False

        self.scrollbar_canvas.bind('<Button-1>', on_scrollbar_click)
        self.scrollbar_canvas.bind('<B1-Motion>', on_scrollbar_drag)
        self.scrollbar_canvas.bind('<ButtonRelease-1>', on_scrollbar_release)

        # Scrollable frame inside canvas
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=update_scrollbar)

        # Make scrollable frame expand to canvas width so content can center
        def on_canvas_configure(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)
        self.canvas.bind('<Configure>', on_canvas_configure)

        # Force initial width update after window is drawn
        def set_initial_width():
            self.canvas.update_idletasks()
            self.canvas.itemconfig(self.canvas_window, width=self.canvas.winfo_width())
        self.root.after(50, set_initial_width)

        # Pack scrollbar and canvas
        self.scrollbar_canvas.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)

        # Enable mousewheel scrolling
        self.canvas.bind_all('<MouseWheel>', lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units'))

        # Build content in scrollable frame
        frame = self.scrollable_frame

        # ===== STAY ON TOP CHECKBOX =====
        self.stay_on_top_var = tk.BooleanVar(value=self.config.get("stay_on_top", False))
        ttk.Checkbutton(frame, text="Stay on top", variable=self.stay_on_top_var, command=self.toggle_stay_on_top).pack(anchor='w', padx=10, pady=5)

        # ===== SHOW OVERLAY CHECKBOX =====
        self.show_overlay_var = tk.BooleanVar(value=self.config.get("show_overlay", True))
        ttk.Checkbutton(frame, text="Show on-screen text", variable=self.show_overlay_var, command=self.save_settings).pack(anchor='w', padx=10, pady=5)

        # ===== TIMING VARIANCE SLIDER =====
        variance_frame = ttk.Frame(frame)
        variance_frame.pack(fill='x', padx=10, pady=5)
        ttk.Label(variance_frame, text="Timing variance:").pack(side='left')
        self.timing_variance_var = tk.IntVar(value=self.config.get("timing_variance", 0))
        variance_slider = ttk.Scale(variance_frame, from_=0, to=20, orient='horizontal', variable=self.timing_variance_var, length=100, command=lambda v: self.save_settings())
        variance_slider.pack(side='left', padx=5)
        self.variance_label = ttk.Label(variance_frame, text=f"±{self.timing_variance_var.get()}%")
        self.variance_label.pack(side='left')
        self.timing_variance_var.trace_add('write', lambda *args: self.variance_label.config(text=f"±{self.timing_variance_var.get()}%"))

        # ===== DRAG DROP FALLBACK =====
        # Only use drag drop if: user manually enabled it, OR vigembus failed and user hasn't disabled it
        self.use_drag_drop_var = tk.BooleanVar(value=self.config.get("use_drag_drop", False))
        drag_drop_frame = ttk.Frame(frame)
        drag_drop_frame.pack(anchor='w', padx=10, pady=5)
        ttk.Checkbutton(drag_drop_frame, text="Use drag & drop (if ViGEmBus fails)", variable=self.use_drag_drop_var, command=self.on_drag_drop_manual_toggle).pack(side='left')
        dragdrop_info = ttk.Label(drag_drop_frame, text=" (?)", foreground='#888888', cursor='hand2')
        dragdrop_info.pack(side='left')
        dragdrop_info.bind('<Button-1>', lambda e: self._show_vigembus_help())
        self._add_tooltip(dragdrop_info, "Click for ViGEmBus (preferred method) info")

        # Drag timing values (used for drag drop fallback)
        self.drag_wait_after = 300    # ms after drop before Tab close

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== QUICK DISCONNECT SECTION =====
        ttk.Label(frame, text="── Quick Disconnect ──", style='Header.TLabel').pack(pady=(5, 5))

        # DC Both (In+Out) row
        dc_both_frame = ttk.Frame(frame)
        dc_both_frame.pack(fill='x', padx=10, pady=2)
        self.dc_both_btn = tk.Button(dc_both_frame, text="DC BOTH", width=12, bg='#3c3c3c', fg='#e0e0e0',
                                     activebackground='#e94560', activeforeground='white', bd=0,
                                     command=self.toggle_dc_both)
        self.dc_both_btn.pack(side='left')
        ttk.Label(dc_both_frame, text="Hotkey:").pack(side='left', padx=(10, 0))
        self.dc_both_hotkey_var = tk.StringVar(value=self.config.get("dc_both_hotkey", ""))
        self.dc_both_hotkey_entry = tk.Entry(dc_both_frame, textvariable=self.dc_both_hotkey_var, width=10, state="readonly",
                                            bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.dc_both_hotkey_entry.pack(side='left', padx=5)
        self.dc_both_record_btn = ttk.Button(dc_both_frame, text="Set", width=4, command=self.start_recording_dc_both)
        self.dc_both_record_btn.pack(side='left')

        # DC Outbound Only row
        dc_out_frame = ttk.Frame(frame)
        dc_out_frame.pack(fill='x', padx=10, pady=2)
        self.dc_outbound_btn = tk.Button(dc_out_frame, text="DC OUTBOUND", width=12, bg='#3c3c3c', fg='#e0e0e0',
                                         activebackground='#e94560', activeforeground='white', bd=0,
                                         command=self.toggle_dc_outbound)
        self.dc_outbound_btn.pack(side='left')
        ttk.Label(dc_out_frame, text="Hotkey:").pack(side='left', padx=(10, 0))
        self.dc_outbound_hotkey_var = tk.StringVar(value=self.config.get("dc_outbound_hotkey", ""))
        self.dc_outbound_hotkey_entry = tk.Entry(dc_out_frame, textvariable=self.dc_outbound_hotkey_var, width=10, state="readonly",
                                                bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.dc_outbound_hotkey_entry.pack(side='left', padx=5)
        self.dc_outbound_record_btn = ttk.Button(dc_out_frame, text="Set", width=4, command=self.start_recording_dc_outbound)
        self.dc_outbound_record_btn.pack(side='left')

        # DC Inbound Only row
        dc_in_frame = ttk.Frame(frame)
        dc_in_frame.pack(fill='x', padx=10, pady=2)
        self.dc_inbound_btn = tk.Button(dc_in_frame, text="DC INBOUND", width=12, bg='#3c3c3c', fg='#e0e0e0',
                                        activebackground='#e94560', activeforeground='white', bd=0,
                                        command=self.toggle_dc_inbound)
        self.dc_inbound_btn.pack(side='left')
        ttk.Label(dc_in_frame, text="Hotkey:").pack(side='left', padx=(10, 0))
        self.dc_inbound_hotkey_var = tk.StringVar(value=self.config.get("dc_inbound_hotkey", ""))
        self.dc_inbound_hotkey_entry = tk.Entry(dc_in_frame, textvariable=self.dc_inbound_hotkey_var, width=10, state="readonly",
                                               bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.dc_inbound_hotkey_entry.pack(side='left', padx=5)
        self.dc_inbound_record_btn = ttk.Button(dc_in_frame, text="Set", width=4, command=self.start_recording_dc_inbound)
        self.dc_inbound_record_btn.pack(side='left')

        # Tamper button (corrupts packets instead of dropping)
        tamper_frame = ttk.Frame(frame)
        tamper_frame.pack(fill='x', padx=10, pady=2)
        self.tamper_btn = tk.Button(tamper_frame, text="TAMPER", width=12, bg='#3c3c3c', fg='#e0e0e0',
                                    activebackground='#ff8c00', activeforeground='white', bd=0,
                                    command=self.toggle_tamper)
        self.tamper_btn.pack(side='left')
        ttk.Label(tamper_frame, text="Hotkey:").pack(side='left', padx=(10, 0))
        self.tamper_hotkey_var = tk.StringVar(value=self.config.get("tamper_hotkey", ""))
        self.tamper_hotkey_entry = tk.Entry(tamper_frame, textvariable=self.tamper_hotkey_var, width=10, state="readonly",
                                           bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.tamper_hotkey_entry.pack(side='left', padx=5)
        self.tamper_record_btn = ttk.Button(tamper_frame, text="Set", width=4, command=self.start_recording_tamper)
        self.tamper_record_btn.pack(side='left')
        tamper_info = ttk.Label(tamper_frame, text=" (?)", foreground='#888888', cursor='hand2')
        tamper_info.pack(side='left')
        self._add_tooltip(tamper_info, "Corrupts packets instead of dropping them.\nCan cause weird behavior instead of full DC.")

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== KEYDOOR METHOD SECTION =====
        keydoor_header = ttk.Frame(frame)
        keydoor_header.pack(pady=(0, 5))
        ttk.Label(keydoor_header, text="── Keydoor Method ──", style='Header.TLabel').pack(side='left')
        keydoor_info = ttk.Label(keydoor_header, text=" (?)", foreground='#888888', cursor='hand2')
        keydoor_info.pack(side='left')
        self._add_tooltip(keydoor_info, "SETUP: Use default settings and record the key's position in your inventory.\n\nTEST FIRST: Stand AWAY from keydoor, open inventory, press hotkey.\nKey should drop then get picked up instantly when inventory closes.\n\nIF ITEM DOESN'T DROP:\n- Record position again more accurately\n- Install ViGEmBus driver\n- Or enable drag & drop mode and record the drag path\n\nWHEN DOING GLITCH: Always open inventory BEFORE approaching door.")

        # Keydoor Hotkey row
        hk_frame = ttk.Frame(frame)
        hk_frame.pack(fill='x', padx=10, pady=5)
        ttk.Label(hk_frame, text="Hotkey:").pack(side='left')
        self.dc_hotkey_var = tk.StringVar(value=self.config.get("dc_hotkey", ""))
        self.dc_hotkey_entry = tk.Entry(hk_frame, textvariable=self.dc_hotkey_var, width=15, state="readonly",
                                       bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.dc_hotkey_entry.pack(side='left', padx=5)
        self.dc_record_btn = ttk.Button(hk_frame, text="Set", width=6, command=self.start_recording_dc)
        self.dc_record_btn.pack(side='left', padx=5)

        # Keydoor drag record (works for both Xbox X and drag drop)
        keydoor_drag_frame = ttk.Frame(frame)
        keydoor_drag_frame.pack(fill='x', padx=10, pady=2)
        self.keydoor_drag_btn = ttk.Button(keydoor_drag_frame, text="Record", width=12, command=self.start_keydoor_drag_recording)
        self.keydoor_drag_btn.pack(side='left')
        self.keydoor_drag_var = tk.StringVar()
        # Load keydoor drag positions
        # Separate storage: slot position vs drag path
        kd_slot = self.config.get("keydoor_slot_pos", [3024, 669])
        kd_drag_start = self.config.get("keydoor_drag_start", [3024, 669])
        kd_drag_end = self.config.get("keydoor_drag_end", [550, 1247])
        self.keydoor_slot_pos = tuple(kd_slot)
        self.keydoor_drag_start = tuple(kd_drag_start)
        self.keydoor_drag_end = tuple(kd_drag_end)
        if self.use_drag_drop_var.get():
            self.keydoor_drag_var.set(f"({kd_drag_start[0]},{kd_drag_start[1]}) → ({kd_drag_end[0]},{kd_drag_end[1]})")
        else:
            self.keydoor_drag_var.set(f"Pos: ({kd_slot[0]},{kd_slot[1]})")
        ttk.Label(keydoor_drag_frame, textvariable=self.keydoor_drag_var, font=("Consolas", 8)).pack(side='left', padx=5)

        # Keydoor Timings
        self.create_slider(frame, "X button hold:", "keydoor_x_hold", 1250, 500, 3000, "ms")
        self.create_slider(frame, "Tab hold:", "keydoor_tab_hold", 21, 10, 200, "ms")
        self.create_slider(frame, "Wait before E spam:", "keydoor_wait_before_e", 73, 0, 500, "ms")
        self.create_slider(frame, "E spam count:", "keydoor_espam_count", 30, 5, 100, "")
        self.create_slider(frame, "E press duration:", "keydoor_e_hold", 13, 5, 100, "ms")
        self.create_slider(frame, "E spam delay:", "keydoor_e_delay", 12, 5, 100, "ms")

        # Keydoor Reset + Status
        ttk.Button(frame, text="Reset Keydoor Defaults", command=self.reset_keydoor_defaults).pack(pady=5)
        self.dc_status_var = tk.StringVar(value="Ready")
        self.dc_status_label = ttk.Label(frame, textvariable=self.dc_status_var, style='Dim.TLabel')
        self.dc_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== THROWABLE SECTION =====
        throwable_header = ttk.Frame(frame)
        throwable_header.pack(pady=(5, 5))
        ttk.Label(throwable_header, text="── Throwable Dupe ──", style='Header.TLabel').pack(side='left')
        throwable_info = ttk.Label(throwable_header, text=" (?)", foreground='#888888', cursor='hand2')
        throwable_info.pack(side='left')
        self._add_tooltip(throwable_info, "Your character should do 2 pumps, releasing throwable\nitem on 2nd pump. Once that is true, modify 'Delay before DC'\nslightly in either direction until consistent as possible.\n\nTIP: Get it working SINGLE USE first. For auto-repeat, item must roll under your feet\nto be grabbed for looping. Drop piles of 1 of item you're duping around feet as backup copies to grab.")

        # Throwable Hotkey row
        throw_hk = ttk.Frame(frame)
        throw_hk.pack(fill='x', padx=10, pady=5)
        ttk.Label(throw_hk, text="Hotkey:").pack(side='left')
        self.throwable_hotkey_var = tk.StringVar(value=self.config.get("throwable_hotkey", ""))
        self.throwable_hotkey_entry = tk.Entry(throw_hk, textvariable=self.throwable_hotkey_var, width=15, state="readonly",
                                             bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.throwable_hotkey_entry.pack(side='left', padx=5)
        self.throwable_record_btn = ttk.Button(throw_hk, text="Set", width=6, command=self.start_recording_throwable)
        self.throwable_record_btn.pack(side='left', padx=5)

        # Repeat checkbox
        self.throwable_repeat_var = tk.BooleanVar(value=self.config.get("throwable_repeat", False))
        ttk.Checkbutton(frame, text="Auto (loop until pressed again)", variable=self.throwable_repeat_var, command=self.save_settings).pack(anchor='w', padx=10, pady=5)

        # Throwable Timings
        self.create_slider(frame, "Throw hold time:", "throw_hold_time", 45, 10, 200, "ms")
        self.create_slider(frame, "Delay before DC:", "throw_dc_delay_before", 40, 0, 200, "ms", bold=True)
        self.create_slider(frame, "Wait before E:", "throw_wait_before_e", 200, 0, 2000, "ms")
        self.create_slider(frame, "E hold time:", "throw_e_hold", 50, 10, 500, "ms")
        # Double E option (for fuel canisters - disarm then pickup)
        self.throw_double_e_var = tk.BooleanVar(value=self.config.get("throw_double_e", False))
        ttk.Checkbutton(frame, text="Double E (disarm + pickup)", variable=self.throw_double_e_var, command=self.save_settings).pack(anchor='w', padx=10, pady=2)
        self.create_slider(frame, "Wait between E:", "throw_e_gap", 200, 50, 1000, "ms")
        self.create_slider(frame, "2nd E hold:", "throw_e2_hold", 50, 10, 500, "ms")
        self.create_slider(frame, "Wait after E:", "throw_wait_after_e", 100, 0, 1000, "ms")
        self.create_slider(frame, "Wait after Q:", "throw_wait_after_q", 750, 0, 2000, "ms")
        throwable_tip = "Your character should do 2 pumps, releasing throwable item on 2nd pump. Once that is true, modify 'Delay before DC' slightly in either direction until consistent."
        self.create_slider(frame, "Throws while DC'd:", "throw_dc_count", 12, 1, 30, "", bold=True, tooltip=throwable_tip)
        self.create_slider(frame, "Time between throws:", "throw_dc_delay", 86, 10, 500, "ms", bold=True, tooltip=throwable_tip)

        ttk.Button(frame, text="Reset Throwable Defaults", command=self.reset_throwable_defaults).pack(pady=5)
        self.throwable_status_var = tk.StringVar(value="Ready")
        self.throwable_status_label = ttk.Label(frame, textvariable=self.throwable_status_var, style='Dim.TLabel')
        self.throwable_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== TRIGGERNADE SECTION =====
        trig_header = ttk.Frame(frame)
        trig_header.pack(pady=(5, 5))
        ttk.Label(trig_header, text="── Wolfpack/Triggernade Dupe ──", style='Header.TLabel').pack(side='left')
        trig_info = ttk.Label(trig_header, text=" (?)", foreground='#888888', cursor='hand2')
        trig_info.pack(side='left')
        self._add_tooltip(trig_info, "Record position of first quick use slot (or drag path if ViGEmBus not working).\n\nMake sure inventory is full of items you're NOT duping (e.g. stacks of 1 ammo).\nFill safe pockets as well.\n\nQuick use slots must be empty EXCEPT item you're duping in first slot.\nEven utility slots must be empty.\n\nThen press Q to bring out wolfpack/triggernade/leaper pulse unit/other grenade and hit hotkey.\n\nTIP: Get it working SINGLE USE first. For auto-repeat, item must roll under your feet\nto be grabbed for looping. Drop piles of 1 of item you're duping around feet as backup copies to grab.\n\nTRIGGERNADES: Start with stack of 3 in first quick use slot - if it fails 2x it keeps going.\nTriggernades are unique: when picked up they return to the same stack.")

        # Triggernade Hotkey row
        trig_hk = ttk.Frame(frame)
        trig_hk.pack(fill='x', padx=10, pady=5)
        ttk.Label(trig_hk, text="Hotkey:").pack(side='left')
        self.triggernade_hotkey_var = tk.StringVar(value=self.config.get("triggernade_hotkey", ""))
        self.triggernade_hotkey_entry = tk.Entry(trig_hk, textvariable=self.triggernade_hotkey_var, width=15, state="readonly",
                                               bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.triggernade_hotkey_entry.pack(side='left', padx=5)
        self.triggernade_record_btn = ttk.Button(trig_hk, text="Set", width=6, command=self.start_recording_triggernade)
        self.triggernade_record_btn.pack(side='left', padx=5)

        # Triggernade drag record (works for both Xbox X and drag drop)
        trig_drag_frame = ttk.Frame(frame)
        trig_drag_frame.pack(fill='x', padx=10, pady=2)
        self.trig_drag_btn = ttk.Button(trig_drag_frame, text="Record", width=12, command=self.start_trig_drag_recording)
        self.trig_drag_btn.pack(side='left')
        self.trig_drag_var = tk.StringVar()
        # Load triggernade drag positions
        # Separate storage: slot position vs drag path
        trig_slot = self.config.get("trig_slot_pos", [3024, 669])
        trig_drag_start = self.config.get("trig_drag_start", [3024, 669])
        trig_drag_end = self.config.get("trig_drag_end", [550, 1247])
        self.trig_slot_pos = tuple(trig_slot)
        self.trig_drag_start = tuple(trig_drag_start)
        self.trig_drag_end = tuple(trig_drag_end)
        if self.use_drag_drop_var.get():
            self.trig_drag_var.set(f"({trig_drag_start[0]},{trig_drag_start[1]}) → ({trig_drag_end[0]},{trig_drag_end[1]})")
        else:
            self.trig_drag_var.set(f"Pos: ({trig_slot[0]},{trig_slot[1]})")
        ttk.Label(trig_drag_frame, textvariable=self.trig_drag_var, font=("Consolas", 8)).pack(side='left', padx=5)

        # Repeat checkbox
        self.triggernade_repeat_var = tk.BooleanVar(value=self.config.get("triggernade_repeat", False))
        ttk.Checkbutton(frame, text="Auto (loop until pressed again)", variable=self.triggernade_repeat_var, command=self.save_settings).pack(anchor='w', padx=10, pady=5)

        # Q spam checkbox (optional re-equip between cycles)
        self.triggernade_q_spam_var = tk.BooleanVar(value=self.config.get("triggernade_q_spam", True))
        ttk.Checkbutton(frame, text="Q spam between cycles (re-equip)", variable=self.triggernade_q_spam_var, command=self.save_settings).pack(anchor='w', padx=10, pady=2)

        # Triggernade Timings
        # Cook time - THE MOST IMPORTANT TIMING (use same layout as other sliders)
        cook_frame = ttk.Frame(frame)
        cook_frame.pack(fill='x', padx=10, pady=2)
        ttk.Label(cook_frame, text="Cook time:", width=20, anchor='w',
                  font=("Arial", 9, "bold")).pack(side='left')
        self.trig_m1_hold_var = tk.IntVar(value=int(self.config.get("trig_m1_hold", 65)))

        def on_cook_slide(val):
            self.trig_m1_hold_var.set(int(float(val)))
            self.save_settings()

        cook_slider = ttk.Scale(cook_frame, from_=10, to=500, variable=self.trig_m1_hold_var,
                               orient='horizontal', length=100, command=on_cook_slide)
        cook_slider.pack(side='left', padx=5)

        cook_entry = tk.Entry(cook_frame, width=5, justify='center', bd=0, highlightthickness=0,
                             bg='#2d2d2d', fg='#e0e0e0', insertbackground='white')
        cook_entry.pack(side='left')
        cook_entry.insert(0, str(self.trig_m1_hold_var.get()))

        def on_cook_entry(event=None):
            try:
                val = int(cook_entry.get())
                val = max(10, min(10000, val))
                self.trig_m1_hold_var.set(val)
                cook_entry.delete(0, 'end')
                cook_entry.insert(0, str(val))
                self.save_settings()
            except ValueError:
                cook_entry.delete(0, 'end')
                cook_entry.insert(0, str(self.trig_m1_hold_var.get()))

        def on_cook_var_change(*args):
            cook_entry.delete(0, 'end')
            cook_entry.insert(0, str(self.trig_m1_hold_var.get()))

        cook_entry.bind('<Return>', on_cook_entry)
        cook_entry.bind('<FocusOut>', on_cook_entry)
        self.trig_m1_hold_var.trace_add('write', on_cook_var_change)
        ttk.Label(cook_frame, text="ms").pack(side='left')
        self.create_slider(frame, "M2 hold time:", "trig_m2_hold", 51, 10, 500, "ms")
        self.create_slider(frame, "Delay before DC:", "trig_dc_delay", 10, 0, 200, "ms")
        self.create_slider(frame, "M1s while DC'd:", "trig_dc_throws", 10, 1, 30, "")
        self.create_slider(frame, "Time between M1s:", "trig_throw_delay", 100, 10, 500, "ms")
        self.create_slider(frame, "Reconnect after M1 #:", "trig_reconnect_after", 1, 1, 20, "")
        self.create_slider(frame, "Wait before E spam:", "wait_before_espam", 0, 0, 2000, "ms")
        self.create_slider(frame, "E spam duration:", "espam_duration", 1000, 0, 5000, "ms")
        self.create_slider(frame, "M1s before E interweave:", "trig_m1_before_interweave", 5, 0, 20, "")
        self.create_slider(frame, "Wait before next cycle:", "wait_before_cycle", 100, 0, 2000, "ms")

        ttk.Button(frame, text="Reset Triggernade Defaults", command=self.reset_triggernade_defaults).pack(pady=5)
        self.triggernade_status_var = tk.StringVar(value="Ready")
        self.triggernade_status_label = ttk.Label(frame, textvariable=self.triggernade_status_var, style='Dim.TLabel')
        self.triggernade_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== MINE DUPE SECTION =====
        mine_header = ttk.Frame(frame)
        mine_header.pack(pady=(5, 5))
        ttk.Label(mine_header, text="── Mine Dupe ──", style='Header.TLabel').pack(side='left')
        mine_info = ttk.Label(mine_header, text=" (?)", foreground='#888888', cursor='hand2')
        mine_info.pack(side='left')
        self._add_tooltip(mine_info, "Record position of mine in inventory (or drag path if ViGEmBus not working).\nIf using SURVIVOR AUGMENT: record position of UTILITY SLOT or it won't work.\n\nCOOK TIME: The use circle should be ALMOST full when inventory opens.\n- If mine deploys before/while opening inventory: reduce cook time\n- Make small adjustments until circle is mostly full on open\n\nDELAY BEFORE DC: Make very light adjustments if still not working.\n\nRECONNECT TO CLICK: If mine drops from inventory but duplicate doesn't place,\nadjust this timing in small increments either direction. Watch for consistency.\n\nTIP: Get it working SINGLE USE first. For auto-repeat, item must roll under your feet\nto be grabbed for looping. Drop piles of 1 of item you're duping around feet as backup copies to grab.")

        # Mine Hotkey row
        mine_hk = ttk.Frame(frame)
        mine_hk.pack(fill='x', padx=10, pady=5)
        ttk.Label(mine_hk, text="Hotkey:").pack(side='left')
        self.mine_hotkey_var = tk.StringVar(value=self.config.get("mine_hotkey", ""))
        self.mine_hotkey_entry = tk.Entry(mine_hk, textvariable=self.mine_hotkey_var, width=15, state="readonly",
                                         bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.mine_hotkey_entry.pack(side='left', padx=5)
        self.mine_record_btn = ttk.Button(mine_hk, text="Set", width=6, command=self.start_recording_mine)
        self.mine_record_btn.pack(side='left', padx=5)

        self.mine_repeat_var = tk.BooleanVar(value=self.config.get("mine_repeat", False))
        ttk.Checkbutton(frame, text="Auto-repeat", variable=self.mine_repeat_var, command=self.save_settings).pack(anchor='w', padx=10, pady=2)

        # Mine drag/slot record
        mine_drag_frame = ttk.Frame(frame)
        mine_drag_frame.pack(fill='x', padx=10, pady=5)
        self.mine_drag_btn = ttk.Button(mine_drag_frame, text="Record", width=12, command=self.start_mine_drag_recording)
        self.mine_drag_btn.pack(side='left')
        self.mine_drag_var = tk.StringVar()
        # Separate storage: slot position vs drag path
        mine_slot = self.config.get("mine_slot_pos", [2966, 1196])
        mine_drag_start = self.config.get("mine_drag_start", [2966, 1196])
        mine_drag_end = self.config.get("mine_drag_end", [1035, 1291])
        self.mine_slot_pos = tuple(mine_slot)
        self.mine_drag_start = tuple(mine_drag_start)
        self.mine_drag_end = tuple(mine_drag_end)
        if self.use_drag_drop_var.get():
            self.mine_drag_var.set(f"({mine_drag_start[0]},{mine_drag_start[1]}) → ({mine_drag_end[0]},{mine_drag_end[1]})")
        else:
            self.mine_drag_var.set(f"Pos: ({mine_slot[0]},{mine_slot[1]})")
        ttk.Label(mine_drag_frame, textvariable=self.mine_drag_var, font=("Consolas", 8)).pack(side='left', padx=10)

        # Mine Timings
        ttk.Label(frame, text="Timings:", font=("Arial", 9, "bold")).pack(anchor='w', padx=10, pady=(5, 2))

        # Cook time with extended range (slider 500, entry 10000)
        mine_cook_frame = ttk.Frame(frame)
        mine_cook_frame.pack(fill='x', padx=10, pady=2)
        ttk.Label(mine_cook_frame, text="Cook time:", width=20, anchor='w', font=("Arial", 9, "bold")).pack(side='left')
        self.mine_cook_var = tk.IntVar(value=int(self.config.get("mine_cook", 1000)))

        def on_mine_cook_slide(val):
            self.mine_cook_var.set(int(float(val)))
            self.save_settings()

        mine_cook_slider = ttk.Scale(mine_cook_frame, from_=10, to=5000, variable=self.mine_cook_var,
                                     orient='horizontal', length=100, command=on_mine_cook_slide)
        mine_cook_slider.pack(side='left', padx=5)

        mine_cook_entry = tk.Entry(mine_cook_frame, width=6, justify='center', bd=0, highlightthickness=0,
                                   bg='#2d2d2d', fg='#e0e0e0', insertbackground='white')
        mine_cook_entry.pack(side='left')
        mine_cook_entry.insert(0, str(self.mine_cook_var.get()))

        def on_mine_cook_entry(event=None):
            try:
                val = int(mine_cook_entry.get())
                val = max(10, min(10000, val))
                self.mine_cook_var.set(val)
                mine_cook_entry.delete(0, 'end')
                mine_cook_entry.insert(0, str(val))
                self.save_settings()
            except ValueError:
                mine_cook_entry.delete(0, 'end')
                mine_cook_entry.insert(0, str(self.mine_cook_var.get()))

        def on_mine_cook_var_change(*args):
            mine_cook_entry.delete(0, 'end')
            mine_cook_entry.insert(0, str(self.mine_cook_var.get()))

        mine_cook_entry.bind('<Return>', on_mine_cook_entry)
        mine_cook_entry.bind('<FocusOut>', on_mine_cook_entry)
        self.mine_cook_var.trace_add('write', on_mine_cook_var_change)
        ttk.Label(mine_cook_frame, text="ms").pack(side='left')

        self.create_slider(frame, "Delay before DC:", "mine_dc_delay", 50, 0, 500, "ms", bold=True)
        self.create_slider(frame, "X hold (drop):", "mine_x_hold", 817, 100, 1500, "ms")
        self.create_slider(frame, "Reconnect to click:", "mine_click_delay", 50, 0, 500, "ms", bold=True)
        self.create_slider(frame, "Dupe click hold:", "mine_pickup_hold", 1800, 100, 3000, "ms")
        self.create_slider(frame, "Delay before E:", "mine_e_delay", 80, 0, 1000, "ms")
        self.create_slider(frame, "Delay before loop:", "mine_loop_delay", 800, 0, 2000, "ms")

        ttk.Button(frame, text="Reset Mine Defaults", command=self.reset_mine_defaults).pack(pady=5)
        self.mine_status_var = tk.StringVar(value="Ready")
        self.mine_status_label = ttk.Label(frame, textvariable=self.mine_status_var, style='Dim.TLabel')
        self.mine_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== E-SPAM COLLECTION SECTION =====
        espam_header = ttk.Frame(frame)
        espam_header.pack(pady=(5, 5))
        ttk.Label(espam_header, text="── E-Spam Collection ──", style='Header.TLabel').pack(side='left')
        espam_info = ttk.Label(espam_header, text=" (?)", foreground='#888888', cursor='hand2')
        espam_info.pack(side='left')
        self._add_tooltip(espam_info, "Used to gather already completed mines/triggernades.")

        espam_hk = ttk.Frame(frame)
        espam_hk.pack(fill='x', padx=10, pady=5)
        ttk.Label(espam_hk, text="Hotkey:").pack(side='left')
        self.espam_hotkey_var = tk.StringVar(value=self.config.get("espam_hotkey", ""))
        self.espam_hotkey_entry = tk.Entry(espam_hk, textvariable=self.espam_hotkey_var, width=15, state="readonly",
                                         bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.espam_hotkey_entry.pack(side='left', padx=5)
        self.espam_record_btn = ttk.Button(espam_hk, text="Set", width=6, command=self.start_recording_espam)
        self.espam_record_btn.pack(side='left', padx=5)

        # Hold vs Toggle option
        self.espam_hold_mode_var = tk.BooleanVar(value=self.config.get("espam_hold_mode", False))
        ttk.Checkbutton(frame, text="Hold to activate (vs toggle)", variable=self.espam_hold_mode_var,
                        command=self.save_settings).pack(anchor='w', padx=10, pady=2)

        # Seconds before repeat slider (0-10, default 0)
        self.create_slider(frame, "Seconds before repeat:", "espam_repeat_delay", 0, 0, 10, "s")

        self.espam_status_var = tk.StringVar(value="Ready")
        self.espam_status_label = ttk.Label(frame, textvariable=self.espam_status_var, style='Dim.TLabel')
        self.espam_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== UNTITLED METHOD #1 SECTION =====
        um1_header = ttk.Frame(frame)
        um1_header.pack(pady=(5, 5))
        ttk.Label(um1_header, text="── Ammo ──", style='Header.TLabel').pack(side='left')
        um1_info = ttk.Label(um1_header, text=" (?)", foreground='#888888', cursor='hand2')
        um1_info.pack(side='left')
        self._add_tooltip(um1_info, "TAB→RightClick→DC→Drop→Grab→Reconnect→Complete→TAB→Equip")

        # Hotkey row
        um1_hk = ttk.Frame(frame)
        um1_hk.pack(fill='x', padx=10, pady=5)
        ttk.Label(um1_hk, text="Hotkey:").pack(side='left')
        self.untitled1_hotkey_var = tk.StringVar(value=self.config.get("untitled1_hotkey", ""))
        self.untitled1_hotkey_entry = tk.Entry(um1_hk, textvariable=self.untitled1_hotkey_var, width=15, state="readonly",
                                               bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.untitled1_hotkey_entry.pack(side='left', padx=5)
        self.untitled1_record_btn = ttk.Button(um1_hk, text="Set", width=6, command=self.start_recording_untitled1)
        self.untitled1_record_btn.pack(side='left', padx=5)

        # Position recording - single guided sequence
        um1_pos_frame = ttk.Frame(frame)
        um1_pos_frame.pack(fill='x', padx=10, pady=2)

        # Load saved positions
        self.um1_item_pos = tuple(self.config.get("um1_item_pos", [1777, 975]))
        self.um1_context_pos = tuple(self.config.get("um1_context_pos", [1928, 1389]))
        self.um1_drag_start = tuple(self.config.get("um1_drag_start", [1693, 990]))
        self.um1_drag_end = tuple(self.config.get("um1_drag_end", [2268, 1150]))

        self.um1_record_seq_btn = ttk.Button(um1_pos_frame, text="Record Sequence", width=16, command=self._start_um1_sequence_recording)
        self.um1_record_seq_btn.pack(side='left', padx=2)
        ttk.Label(um1_pos_frame, text="(Right-click → Left-click → Drag)", font=("Arial", 8), foreground='#888888').pack(side='left', padx=5)

        self.um1_pos_var = tk.StringVar()
        self._update_um1_pos_display()
        ttk.Label(frame, textvariable=self.um1_pos_var, font=("Consolas", 7)).pack(anchor='w', padx=10)

        # Repeat checkbox
        self.untitled1_repeat_var = tk.BooleanVar(value=self.config.get("untitled1_repeat", True))
        ttk.Checkbutton(frame, text="Auto (loop until pressed again)", variable=self.untitled1_repeat_var, command=self.save_settings).pack(anchor='w', padx=10, pady=2)

        # Timing sliders
        self.create_slider(frame, "TAB hold:", "um1_tab_hold", 30, 15, 150, "ms")
        self.create_slider(frame, "After TAB open:", "um1_after_tab_open", 50, 20, 500, "ms")
        self.create_slider(frame, "Right click hold:", "um1_rclick_hold", 30, 15, 150, "ms")
        self.create_slider(frame, "After right click:", "um1_after_rclick", 50, 20, 500, "ms")
        self.create_slider(frame, "After DC:", "um1_after_dc", 20, 10, 500, "ms")
        self.create_slider(frame, "Context click hold:", "um1_context_hold", 30, 15, 150, "ms")
        self.create_slider(frame, "After context click:", "um1_after_context", 50, 20, 500, "ms")
        self.create_slider(frame, "After reconnect:", "um1_after_reconnect", 50, 20, 500, "ms")
        self.create_slider(frame, "Dbl click hold:", "um1_dblclick_hold", 20, 10, 100, "ms")
        self.create_slider(frame, "Dbl click gap:", "um1_dblclick_gap", 15, 10, 80, "ms")
        self.create_slider(frame, "After dbl click:", "um1_after_dblclick", 59, 20, 300, "ms")
        self.create_slider(frame, "After TAB close:", "um1_after_tab_close", 61, 20, 300, "ms")
        self.create_slider(frame, "Equip key hold:", "um1_equip_hold", 67, 20, 200, "ms")
        self.create_slider(frame, "Loop delay:", "um1_loop_delay", 300, 0, 2000, "ms")

        ttk.Button(frame, text="Reset Ammo Defaults", command=self.reset_untitled1_defaults).pack(pady=5)
        self.untitled1_status_var = tk.StringVar(value="Ready")
        self.untitled1_status_label = ttk.Label(frame, textvariable=self.untitled1_status_var, style='Dim.TLabel')
        self.untitled1_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== HOTKEYS (Minimize) =====
        ttk.Label(frame, text="── Window Hotkeys ──", style='Header.TLabel').pack(pady=(5, 5))

        # Minimize hotkey
        min_hk_frame = ttk.Frame(frame)
        min_hk_frame.pack(fill='x', padx=10, pady=2)
        ttk.Label(min_hk_frame, text="Minimize:").pack(side='left')
        self.minimize_hotkey_var = tk.StringVar(value=self.config.get("minimize_hotkey", ""))
        self.minimize_hotkey_entry = tk.Entry(min_hk_frame, textvariable=self.minimize_hotkey_var, width=10, state="readonly",
                                             bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.minimize_hotkey_entry.pack(side='left', padx=5)
        self.minimize_record_btn = ttk.Button(min_hk_frame, text="Set", width=4, command=self.start_recording_minimize)
        self.minimize_record_btn.pack(side='left')
        self.recording_minimize = False

        # Minimize to tray hotkey
        tray_hk_frame = ttk.Frame(frame)
        tray_hk_frame.pack(fill='x', padx=10, pady=2)
        ttk.Label(tray_hk_frame, text="Minimize to Tray:").pack(side='left')
        self.tray_hotkey_var = tk.StringVar(value=self.config.get("tray_hotkey", ""))
        self.tray_hotkey_entry = tk.Entry(tray_hk_frame, textvariable=self.tray_hotkey_var, width=10, state="readonly",
                                         bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.tray_hotkey_entry.pack(side='left', padx=5)
        self.tray_record_btn = ttk.Button(tray_hk_frame, text="Set", width=4, command=self.start_recording_tray)
        self.tray_record_btn.pack(side='left')
        self.recording_tray = False

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== RESET ALL =====
        ttk.Button(frame, text="⚠ Reset ALL Settings", command=self.reset_all_settings).pack(pady=5)

        # ===== FOOTER =====
        ttk.Label(frame, text="Press ESC to stop all macros", style='Dim.TLabel').pack(pady=(20, 10))

        # ===== RESIZE GRIP (bottom of window) =====
        resize_grip = tk.Frame(self.root, bg='#2d2d2d', height=8, cursor='sb_v_double_arrow')
        resize_grip.pack(side='bottom', fill='x')

        def start_resize(event):
            self._resize_start_y = event.y_root
            self._resize_start_height = self.root.winfo_height()

        def do_resize(event):
            delta = event.y_root - self._resize_start_y
            new_height = max(400, self._resize_start_height + delta)  # Min height 400
            self.root.geometry(f"442x{new_height}")

        resize_grip.bind('<Button-1>', start_resize)
        resize_grip.bind('<B1-Motion>', do_resize)

        # Set initial button text based on drag drop mode
        self._update_record_button_text()

    def create_slider(self, parent, label, config_key, default, min_val, max_val, unit, bold=False, tooltip=None):
        """Create a slider row with label, slider, and editable value entry"""
        row = ttk.Frame(parent)
        row.pack(fill='x', padx=10, pady=2)

        if bold:
            lbl = ttk.Label(row, text=label, width=20, anchor='w', font=('Segoe UI', 9, 'bold'))
        else:
            lbl = ttk.Label(row, text=label, width=20, anchor='w')
        lbl.pack(side='left')

        # Add tooltip if provided
        if tooltip:
            def show_tooltip(event):
                tip = tk.Toplevel(row)
                tip.wm_overrideredirect(True)
                tip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
                tip_label = tk.Label(tip, text=tooltip, justify='left', background="#ffffe0",
                                    relief='solid', borderwidth=1, font=("Segoe UI", 8),
                                    wraplength=300)
                tip_label.pack()
                row._tooltip = tip
            def hide_tooltip(event):
                if hasattr(row, '_tooltip'):
                    row._tooltip.destroy()
                    del row._tooltip
            lbl.bind('<Enter>', show_tooltip)
            lbl.bind('<Leave>', hide_tooltip)

        var = tk.IntVar(value=int(self.config.get(config_key, default)))
        setattr(self, f"{config_key}_var", var)

        def on_slide(val):
            var.set(int(float(val)))
            self.save_settings()

        slider = ttk.Scale(row, from_=min_val, to=max_val, variable=var, orient='horizontal', length=100,
                          command=on_slide)
        slider.pack(side='left', padx=5)

        # Editable entry instead of label (no border)
        entry = tk.Entry(row, width=5, justify='center', bd=0, highlightthickness=0,
                        bg='#2d2d2d', fg='#e0e0e0', insertbackground='white')
        entry.pack(side='left')
        entry.insert(0, str(var.get()))

        def on_entry_change(event=None):
            try:
                val = int(entry.get())
                var.set(val)  # No clamping - accept any value
                self.save_settings()
            except ValueError:
                entry.delete(0, 'end')
                entry.insert(0, str(var.get()))

        def on_var_change(*args):
            entry.delete(0, 'end')
            entry.insert(0, str(var.get()))

        entry.bind('<Return>', on_entry_change)
        entry.bind('<FocusOut>', on_entry_change)
        var.trace_add('write', on_var_change)

        if unit:
            ttk.Label(row, text=unit).pack(side='left')

    def start_recording_mine(self):
        self.recording_mine = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_minimize = False
        self.recording_tray = False
        self.mine_record_btn.config(text="...")
        self.mine_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_mine_drag_recording(self):
        """Record mine drag path or slot position based on drag drop setting"""
        if self.use_drag_drop_var.get():
            self.show_overlay("10 sec - then click & drag item to drop zone")
            self._mine_drag_countdown(10, is_drag=True)
        else:
            self.show_overlay("10 sec - then click inventory slot")
            self._mine_drag_countdown(10, is_drag=False)

    def _mine_drag_countdown(self, seconds_left, is_drag=True):
        if seconds_left > 0:
            self.show_overlay(f"Get ready... {seconds_left}")
            self.root.after(1000, lambda: self._mine_drag_countdown(seconds_left - 1, is_drag))
        else:
            self._start_mine_drag_listener(is_drag)

    def _start_mine_drag_listener(self, is_drag=True):
        from pynput import mouse

        if is_drag:
            self.show_overlay("DRAG NOW!")
            drag_start_pos = [None, None]

            def on_click(x, y, button, pressed):
                if button != mouse.Button.left:
                    return
                if pressed:
                    drag_start_pos[0] = x
                    drag_start_pos[1] = y
                    self.show_overlay(f"Start: ({x},{y}) - Release to set end...")
                else:
                    if drag_start_pos[0] is not None:
                        start = (drag_start_pos[0], drag_start_pos[1])
                        end = (x, y)
                        self.mine_drag_start = start
                        self.mine_drag_end = end
                        self.config["mine_drag_start"] = list(start)
                        self.config["mine_drag_end"] = list(end)
                        self.mine_drag_var.set(f"({start[0]},{start[1]}) → ({end[0]},{end[1]})")
                        save_config(self.config)
                        self.show_overlay(f"Saved! {start} → {end}")
                        print(f"[MINE DRAG] Recorded: {start} → {end}")
                        return False
        else:
            self.show_overlay("CLICK SLOT NOW!")

            def on_click(x, y, button, pressed):
                if button != mouse.Button.left:
                    return
                if pressed:
                    self.mine_slot_pos = (x, y)
                    self.config["mine_slot_pos"] = [x, y]
                    self.mine_drag_var.set(f"Pos: ({x},{y})")
                    save_config(self.config)
                    self.show_overlay(f"Saved slot: ({x},{y})")
                    print(f"[MINE SLOT] Recorded: ({x},{y})")
                    return False

        listener = mouse.Listener(on_click=on_click)
        listener.start()

    def start_recording_espam(self):
        self.recording_espam = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_mine = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_minimize = False
        self.recording_tray = False
        self.espam_record_btn.config(text="...")
        self.espam_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_triggernade(self):
        self.recording_triggernade = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_espam = False
        self.recording_mine = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_minimize = False
        self.recording_tray = False
        self.triggernade_record_btn.config(text="...")
        self.triggernade_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_drag_recording(self):
        """Start recording drag coordinates - 10 sec countdown, then waits for mouse down/up"""
        if self.recording_drag:
            return  # Already recording

        self.recording_drag = True
        self.drag_record_btn.config(text="10...")
        self.drag_label_var.set("Get ready...")

        # Start countdown
        self._drag_countdown(10)

    def _drag_countdown(self, seconds_left):
        """Countdown before starting drag recording"""
        if not self.recording_drag:
            return  # Cancelled

        if seconds_left > 0:
            self.drag_record_btn.config(text=f"{seconds_left}...")
            self.show_overlay(f"Drag recording in {seconds_left}...")
            self.root.after(1000, lambda: self._drag_countdown(seconds_left - 1))
        else:
            # Countdown done - start listening
            self._start_drag_listener()

    def _start_drag_listener(self):
        """Actually start the mouse listener for drag recording"""
        from pynput import mouse

        self.drag_record_btn.config(text="DRAG NOW")
        self.drag_label_var.set("Click and drag item!")
        self.show_overlay("DRAG NOW!")

        drag_start_pos = [None, None]

        def on_click(x, y, button, pressed):
            if button != mouse.Button.left:
                return  # Only track left clicks

            if pressed:
                # Mouse down - record start position
                drag_start_pos[0] = x
                drag_start_pos[1] = y
                self.root.after(0, lambda: self.drag_label_var.set(f"Start: ({x},{y}) - Release..."))
                self.root.after(0, lambda: self.show_overlay(f"Start: ({x},{y}) - Release..."))
            else:
                # Mouse up - record end position and stop
                if drag_start_pos[0] is not None:
                    self.drag_start = (drag_start_pos[0], drag_start_pos[1])
                    self.drag_end = (x, y)

                    # Update UI
                    self.root.after(0, lambda: self.drag_label_var.set(
                        f"({self.drag_start[0]},{self.drag_start[1]}) → ({self.drag_end[0]},{self.drag_end[1]})"
                    ))
                    self.root.after(0, lambda: self.drag_record_btn.config(text="Record Drag"))

                    # Save to config
                    self.config["drag_start"] = list(self.drag_start)
                    self.config["drag_end"] = list(self.drag_end)
                    save_config(self.config)

                    print(f"[DRAG] Recorded: {self.drag_start} → {self.drag_end}")
                    self.root.after(0, lambda: self.show_overlay(f"Drag saved!"))

                    self.recording_drag = False
                    return False  # Stop listener

        # Start mouse listener
        self.drag_mouse_listener = mouse.Listener(on_click=on_click)
        self.drag_mouse_listener.start()

    def _start_drag_position_listener(self, target='triggernade'):
        """Listen for drag and record start/end positions only"""
        from pynput import mouse

        self.show_overlay("Click & drag item to drop zone NOW!")

        state = {'start_pos': None}
        listener_ref = [None]

        def on_click(x, y, button, pressed):
            if button != mouse.Button.left:
                return

            # Convert to int (pynput can return floats on some systems)
            x, y = int(x), int(y)

            if pressed:
                state['start_pos'] = (x, y)
                self.show_overlay(f"Dragging from ({x},{y})...")
            else:
                if state['start_pos']:
                    start = state['start_pos']
                    end = (x, y)

                    if target == 'keydoor':
                        self.keydoor_drag_start = start
                        self.keydoor_drag_end = end
                        self.config["keydoor_drag_start"] = list(start)
                        self.config["keydoor_drag_end"] = list(end)
                        self.keydoor_drag_var.set(f"({start[0]},{start[1]}) → ({end[0]},{end[1]})")
                        print(f"[KEYDOOR DRAG] Recorded: {start} → {end}")
                    else:
                        self.trig_drag_start = start
                        self.trig_drag_end = end
                        self.config["trig_drag_start"] = list(start)
                        self.config["trig_drag_end"] = list(end)
                        self.trig_drag_var.set(f"({start[0]},{start[1]}) → ({end[0]},{end[1]})")
                        print(f"[TRIG DRAG] Recorded: {start} → {end}")

                    save_config(self.config)
                    self.show_overlay(f"Saved! {start} → {end}")
                    return False  # Stop listener

        listener_ref[0] = mouse.Listener(on_click=on_click)
        listener_ref[0].start()

    def start_keydoor_drag_recording(self):
        """Record keydoor position or drag path depending on mode"""
        if self.use_drag_drop_var.get():
            self.show_overlay("10 sec - then click & drag item to drop zone")
            self._drag_countdown(10, 'keydoor', record_drag=True)
        else:
            self.show_overlay("10 sec - then click on item position")
            self._drag_countdown(10, 'keydoor', record_drag=False)

    def start_trig_drag_recording(self):
        """Record triggernade position or drag path depending on mode"""
        if self.use_drag_drop_var.get():
            self.show_overlay("10 sec - then click & drag item to drop zone")
            self._drag_countdown(10, 'triggernade', record_drag=True)
        else:
            self.show_overlay("10 sec - then click on item position")
            self._drag_countdown(10, 'triggernade', record_drag=False)

    def _drag_countdown(self, seconds_left, target, record_drag=True):
        if seconds_left > 0:
            self.show_overlay(f"Get ready... {seconds_left}")
            self.root.after(1000, lambda: self._drag_countdown(seconds_left - 1, target, record_drag))
        else:
            if record_drag:
                self._start_drag_position_listener(target)
            else:
                self._start_position_listener(target)

    def _start_position_listener(self, target):
        """Listen for single click to record position (for ViGEmBus mode)"""
        from pynput import mouse

        self.show_overlay("Click on item position NOW!")

        listener_ref = [None]

        def on_click(x, y, button, pressed):
            if button != mouse.Button.left:
                return
            if not pressed:  # On release
                x, y = int(x), int(y)
                pos = (x, y)

                if target == 'keydoor':
                    self.keydoor_slot_pos = pos
                    self.config["keydoor_slot_pos"] = list(pos)
                    self.keydoor_drag_var.set(f"Pos: ({x}, {y})")
                    print(f"[KEYDOOR POS] Recorded: {pos}")
                else:
                    self.trig_slot_pos = pos
                    self.config["trig_slot_pos"] = list(pos)
                    self.trig_drag_var.set(f"Pos: ({x}, {y})")
                    print(f"[TRIG POS] Recorded: {pos}")

                save_config(self.config)
                print(f"[CONFIG] Saved to: {CONFIG_FILE}")
                print(f"[CONFIG] keydoor_slot_pos = {self.config.get('keydoor_slot_pos')}")
                self.show_overlay(f"Position saved: ({x}, {y})")
                return False  # Stop listener

        listener_ref[0] = mouse.Listener(on_click=on_click)
        listener_ref[0].start()

    def start_slot_recording(self):
        """Record drop position - click where the item slot is"""
        self.slot_record_btn.config(text="3...")
        self._slot_countdown(3)

    def _slot_countdown(self, seconds_left):
        if seconds_left > 0:
            self.slot_record_btn.config(text=f"{seconds_left}...")
            self.show_overlay(f"Click slot in {seconds_left}...")
            self.root.after(1000, lambda: self._slot_countdown(seconds_left - 1))
        else:
            self._start_slot_listener()

    def _start_slot_listener(self):
        """Listen for click to record drop position"""
        from pynput import mouse

        self.slot_record_btn.config(text="CLICK!")
        self.show_overlay("CLICK ON SLOT!")

        def on_click(x, y, button, pressed):
            if button == mouse.Button.left and pressed:
                self.drag_start = (x, y)

                # Save to config
                self.config["drop_position"] = [x, y]
                save_config(self.config)

                self.root.after(0, lambda: self.slot_pos_var.set(f"({x}, {y})"))
                self.root.after(0, lambda: self.slot_record_btn.config(text="Record"))
                self.root.after(0, lambda: self.show_overlay(f"Position: ({x}, {y})"))
                print(f"[SLOT] Recorded drop position: ({x}, {y})")
                return False  # Stop listener

        listener = mouse.Listener(on_click=on_click)
        listener.start()

    def _update_um1_pos_display(self):
        """Update the Ammo position display"""
        self.um1_pos_var.set(f"Item:{self.um1_item_pos} Context:{self.um1_context_pos} Drag:{self.um1_drag_start}→{self.um1_drag_end}")

    def _start_um1_sequence_recording(self):
        """Start guided sequence recording for Ammo"""
        from pynput import mouse

        self.um1_record_seq_btn.config(text="Recording...")
        self.show_overlay("Step 1: RIGHT-CLICK on item")
        self._um1_record_step = 1
        self._um1_drag_started = False  # Track if drag press was captured

        def on_click(x, y, button, pressed):
            if self._um1_record_step == 1:
                # Step 1: Right click on item
                if pressed and button == mouse.Button.right:
                    self.um1_item_pos = (x, y)
                    self.config["um1_item_pos"] = [x, y]
                    self._um1_record_step = 2
                    self.root.after(0, lambda: self.show_overlay("Step 2: LEFT-CLICK context menu"))

            elif self._um1_record_step == 2:
                # Step 2: Left click on context menu (only capture press, ignore release)
                if pressed and button == mouse.Button.left:
                    self.um1_context_pos = (x, y)
                    self.config["um1_context_pos"] = [x, y]
                    self._um1_record_step = 3
                    self._um1_drag_started = False  # Reset - need a NEW press for drag
                    self.root.after(0, lambda: self.show_overlay("Step 3: DRAG item to slot"))

            elif self._um1_record_step == 3:
                # Step 3: Drag - capture start on press, end on release
                # Only process if it's a NEW click (not the release from step 2)
                if button == mouse.Button.left:
                    if pressed:
                        self.um1_drag_start = (x, y)
                        self.config["um1_drag_start"] = [x, y]
                        self._um1_drag_started = True  # Mark that we got a drag press
                        self.root.after(0, lambda: self.show_overlay("Now RELEASE to end drag"))
                    elif self._um1_drag_started:  # Only end if we captured a drag start
                        self.um1_drag_end = (x, y)
                        self.config["um1_drag_end"] = [x, y]
                        save_config(self.config)
                        self.root.after(0, self._update_um1_pos_display)
                        self.root.after(0, lambda: self.um1_record_seq_btn.config(text="Record Sequence"))
                        self.root.after(0, lambda: self.show_overlay("Sequence recorded!"))
                        return False  # Stop listener

        listener = mouse.Listener(on_click=on_click)
        listener.start()

    def start_recording_untitled1(self):
        """Start recording hotkey for Ammo"""
        self.recording_untitled1 = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_mine = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_minimize = False
        self.recording_tray = False
        self.untitled1_record_btn.config(text="...")
        self.untitled1_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_dc(self):
        self.recording_dc = True
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_minimize = False
        self.recording_tray = False
        self.dc_record_btn.config(text="...")
        self.dc_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_throwable(self):
        self.recording_throwable = True
        self.recording_dc = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_minimize = False
        self.recording_tray = False
        self.throwable_record_btn.config(text="...")
        self.throwable_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def on_key_press(self, event):
        if not self.recording_dc and not self.recording_throwable and not self.recording_triggernade and not self.recording_mine and not self.recording_espam and not self.recording_dc_both and not self.recording_dc_outbound and not self.recording_dc_inbound and not self.recording_tamper and not self.recording_minimize and not self.recording_tray and not self.recording_untitled1:
            return

        # Use keyboard library to check modifiers (tkinter state flags are unreliable)
        parts = []
        if keyboard.is_pressed('ctrl'):
            parts.append("ctrl")
        if keyboard.is_pressed('alt'):
            parts.append("alt")
        if keyboard.is_pressed('shift'):
            parts.append("shift")

        # Map tkinter keysyms to keyboard library key names
        tkinter_to_keyboard = {
            'next': 'page down',
            'prior': 'page up',
            'escape': 'esc',
            'return': 'enter',
            'control_l': 'ctrl',
            'control_r': 'ctrl',
            'alt_l': 'alt',
            'alt_r': 'alt',
            'shift_l': 'shift',
            'shift_r': 'shift',
            'caps_lock': 'caps lock',
            'num_lock': 'num lock',
            'scroll_lock': 'scroll lock',
            'print': 'print screen',
            'insert': 'insert',
            'delete': 'delete',
            'home': 'home',
            'end': 'end',
            'up': 'up',
            'down': 'down',
            'left': 'left',
            'right': 'right',
            'space': 'space',
            'tab': 'tab',
            'backspace': 'backspace',
            # Symbol keys
            'minus': '-',
            'plus': '+',
            'equal': '=',
            'bracketleft': '[',
            'bracketright': ']',
            'semicolon': ';',
            'apostrophe': "'",
            'grave': '`',
            'backslash': '\\',
            'comma': ',',
            'period': '.',
            'slash': '/',
            # Numpad
            'kp_subtract': '-',
            'kp_add': '+',
            'kp_multiply': '*',
            'kp_divide': '/',
            'kp_decimal': '.',
            'kp_enter': 'enter',
        }

        key = event.keysym.lower()
        key = tkinter_to_keyboard.get(key, key)  # Map if exists, otherwise use as-is

        # ESC clears the hotkey
        if key == 'esc':
            if self.recording_dc:
                self.dc_hotkey_var.set("")
                self.dc_record_btn.config(text="Set")
                self.recording_dc = False
            elif self.recording_throwable:
                self.throwable_hotkey_var.set("")
                self.throwable_record_btn.config(text="Set")
                self.recording_throwable = False
            elif self.recording_triggernade:
                self.triggernade_hotkey_var.set("")
                self.triggernade_record_btn.config(text="Set")
                self.recording_triggernade = False
            elif self.recording_mine:
                self.mine_hotkey_var.set("")
                self.mine_record_btn.config(text="Set")
                self.recording_mine = False
            elif self.recording_espam:
                self.espam_hotkey_var.set("")
                self.espam_record_btn.config(text="Set")
                self.recording_espam = False
            elif self.recording_untitled1:
                self.untitled1_hotkey_var.set("")
                self.untitled1_record_btn.config(text="Set")
                self.recording_untitled1 = False
            elif self.recording_dc_both:
                self.dc_both_hotkey_var.set("")
                self.dc_both_record_btn.config(text="Set")
                self.recording_dc_both = False
            elif self.recording_dc_outbound:
                self.dc_outbound_hotkey_var.set("")
                self.dc_outbound_record_btn.config(text="Set")
                self.recording_dc_outbound = False
            elif self.recording_dc_inbound:
                self.dc_inbound_hotkey_var.set("")
                self.dc_inbound_record_btn.config(text="Set")
                self.recording_dc_inbound = False
            elif self.recording_tamper:
                self.tamper_hotkey_var.set("")
                self.tamper_record_btn.config(text="Set")
                self.recording_tamper = False
            elif self.recording_minimize:
                self.minimize_hotkey_var.set("")
                self.minimize_record_btn.config(text="Set")
                self.recording_minimize = False
            elif self.recording_tray:
                self.tray_hotkey_var.set("")
                self.tray_record_btn.config(text="Set")
                self.recording_tray = False
            self.root.unbind("<KeyPress>")
            self.save_settings()
            self.register_hotkeys()
            return

        modifier_keys = ['ctrl', 'alt', 'shift', 'control_l', 'control_r', 'alt_l', 'alt_r', 'shift_l', 'shift_r', 'meta_l', 'meta_r']
        if key not in modifier_keys:
            parts.append(key)
            hotkey = "+".join(parts)

            # Clear this hotkey from any other action first
            all_hotkey_vars = [
                self.dc_hotkey_var,
                self.throwable_hotkey_var,
                self.triggernade_hotkey_var,
                self.mine_hotkey_var,
                self.espam_hotkey_var,
                self.dc_both_hotkey_var,
                self.dc_outbound_hotkey_var,
                self.dc_inbound_hotkey_var,
                self.tamper_hotkey_var,
                self.minimize_hotkey_var,
                self.tray_hotkey_var,
            ]
            for var in all_hotkey_vars:
                if var.get() == hotkey:
                    var.set("")

            if self.recording_dc:
                self.dc_hotkey_var.set(hotkey)
                self.dc_record_btn.config(text="Set")
                self.recording_dc = False
            elif self.recording_throwable:
                self.throwable_hotkey_var.set(hotkey)
                self.throwable_record_btn.config(text="Set")
                self.recording_throwable = False
            elif self.recording_triggernade:
                self.triggernade_hotkey_var.set(hotkey)
                self.triggernade_record_btn.config(text="Set")
                self.recording_triggernade = False
            elif self.recording_mine:
                self.mine_hotkey_var.set(hotkey)
                self.mine_record_btn.config(text="Set")
                self.recording_mine = False
            elif self.recording_espam:
                self.espam_hotkey_var.set(hotkey)
                self.espam_record_btn.config(text="Set")
                self.recording_espam = False
            elif self.recording_untitled1:
                self.untitled1_hotkey_var.set(hotkey)
                self.untitled1_record_btn.config(text="Set")
                self.recording_untitled1 = False
            elif self.recording_dc_both:
                self.dc_both_hotkey_var.set(hotkey)
                self.dc_both_record_btn.config(text="Set")
                self.recording_dc_both = False
            elif self.recording_dc_outbound:
                self.dc_outbound_hotkey_var.set(hotkey)
                self.dc_outbound_record_btn.config(text="Set")
                self.recording_dc_outbound = False
            elif self.recording_dc_inbound:
                self.dc_inbound_hotkey_var.set(hotkey)
                self.dc_inbound_record_btn.config(text="Set")
                self.recording_dc_inbound = False
            elif self.recording_tamper:
                self.tamper_hotkey_var.set(hotkey)
                self.tamper_record_btn.config(text="Set")
                self.recording_tamper = False
            elif self.recording_minimize:
                self.minimize_hotkey_var.set(hotkey)
                self.minimize_record_btn.config(text="Set")
                self.recording_minimize = False
            elif self.recording_tray:
                self.tray_hotkey_var.set(hotkey)
                self.tray_record_btn.config(text="Set")
                self.recording_tray = False
            self.root.unbind("<KeyPress>")
            self.save_settings()
            self.register_hotkeys()

    def toggle_stay_on_top(self):
        """Toggle window always-on-top setting"""
        stay_on_top = self.stay_on_top_var.get()
        self.root.attributes('-topmost', stay_on_top)
        self.save_settings()
        print(f"[UI] Stay on top: {stay_on_top}")

    def _reset_dc_buttons(self):
        """Reset all DC buttons to default state"""
        self.dc_both_btn.config(text="DC BOTH", bg='#3c3c3c')
        self.dc_outbound_btn.config(text="DC OUTBOUND", bg='#3c3c3c')
        self.dc_inbound_btn.config(text="DC INBOUND", bg='#3c3c3c')

    def toggle_dc_both(self):
        """Toggle disconnect both inbound + outbound"""
        if is_dropping():
            # Reconnect
            stop_packet_drop()
            self._reset_dc_buttons()
            self.root.after(0, lambda: self.show_overlay("RECONNECTED"))
        else:
            start_packet_drop(outbound=True, inbound=True)
            self._reset_dc_buttons()
            self.dc_both_btn.config(text="RECONNECT", bg='#e94560')
            self.root.after(0, lambda: self.show_overlay("DC BOTH"))

    def toggle_dc_outbound(self):
        """Toggle disconnect outbound only"""
        if is_dropping():
            # Reconnect
            stop_packet_drop()
            self._reset_dc_buttons()
            self.root.after(0, lambda: self.show_overlay("RECONNECTED"))
        else:
            start_packet_drop(outbound=True, inbound=False)
            self._reset_dc_buttons()
            self.dc_outbound_btn.config(text="RECONNECT", bg='#e94560')
            self.root.after(0, lambda: self.show_overlay("DC OUTBOUND"))

    def toggle_dc_inbound(self):
        """Toggle disconnect inbound only"""
        if is_dropping():
            # Reconnect
            stop_packet_drop()
            self._reset_dc_buttons()
            self.root.after(0, lambda: self.show_overlay("RECONNECTED"))
        else:
            start_packet_drop(outbound=False, inbound=True)
            self._reset_dc_buttons()
            self.dc_inbound_btn.config(text="RECONNECT", bg='#e94560')
            self.root.after(0, lambda: self.show_overlay("DC INBOUND"))

    def toggle_tamper(self):
        """Toggle packet tampering - corrupts packets but still sends them"""
        if self.tampering:
            stop_packet_tamper()
            self.tamper_btn.config(text="TAMPER", bg='#3c3c3c')
            self.tampering = False
            self.root.after(0, lambda: self.show_overlay("TAMPER OFF"))
        else:
            start_packet_tamper(outbound=True, inbound=True)
            self.tamper_btn.config(text="STOP TAMPER", bg='#ff8c00')
            self.tampering = True
            self.root.after(0, lambda: self.show_overlay("TAMPER ON"))

    def start_recording_dc_both(self):
        """Start recording hotkey for DC both"""
        self.recording_dc_both = True
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_mine = False
        self.recording_minimize = False
        self.recording_tray = False
        self.dc_both_record_btn.config(text="...")
        self.dc_both_hotkey_var.set("...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_dc_outbound(self):
        """Start recording hotkey for DC outbound"""
        self.recording_dc_outbound = True
        self.recording_dc_both = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_mine = False
        self.recording_minimize = False
        self.recording_tray = False
        self.dc_outbound_record_btn.config(text="...")
        self.dc_outbound_hotkey_var.set("...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_dc_inbound(self):
        """Start recording hotkey for DC inbound"""
        self.recording_dc_inbound = True
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_tamper = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_mine = False
        self.recording_minimize = False
        self.recording_tray = False
        self.dc_inbound_record_btn.config(text="...")
        self.dc_inbound_hotkey_var.set("...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_tamper(self):
        """Start recording hotkey for Tamper"""
        self.recording_tamper = True
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_mine = False
        self.recording_minimize = False
        self.recording_tray = False
        self.tamper_record_btn.config(text="...")
        self.tamper_hotkey_var.set("...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_minimize(self):
        """Start recording hotkey for minimize window"""
        self.recording_minimize = True
        self.recording_tray = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_mine = False
        self.minimize_record_btn.config(text="...")
        self.minimize_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_tray(self):
        """Start recording hotkey for minimize to tray"""
        self.recording_tray = True
        self.recording_minimize = False
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.recording_dc_both = False
        self.recording_dc_outbound = False
        self.recording_dc_inbound = False
        self.recording_tamper = False
        self.recording_mine = False
        self.tray_record_btn.config(text="...")
        self.tray_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def on_drag_drop_manual_toggle(self):
        """User manually toggled drag drop - remember their preference and update button text"""
        self.config["drag_drop_user_set"] = True  # User explicitly set this
        self._update_record_button_text()
        self.save_settings()

    def _update_record_button_text(self):
        """Update record button text and position displays based on drag drop mode"""
        use_drag = self.use_drag_drop_var.get()

        # Update keydoor display
        if use_drag:
            self.keydoor_drag_var.set(f"({self.keydoor_drag_start[0]},{self.keydoor_drag_start[1]}) → ({self.keydoor_drag_end[0]},{self.keydoor_drag_end[1]})")
        else:
            self.keydoor_drag_var.set(f"Pos: ({self.keydoor_slot_pos[0]},{self.keydoor_slot_pos[1]})")

        # Update triggernade display
        if use_drag:
            self.trig_drag_var.set(f"({self.trig_drag_start[0]},{self.trig_drag_start[1]}) → ({self.trig_drag_end[0]},{self.trig_drag_end[1]})")
        else:
            self.trig_drag_var.set(f"Pos: ({self.trig_slot_pos[0]},{self.trig_slot_pos[1]})")

        # Update mine display
        if use_drag:
            self.mine_drag_var.set(f"({self.mine_drag_start[0]},{self.mine_drag_start[1]}) → ({self.mine_drag_end[0]},{self.mine_drag_end[1]})")
        else:
            self.mine_drag_var.set(f"Pos: ({self.mine_slot_pos[0]},{self.mine_slot_pos[1]})")

    def auto_enable_drag_drop_if_no_vigembus(self):
        """Auto-enable drag drop if ViGEmBus failed, but only if user hasn't manually set preference"""
        if not self.config.get("drag_drop_user_set", False):
            # User hasn't manually set it, so auto-enable
            self.use_drag_drop_var.set(True)
            self.config["use_drag_drop"] = True
            save_config(self.config)
            print("[VIGEMBUS] Auto-enabled drag drop fallback")

    def save_settings(self):
        # Keydoor settings
        self.config["dc_hotkey"] = self.dc_hotkey_var.get()
        self.config["keydoor_x_hold"] = self.keydoor_x_hold_var.get()
        self.config["keydoor_tab_hold"] = self.keydoor_tab_hold_var.get()
        self.config["keydoor_wait_before_e"] = self.keydoor_wait_before_e_var.get()
        self.config["keydoor_espam_count"] = self.keydoor_espam_count_var.get()
        self.config["keydoor_e_hold"] = self.keydoor_e_hold_var.get()
        self.config["keydoor_e_delay"] = self.keydoor_e_delay_var.get()
        # Throwable settings
        self.config["throwable_hotkey"] = self.throwable_hotkey_var.get()
        self.config["throwable_repeat"] = self.throwable_repeat_var.get()
        self.config["throw_hold_time"] = self.throw_hold_time_var.get()
        self.config["throw_dc_delay_before"] = self.throw_dc_delay_before_var.get()
        self.config["throw_wait_before_e"] = self.throw_wait_before_e_var.get()
        self.config["throw_e_hold"] = self.throw_e_hold_var.get()
        self.config["throw_double_e"] = self.throw_double_e_var.get()
        self.config["throw_e_gap"] = self.throw_e_gap_var.get()
        self.config["throw_e2_hold"] = self.throw_e2_hold_var.get()
        self.config["throw_wait_after_e"] = self.throw_wait_after_e_var.get()
        self.config["throw_wait_after_q"] = self.throw_wait_after_q_var.get()
        self.config["throw_dc_count"] = self.throw_dc_count_var.get()
        self.config["throw_dc_delay"] = self.throw_dc_delay_var.get()
        # Triggernade settings
        self.config["triggernade_hotkey"] = self.triggernade_hotkey_var.get()
        self.config["triggernade_repeat"] = self.triggernade_repeat_var.get()
        self.config["triggernade_q_spam"] = self.triggernade_q_spam_var.get()
        self.config["espam_hotkey"] = self.espam_hotkey_var.get()
        self.config["wait_before_espam"] = self.wait_before_espam_var.get()
        self.config["espam_duration"] = self.espam_duration_var.get()
        self.config["wait_before_cycle"] = self.wait_before_cycle_var.get()
        self.config["trig_dc_throws"] = self.trig_dc_throws_var.get()
        self.config["trig_throw_delay"] = self.trig_throw_delay_var.get()
        self.config["trig_reconnect_after"] = self.trig_reconnect_after_var.get()
        self.config["trig_m1_hold"] = self.trig_m1_hold_var.get()
        self.config["trig_m2_hold"] = self.trig_m2_hold_var.get()
        self.config["trig_dc_delay"] = self.trig_dc_delay_var.get()
        # Mine settings
        self.config["mine_hotkey"] = self.mine_hotkey_var.get()
        self.config["mine_repeat"] = self.mine_repeat_var.get()
        self.config["mine_cook"] = self.mine_cook_var.get()
        self.config["mine_dc_delay"] = self.mine_dc_delay_var.get()
        self.config["mine_x_hold"] = self.mine_x_hold_var.get()
        self.config["mine_click_delay"] = self.mine_click_delay_var.get()
        self.config["mine_pickup_hold"] = self.mine_pickup_hold_var.get()
        self.config["mine_e_delay"] = self.mine_e_delay_var.get()
        self.config["mine_loop_delay"] = self.mine_loop_delay_var.get()
        # E-spam settings
        self.config["espam_hold_mode"] = self.espam_hold_mode_var.get()
        self.config["espam_repeat_delay"] = self.espam_repeat_delay_var.get()
        # Ammo settings
        self.config["untitled1_hotkey"] = self.untitled1_hotkey_var.get()
        self.config["untitled1_repeat"] = self.untitled1_repeat_var.get()
        # Quick disconnect hotkeys
        self.config["dc_both_hotkey"] = self.dc_both_hotkey_var.get()
        self.config["dc_outbound_hotkey"] = self.dc_outbound_hotkey_var.get()
        self.config["dc_inbound_hotkey"] = self.dc_inbound_hotkey_var.get()
        self.config["tamper_hotkey"] = self.tamper_hotkey_var.get()
        # General settings
        self.config["stay_on_top"] = self.stay_on_top_var.get()
        self.config["show_overlay"] = self.show_overlay_var.get()
        self.config["timing_variance"] = self.timing_variance_var.get()
        self.config["use_drag_drop"] = self.use_drag_drop_var.get()
        # Window hotkeys
        self.config["minimize_hotkey"] = self.minimize_hotkey_var.get()
        self.config["tray_hotkey"] = self.tray_hotkey_var.get()
        save_config(self.config)

    def reset_keydoor_defaults(self):
        """Reset all keydoor timing parameters to defaults"""
        self.keydoor_x_hold_var.set(1250)
        self.keydoor_tab_hold_var.set(21)
        self.keydoor_wait_before_e_var.set(73)
        self.keydoor_espam_count_var.set(30)
        self.keydoor_e_hold_var.set(13)
        self.keydoor_e_delay_var.set(12)
        # Reset positions
        self.keydoor_slot_pos = (3024, 669)
        self.keydoor_drag_start = (3024, 669)
        self.keydoor_drag_end = (550, 1247)
        self.config["keydoor_slot_pos"] = [3024, 669]
        self.config["keydoor_drag_start"] = [3024, 669]
        self.config["keydoor_drag_end"] = [550, 1247]
        self._update_record_button_text()
        self.save_settings()
        print("[RESET] Keydoor parameters reset to defaults")

    def reset_throwable_defaults(self):
        """Reset all throwable timing parameters to defaults"""
        self.throw_hold_time_var.set(45)
        self.throw_dc_delay_before_var.set(40)
        self.throw_wait_before_e_var.set(200)
        self.throw_e_hold_var.set(50)
        self.throw_double_e_var.set(False)
        self.throw_e_gap_var.set(200)
        self.throw_e2_hold_var.set(50)
        self.throw_wait_after_e_var.set(100)
        self.throw_wait_after_q_var.set(750)
        self.throw_dc_count_var.set(12)
        self.throw_dc_delay_var.set(86)
        self.save_settings()
        print("[RESET] Throwable parameters reset to defaults")

    def reset_triggernade_defaults(self):
        """Reset all triggernade timing parameters to defaults (from working recording)"""
        self.wait_before_espam_var.set(0)  # E spam starts during M1 spam (interleaved)
        self.espam_duration_var.set(1000)  # ~1 second of E spam
        self.wait_before_cycle_var.set(100)
        self.trig_dc_throws_var.set(10)  # 10 M1s after reconnect
        self.trig_throw_delay_var.set(100)  # ~100ms between M1s
        self.trig_reconnect_after_var.set(1)  # Reconnect after first M1
        self.trig_m1_hold_var.set(65)  # Hold M1 65ms before M2
        self.trig_m2_hold_var.set(51)  # Hold M2 for 51ms
        self.trig_dc_delay_var.set(10)  # Delay before DC
        self.trig_m1_before_interweave_var.set(5)  # 5 M1s before E interweave
        self.triggernade_q_spam_var.set(True)  # Q spam enabled by default
        # Reset positions
        self.trig_slot_pos = (3024, 669)
        self.trig_drag_start = (3024, 669)
        self.trig_drag_end = (550, 1247)
        self.config["trig_slot_pos"] = [3024, 669]
        self.config["trig_drag_start"] = [3024, 669]
        self.config["trig_drag_end"] = [550, 1247]
        self._update_record_button_text()
        self.save_settings()
        print("[RESET] Triggernade parameters reset to defaults")

    def reset_mine_defaults(self):
        """Reset all mine dupe timing parameters to defaults"""
        self.mine_cook_var.set(980)
        self.mine_dc_delay_var.set(50)
        self.mine_x_hold_var.set(817)
        self.mine_click_delay_var.set(50)
        self.mine_pickup_hold_var.set(1800)
        self.mine_e_delay_var.set(80)
        self.mine_loop_delay_var.set(800)
        # Reset positions
        self.mine_slot_pos = (2966, 1196)
        self.mine_drag_start = (2966, 1196)
        self.mine_drag_end = (1035, 1291)
        self.config["mine_slot_pos"] = [2966, 1196]
        self.config["mine_drag_start"] = [2966, 1196]
        self.config["mine_drag_end"] = [1035, 1291]
        self._update_record_button_text()
        self.save_settings()
        print("[RESET] Mine dupe parameters reset to defaults")

    def reset_untitled1_defaults(self):
        """Reset Ammo timing parameters to defaults"""
        self.um1_tab_hold_var.set(30)
        self.um1_after_tab_open_var.set(50)
        self.um1_rclick_hold_var.set(30)
        self.um1_after_rclick_var.set(50)
        self.um1_after_dc_var.set(20)
        self.um1_context_hold_var.set(30)
        self.um1_after_context_var.set(50)
        self.um1_after_reconnect_var.set(50)
        self.um1_dblclick_hold_var.set(20)
        self.um1_dblclick_gap_var.set(15)
        self.um1_after_dblclick_var.set(59)
        self.um1_after_tab_close_var.set(61)
        self.um1_equip_hold_var.set(67)
        self.um1_loop_delay_var.set(300)
        # Reset positions
        self.um1_item_pos = (1777, 975)
        self.um1_context_pos = (1928, 1389)
        self.um1_drag_start = (1693, 990)
        self.um1_drag_end = (2268, 1150)
        self.config["um1_item_pos"] = [1777, 975]
        self.config["um1_context_pos"] = [1928, 1389]
        self.config["um1_drag_start"] = [1693, 990]
        self.config["um1_drag_end"] = [2268, 1150]
        self._update_um1_pos_display()
        self.save_settings()
        print("[RESET] Ammo parameters reset to defaults")

    def reset_all_settings(self):
        """Reset ALL settings including hotkeys and recordings to factory defaults"""
        import tkinter.messagebox as mb
        if not mb.askyesno("Reset All Settings", "This will reset EVERYTHING including:\n\n• All hotkeys\n• All timing settings\n• All recorded positions\n• Drag drop preference\n\nAre you sure?"):
            return

        # Clear config file completely
        self.config = {}
        save_config(self.config)

        # Reset all hotkeys
        self.dc_hotkey_var.set("")
        self.throwable_hotkey_var.set("")
        self.triggernade_hotkey_var.set("")
        self.espam_hotkey_var.set("")
        self.dc_both_hotkey_var.set("")
        self.dc_outbound_hotkey_var.set("")
        self.dc_inbound_hotkey_var.set("")
        self.tamper_hotkey_var.set("")

        # Reset checkboxes
        self.use_drag_drop_var.set(False)
        self.show_overlay_var.set(True)
        self.stay_on_top_var.set(False)
        self.throwable_repeat_var.set(True)
        self.triggernade_repeat_var.set(True)

        # Reset all timing sliders and positions (these call _update_record_button_text)
        self.reset_keydoor_defaults()
        self.reset_throwable_defaults()
        self.reset_triggernade_defaults()
        self.reset_mine_defaults()

        # Re-register hotkeys (will be empty now)
        self.register_hotkeys()

        print("[RESET] ALL settings reset to factory defaults")
        self.show_overlay("All settings reset!")

    def register_hotkeys(self):
        # Clear ALL hooks first to prevent ghost hotkeys (including on_press_key hooks)
        try:
            keyboard.unhook_all()
            print("[HOTKEY] Cleared all previous hotkeys and hooks")
        except Exception as e:
            print(f"[HOTKEY] Error clearing hotkeys: {e}")

        self.dc_hotkey_registered = None
        self.throwable_hotkey_registered = None
        self.triggernade_hotkey_registered = None
        self.espam_hotkey_registered = None
        self.escape_hotkey_registered = None
        self.dc_both_hotkey_registered = None
        self.dc_outbound_hotkey_registered = None
        self.dc_inbound_hotkey_registered = None
        self.tamper_hotkey_registered = None
        self.mine_hotkey_registered = None
        self.minimize_hotkey_registered = None
        self.tray_hotkey_registered = None

        # Register ALL hotkeys
        dc_hk = self.dc_hotkey_var.get()
        throw_hk = self.throwable_hotkey_var.get()
        trig_hk = self.triggernade_hotkey_var.get()
        espam_hk = self.espam_hotkey_var.get()

        print(f"[HOTKEY] Registering hotkeys: keydoor='{dc_hk}', throwable='{throw_hk}', triggernade='{trig_hk}', espam='{espam_hk}'")

        if dc_hk and dc_hk != "Press key...":
            try:
                self.dc_hotkey_registered = keyboard.add_hotkey(dc_hk, self.on_dc_hotkey, suppress=False)
                print(f"[HOTKEY] Keydoor registered OK: '{dc_hk}' -> {self.dc_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED keydoor '{dc_hk}': {e}")

        if throw_hk and throw_hk != "Press key...":
            try:
                self.throwable_hotkey_registered = keyboard.add_hotkey(throw_hk, self.on_throwable_hotkey, suppress=False)
                print(f"[HOTKEY] Throwable registered OK: '{throw_hk}' -> {self.throwable_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED throwable '{throw_hk}': {e}")

        if trig_hk and trig_hk != "Press key...":
            try:
                self.triggernade_hotkey_registered = keyboard.add_hotkey(trig_hk, self.on_triggernade_hotkey, suppress=False)
                print(f"[HOTKEY] Triggernade registered OK: '{trig_hk}' -> {self.triggernade_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED triggernade '{trig_hk}': {e}")

        if espam_hk and espam_hk != "Press key...":
            try:
                self.espam_hotkey_registered = keyboard.add_hotkey(espam_hk, self.on_espam_hotkey, suppress=False)
                print(f"[HOTKEY] E-Spam registered OK: '{espam_hk}' -> {self.espam_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED espam '{espam_hk}': {e}")

        mine_hk = self.mine_hotkey_var.get()
        if mine_hk and mine_hk != "Press key...":
            try:
                self.mine_hotkey_registered = keyboard.add_hotkey(mine_hk, self.on_mine_hotkey, suppress=False)
                print(f"[HOTKEY] Mine registered OK: '{mine_hk}' -> {self.mine_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED mine '{mine_hk}': {e}")

        untitled1_hk = self.untitled1_hotkey_var.get()
        if untitled1_hk and untitled1_hk != "Press key...":
            try:
                self.untitled1_hotkey_registered = keyboard.add_hotkey(untitled1_hk, self.on_untitled1_hotkey, suppress=False)
                print(f"[HOTKEY] Untitled1 registered OK: '{untitled1_hk}' -> {self.untitled1_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED untitled1 '{untitled1_hk}': {e}")

        # Register quick disconnect hotkeys (use on_press_key so they work while other keys held)
        dc_both_hk = self.dc_both_hotkey_var.get()
        if dc_both_hk and dc_both_hk != "Press key..." and dc_both_hk != "...":
            try:
                self.dc_both_hotkey_registered = keyboard.on_press_key(dc_both_hk, lambda e: self.toggle_dc_both(), suppress=False)
                print(f"[HOTKEY] DC Both registered OK: '{dc_both_hk}' -> {self.dc_both_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED dc_both '{dc_both_hk}': {e}")

        dc_outbound_hk = self.dc_outbound_hotkey_var.get()
        if dc_outbound_hk and dc_outbound_hk != "Press key..." and dc_outbound_hk != "...":
            try:
                self.dc_outbound_hotkey_registered = keyboard.on_press_key(dc_outbound_hk, lambda e: self.toggle_dc_outbound(), suppress=False)
                print(f"[HOTKEY] DC Outbound registered OK: '{dc_outbound_hk}' -> {self.dc_outbound_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED dc_outbound '{dc_outbound_hk}': {e}")

        dc_inbound_hk = self.dc_inbound_hotkey_var.get()
        if dc_inbound_hk and dc_inbound_hk != "Press key..." and dc_inbound_hk != "...":
            try:
                self.dc_inbound_hotkey_registered = keyboard.on_press_key(dc_inbound_hk, lambda e: self.toggle_dc_inbound(), suppress=False)
                print(f"[HOTKEY] DC Inbound registered OK: '{dc_inbound_hk}' -> {self.dc_inbound_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED dc_inbound '{dc_inbound_hk}': {e}")

        tamper_hk = self.tamper_hotkey_var.get()
        if tamper_hk and tamper_hk != "Press key..." and tamper_hk != "...":
            try:
                self.tamper_hotkey_registered = keyboard.on_press_key(tamper_hk, lambda e: self.toggle_tamper(), suppress=False)
                print(f"[HOTKEY] Tamper registered OK: '{tamper_hk}' -> {self.tamper_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED tamper '{tamper_hk}': {e}")

        # Register minimize hotkey
        min_hk = self.minimize_hotkey_var.get()
        if min_hk and min_hk != "Press key...":
            try:
                self.minimize_hotkey_registered = keyboard.add_hotkey(min_hk, self.minimize_window, suppress=False)
                print(f"[HOTKEY] Minimize registered OK: '{min_hk}' -> {self.minimize_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED minimize '{min_hk}': {e}")

        # Register minimize to tray hotkey
        tray_hk = self.tray_hotkey_var.get()
        if tray_hk and tray_hk != "Press key...":
            try:
                self.tray_hotkey_registered = keyboard.add_hotkey(tray_hk, self.minimize_to_tray, suppress=False)
                print(f"[HOTKEY] Tray registered OK: '{tray_hk}' -> {self.tray_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED tray '{tray_hk}': {e}")

        # Always register Escape as universal stop
        try:
            self.escape_hotkey_registered = keyboard.add_hotkey('esc', self.stop_all_macros, suppress=False)
            print(f"[HOTKEY] Escape (stop all) registered OK: {self.escape_hotkey_registered}")
        except Exception as e:
            print(f"[HOTKEY] FAILED escape: {e}")

    def stop_all_macros(self):
        """Universal stop - triggered by Escape"""
        print("[HOTKEY] ESCAPE pressed - stopping all macros!")
        self.keydoor_stop = True
        self.throwable_stop = True
        self.triggernade_stop = True
        self.espam_stop = True
        self.mine_stop = True
        self.untitled1_stop = True
        self.root.after(0, lambda: self.show_overlay("All macros stopped!"))

    def on_dc_hotkey(self):
        """Run keydoor macro (runs once)"""
        print("[HOTKEY] Keydoor hotkey PRESSED!")
        if self.keydoor_running:
            # Already running, stop it
            self.keydoor_stop = True
            print("[HOTKEY] Stopping keydoor...")
            return

        self.keydoor_stop = False
        self.keydoor_running = True
        # Use root.after to update UI from main thread
        self.root.after(0, lambda: self.dc_status_var.set("RUNNING"))
        self.root.after(0, lambda: self.dc_status_label.config(foreground="orange"))
        self.root.after(0, lambda: self.show_overlay("Keydoor running..."))
        threading.Thread(target=self.run_keydoor_macro, daemon=True).start()

    def run_keydoor_macro(self):
        """
        Keydoor macro (configurable timings):
        1. Disconnect
        2. Hold Xbox X button (drops key)
        3. TAB to exit inventory
        4. Start E spam, reconnect almost immediately
        5. Continue E spam after reconnect
        """
        is_disconnected = False
        gp = get_gamepad()

        # Only require gamepad if NOT using drag drop
        if gp is None and not self.use_drag_drop_var.get():
            print("[KEYDOOR] Skipping - ViGEmBus not installed (enable drag drop or install ViGEmBus)")
            self.root.after(0, lambda: self.dc_status_var.set("ERROR: Install ViGEmBus"))
            self.root.after(0, lambda: self.dc_status_label.config(foreground="red"))
            self.keydoor_running = False
            return

        # Get configurable values
        x_hold_ms = self.keydoor_x_hold_var.get()
        tab_hold_ms = self.keydoor_tab_hold_var.get()
        wait_before_e_ms = self.keydoor_wait_before_e_var.get()
        espam_count = self.keydoor_espam_count_var.get()
        e_hold_ms = self.keydoor_e_hold_var.get()
        e_delay_ms = self.keydoor_e_delay_var.get()

        # ===== Disconnect FIRST =====
        print("[KEYDOOR] Disconnecting...")
        start_packet_drop()
        is_disconnected = True

        # ===== Drop item (Xbox X or drag fallback) =====
        print(f"[KEYDOOR] use_drag_drop_var = {self.use_drag_drop_var.get()}")
        if self.use_drag_drop_var.get():
            # Drag fallback using pynput - need to open inventory first
            print(f"[KEYDOOR] Opening inventory...")
            pynput_keyboard.press(Key.tab)
            self.vsleep(300)
            pynput_keyboard.release(Key.tab)
            self.vsleep(120)

            print(f"[KEYDOOR] Using drag drop: {self.keydoor_drag_start} → {self.keydoor_drag_end}")

            # Clear any stuck mouse state first
            pynput_mouse.release(MouseButton.left)

            # Move to start position
            pynput_mouse.position = self.keydoor_drag_start
            self.vsleep(30)

            # Press and drag
            pynput_mouse.press(MouseButton.left)
            self.vsleep(80)  # Click registers

            # Smooth drag - 20 steps over ~150ms
            start_x, start_y = self.keydoor_drag_start
            end_x, end_y = self.keydoor_drag_end
            dx = end_x - start_x
            dy = end_y - start_y
            steps = 20
            for i in range(1, steps + 1):
                t = i / steps
                x = int(start_x + dx * t)
                y = int(start_y + dy * t)
                pynput_mouse.position = (x, y)
                self.vsleep(7)

            pynput_mouse.release(MouseButton.left)
            print(f"[KEYDOOR] Drag complete")
        else:
            # Xbox X button - move to recorded slot position first
            print(f"[KEYDOOR] Moving to {self.keydoor_slot_pos}, holding X for {x_hold_ms}ms")
            pynput_mouse.position = self.keydoor_slot_pos
            self.vsleep(20)
            gp.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
            gp.update()

            # Hold for configured time (cancelable)
            t = 0
            while t < x_hold_ms:
                if self.keydoor_stop:
                    gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                    gp.update()
                    self.finish_keydoor(is_disconnected)
                    return
                self.vsleep(10)
                t += 10

            gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
            gp.update()
            print("[KEYDOOR] X released - key should be dropped")

        if self.keydoor_stop:
            self.finish_keydoor(is_disconnected)
            return

        # TAB to exit inventory
        pynput_keyboard.press(Key.tab)
        self.vsleep(tab_hold_ms)
        pynput_keyboard.release(Key.tab)
        self.vsleep(wait_before_e_ms)
        print("[KEYDOOR] TAB - exited inventory")

        if self.keydoor_stop:
            self.finish_keydoor(is_disconnected)
            return

        # ===== E spam - reconnect after just 1 press =====
        print("[KEYDOOR] Starting E spam...")
        pynput_keyboard.press('e')
        self.vsleep(e_hold_ms)
        pynput_keyboard.release('e')
        self.vsleep(7)

        # ===== Reconnect almost immediately =====
        print("[KEYDOOR] Reconnecting...")
        stop_packet_drop()
        is_disconnected = False

        # ===== Continue E spam after reconnect =====
        print(f"[KEYDOOR] Spamming E {espam_count}x...")
        for i in range(espam_count):
            if self.keydoor_stop:
                break
            pynput_keyboard.press('e')
            self.vsleep(e_hold_ms)
            pynput_keyboard.release('e')
            self.vsleep(e_delay_ms)

        # Done
        print("[KEYDOOR] Done!")
        self.finish_keydoor(is_disconnected)

    def finish_keydoor(self, is_disconnected):
        """Clean up keydoor macro"""
        if is_disconnected:
            stop_packet_drop()
        self.keydoor_running = False
        self.keydoor_stop = False
        # Use root.after to update UI from main thread
        self.root.after(0, lambda: self.dc_status_var.set("Ready"))
        self.root.after(0, lambda: self.dc_status_label.config(foreground="gray"))
        self.root.after(0, lambda: self.show_overlay("Keydoor done."))

    def on_throwable_hotkey(self):
        """Toggle throwable macro"""
        print(f"[HOTKEY] Throwable hotkey PRESSED! running={self.throwable_running}")
        if self.throwable_running:
            # Stop it
            print("[HOTKEY] Setting throwable_stop = True")
            self.throwable_stop = True
            self.root.after(0, lambda: self.throwable_status_var.set("Stopping..."))
        else:
            # Start it
            print("[HOTKEY] Starting throwable macro")
            self.throwable_stop = False
            self.throwable_running = True
            self.root.after(0, lambda: self.throwable_status_var.set("RUNNING"))
            self.root.after(0, lambda: self.throwable_status_label.config(foreground="orange"))
            self.root.after(0, lambda: self.show_overlay("Throwable running..."))
            threading.Thread(target=self.run_throwable_macro, daemon=True).start()

    def run_throwable_macro(self):
        """
        Throwable dupe macro - EXACT match to GHUB Lua script
        """
        repeat = self.throwable_repeat_var.get()
        is_disconnected = False
        cycle = 0

        # Equip throwable first (not in original but needed for first cycle)
        print("[PREP] Q to equip throwable")
        pynput_keyboard.press('q')
        self.vsleep(10)
        pynput_keyboard.release('q')
        self.vsleep(500)
        print("[PREP] Done, starting loop")

        try:
            while True:
                cycle += 1
                cycle_start = time.perf_counter()
                print(f"\n=== CYCLE {cycle} ===")

                # ===== Initial throw =====
                throw_hold = self.throw_hold_time_var.get()
                dc_delay = self.throw_dc_delay_before_var.get()

                self.vsleep(5)
                pynput_mouse.press(MouseButton.left)
                self.vsleep(throw_hold)
                pynput_mouse.release(MouseButton.left)
                print(f"[{cycle}] Throw done (held {throw_hold}ms)")

                # ===== Delay before disconnect =====
                if dc_delay > 0:
                    self.vsleep(dc_delay)
                    print(f"[{cycle}] Waited {dc_delay}ms before DC")

                start_packet_drop()
                is_disconnected = True
                print(f"[{cycle}] Disconnected")

                # ===== Spam M1 while disconnected (configurable) =====
                throw_count = self.throw_dc_count_var.get()
                base_delay = self.throw_dc_delay_var.get()
                # Generate balanced varied delays (total stays same)
                varied_delays = self.vary_balanced(base_delay, throw_count)
                print(f"[{cycle}] Throwing {throw_count}x with ~{base_delay}ms between (variance applied)")
                for i in range(throw_count):
                    if self.throwable_stop:
                        break
                    delay = varied_delays[i] / 2  # Split between down and up
                    pynput_mouse.press(MouseButton.left)
                    self.vsleep(delay)
                    pynput_mouse.release(MouseButton.left)
                    self.vsleep(delay)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED during M1 spam")
                    break

                # ===== Reconnect (GHUB: press, Sleep10, release) =====
                stop_packet_drop()
                is_disconnected = False
                print(f"[{cycle}] Reconnected")

                # ===== Spam M1 x8 after reconnect (GHUB: 50ms down, 50ms up) =====
                spam2_start = time.perf_counter()
                for i in range(1):
                    if self.throwable_stop:
                        break
                    pynput_mouse.press(MouseButton.left)
                    self.vsleep(50)
                    pynput_mouse.release(MouseButton.left)
                    self.vsleep(50)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED during M1 spam after reconnect")
                    break

                # ===== Wait before E (configurable) =====
                wait_before_e_ms = self.throw_wait_before_e_var.get()
                wait_after_e_ms = self.throw_wait_after_e_var.get()
                wait_after_q_ms = self.throw_wait_after_q_var.get()

                print(f"[{cycle}] Waiting ~{wait_before_e_ms}ms before E...")
                self.vsleep(wait_before_e_ms)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED before E")
                    break

                # ===== E (pickup / disarm) =====
                e_hold_ms = self.throw_e_hold_var.get()
                pynput_keyboard.press('e')
                self.vsleep(e_hold_ms)
                pynput_keyboard.release('e')
                print(f"[{cycle}] E held {e_hold_ms}ms")

                # Second E press if double E enabled (for fuel canisters: disarm then pickup)
                if self.throw_double_e_var.get():
                    e_gap_ms = self.throw_e_gap_var.get()
                    self.vsleep(e_gap_ms)  # Configurable gap between presses
                    e2_hold_ms = self.throw_e2_hold_var.get()
                    pynput_keyboard.press('e')
                    self.vsleep(e2_hold_ms)
                    pynput_keyboard.release('e')
                    print(f"[{cycle}] 2nd E held {e2_hold_ms}ms")

                print(f"[{cycle}] Waiting ~{wait_after_e_ms}ms after E...")
                self.vsleep(wait_after_e_ms)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED before Q")
                    break

                # ===== Q (re-equip) =====
                pynput_keyboard.press('q')
                self.vsleep(50)
                pynput_keyboard.release('q')
                # Add extra loop variance (scales with variance slider - more extreme)
                variance_pct = self.timing_variance_var.get()
                extra_loop_var = random.uniform(0, variance_pct * 10) if variance_pct > 0 else 0
                loop_wait = wait_after_q_ms + extra_loop_var
                print(f"[{cycle}] Q pressed, waiting {loop_wait:.0f}ms before next cycle...")
                self.vsleep(loop_wait)

                cycle_time = (time.perf_counter() - cycle_start) * 1000
                print(f"[{cycle}] CYCLE DONE in {cycle_time:.0f}ms")

                if not repeat or self.throwable_stop:
                    break
        finally:
            # ALWAYS ensure reconnected when stopped
            if is_disconnected:
                stop_packet_drop()
            # Done
            self.throwable_running = False
            self.throwable_stop = False
            self.root.after(0, lambda: self.throwable_status_var.set("Ready"))
            self.root.after(0, lambda: self.throwable_status_label.config(foreground="gray"))
            self.root.after(0, lambda: self.show_overlay("Throwable stopped."))

    def on_triggernade_hotkey(self):
        """Toggle triggernade macro"""
        print(f"[HOTKEY] Triggernade hotkey PRESSED! running={self.triggernade_running}")
        if self.triggernade_running:
            print("[HOTKEY] Setting triggernade_stop = True")
            self.triggernade_stop = True
            self.root.after(0, lambda: self.triggernade_status_var.set("Stopping..."))
        else:
            print("[HOTKEY] Starting triggernade macro")
            self.triggernade_stop = False
            self.triggernade_running = True
            self.root.after(0, lambda: self.triggernade_status_var.set("RUNNING"))
            self.root.after(0, lambda: self.triggernade_status_label.config(foreground="orange"))
            self.root.after(0, lambda: self.show_overlay("Wolfpack/Triggernade started"))
            threading.Thread(target=self.run_triggernade_macro, daemon=True).start()

    def run_triggernade_macro(self):
        """
        Triggernade dupe macro - from recording
        Drag coordinates are for user's resolution - may need adjustment
        """
        repeat = self.triggernade_repeat_var.get()
        is_disconnected = False
        cycle = 0

        print(f"[TRIGGERNADE] Using positions: {self.trig_drag_start} → {self.trig_drag_end}")

        # Release ALL buttons and keys before starting
        pynput_mouse.release(MouseButton.left)
        pynput_mouse.release(MouseButton.left)
        pynput_mouse.release(MouseButton.right)
        pynput_keyboard.release('e')
        pynput_keyboard.release('q')
        pynput_keyboard.release(Key.tab)

        # Get the hotkey for direct checking
        hotkey = self.triggernade_hotkey_var.get()

        # Brief delay so starting hotkey doesn't trigger stop
        time.sleep(0.2)

        try:
            while True:
                # Check stop flag AND direct key press as backup
                if self.triggernade_stop:
                    print("[TRIGGERNADE] Stop detected at cycle start")
                    break
                if hotkey and keyboard.is_pressed(hotkey):
                    print("[TRIGGERNADE] Hotkey pressed directly - stopping")
                    self.triggernade_stop = True
                    break

                cycle += 1
                import random

                # Print params at start
                print(f"\n{'='*50}")
                print(f"RUN {cycle}")
                print(f"{'='*50}")

                self.root.after(0, lambda c=cycle: self.show_overlay(f"Run {c}"))

                # ===== Left click throw (configurable) =====
                m1_hold = self.trig_m1_hold_var.get()
                m2_hold = self.trig_m2_hold_var.get()

                pynput_mouse.press(MouseButton.left)
                self.vsleep(m1_hold)

                # ===== Right click during throw (configurable) =====
                pynput_mouse.press(MouseButton.right)
                self.vsleep(m2_hold)
                pynput_mouse.release(MouseButton.right)
                print(f"[{cycle}] Throw (M1:{m1_hold}ms) + M2:{m2_hold}ms")

                pynput_mouse.release(MouseButton.left)

                # ===== E key 11ms =====
                pynput_keyboard.press('e')
                self.vsleep(11)
                pynput_keyboard.release('e')
                print(f"[{cycle}] E pressed")

                # ===== Delay before disconnect =====
                dc_delay = self.trig_dc_delay_var.get()
                if dc_delay > 0:
                    self.vsleep(dc_delay)

                # ===== Disconnect (outbound only for triggernade) =====
                start_packet_drop(inbound=False)
                is_disconnected = True
                self.vsleep(51)
                print(f"[{cycle}] Disconnected (outbound only)")

                if self.triggernade_stop:
                    break

                # ===== TAB to open inventory 51ms =====
                self.vsleep(20)
                pynput_keyboard.press(Key.tab)
                self.vsleep(301)
                pynput_keyboard.release(Key.tab)
                print(f"[{cycle}] Inventory opened")

                if self.triggernade_stop:
                    break

                # ===== Wait then drop (uses recorded timing) =====
                if self.use_drag_drop_var.get():
                    # Drag fallback using pynput
                    self.vsleep(120)  # Wait for inventory to open

                    # Clear any stuck mouse state first
                    pynput_mouse.release(MouseButton.left)

                    # Move to start position
                    pynput_mouse.position = self.trig_drag_start
                    self.vsleep(30)

                    # Press and drag
                    pynput_mouse.press(MouseButton.left)
                    self.vsleep(80)  # Click registers

                    # Smooth drag - 20 steps over ~150ms
                    start_x, start_y = self.trig_drag_start
                    end_x, end_y = self.trig_drag_end
                    dx = end_x - start_x
                    dy = end_y - start_y
                    steps = 20
                    for i in range(1, steps + 1):
                        t = i / steps
                        x = int(start_x + dx * t)
                        y = int(start_y + dy * t)
                        pynput_mouse.position = (x, y)
                        self.vsleep(7)

                    pynput_mouse.release(MouseButton.left)
                    print(f"[{cycle}] Dropped with drag: {self.trig_drag_start} → {self.trig_drag_end}")
                else:
                    # Xbox X button - uses original hardcoded timing
                    self.vsleep(300)  # Wait before drop
                    x_hold_ms = self.keydoor_x_hold_var.get()
                    pynput_mouse.position = self.trig_slot_pos
                    self.vsleep(20)
                    gp = get_gamepad()
                    if gp:
                        gp.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                        gp.update()
                        self.vsleep(x_hold_ms)
                        gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                        gp.update()
                        print(f"[{cycle}] Dropped with X ({x_hold_ms}ms)")
                    else:
                        print(f"[{cycle}] ERROR: No gamepad for X drop")

                if self.triggernade_stop:
                    break

                # ===== Wait then TAB close =====
                self.vsleep(self.drag_wait_after)

                pynput_keyboard.press(Key.tab)
                self.vsleep(51)
                pynput_keyboard.release(Key.tab)
                print(f"[{cycle}] Inventory closed")

                if self.triggernade_stop:
                    break

                # ===== Wait 300ms then M1 spam =====
                self.vsleep(300)

                # Get configurable values
                total_throws = self.trig_dc_throws_var.get()
                base_delay = self.trig_throw_delay_var.get()
                reconnect_after = self.trig_reconnect_after_var.get()
                m1_before_interweave = self.trig_m1_before_interweave_var.get()

                # Generate balanced varied delays for phase 1 (total stays same)
                phase1_delays = self.vary_balanced(base_delay, m1_before_interweave)

                # Clamp reconnect_after to be within valid range
                reconnect_after = min(reconnect_after, total_throws)
                print(f"[{cycle}] M1 spam: {total_throws} throws, reconnect after #{reconnect_after}, E interweave after #{m1_before_interweave}")

                # ===== M1 spam with reconnect, then interleaved E+M1 =====
                # Phase 1: M1s before E interweave
                for i in range(m1_before_interweave):
                    if self.triggernade_stop:
                        break

                    delay = phase1_delays[i]
                    pynput_mouse.press(MouseButton.left)
                    self.vsleep(delay / 2)
                    pynput_mouse.release(MouseButton.left)

                    # Reconnect after specified throw number
                    if i + 1 == reconnect_after and is_disconnected:
                        self.vsleep(21)
                        stop_packet_drop()
                        is_disconnected = False
                        print(f"[{cycle}] Reconnected after M1 #{i+1}")
                        self.vsleep(59)  # Wait after reconnect before next M1
                    else:
                        self.vsleep(delay / 2)

                # Safety: ensure we're reconnected
                if is_disconnected:
                    stop_packet_drop()
                    is_disconnected = False

                if self.triggernade_stop:
                    break

                # Phase 2: Interleaved E spam + M1 throws (like the recording)
                # E every ~22ms, M1 every ~100ms = about 4-5 E's per M1
                remaining_throws = max(0, total_throws - m1_before_interweave)
                print(f"[{cycle}] Interleaved E+M1: {remaining_throws} more M1s with E spam")

                for i in range(remaining_throws):
                    if self.triggernade_stop:
                        break

                    # M1 throw
                    pynput_mouse.press(MouseButton.left)

                    # E spam during M1 hold (~50ms hold, fit 2 E's)
                    for _ in range(2):
                        pynput_keyboard.press('e')
                        self.vsleep(6)
                        pynput_keyboard.release('e')
                        self.vsleep(16)

                    pynput_mouse.release(MouseButton.left)

                    # E spam between M1s (~50ms gap, fit 2-3 E's)
                    for _ in range(2):
                        if self.triggernade_stop:
                            break
                        pynput_keyboard.press('e')
                        self.vsleep(6)
                        pynput_keyboard.release('e')
                        self.vsleep(16)

                if self.triggernade_stop:
                    break

                print(f"[{cycle}] CYCLE DONE")

                # Phase 3: Continue E spam for pickup
                espam_duration_ms = self.espam_duration_var.get()
                wait_before_cycle_ms = self.wait_before_cycle_var.get()
                espam_iterations = max(1, espam_duration_ms // 22)
                print(f"[{cycle}] E spam for {espam_duration_ms}ms...")
                for _ in range(espam_iterations):
                    if self.triggernade_stop:
                        break
                    pynput_keyboard.press('e')
                    self.vsleep(6)
                    pynput_keyboard.release('e')
                    self.vsleep(16)  # ~22ms per E press

                # If single cycle (not repeat), skip Q spam and exit
                if not repeat:
                    print(f"[{cycle}] Single cycle done - E pickup complete")
                    break

                if self.triggernade_stop:
                    break

                # Q spam to ready next throw (optional)
                if self.triggernade_q_spam_var.get():
                    for _ in range(5):
                        pynput_keyboard.press('q')
                        self.vsleep(11)
                        pynput_keyboard.release('q')
                        self.vsleep(11)
                    print(f"[{cycle}] Q spam done")
                else:
                    print(f"[{cycle}] Q spam skipped")

                # Wait before next cycle (configurable)
                if wait_before_cycle_ms > 0:
                    cycle_wait_iterations = max(1, wait_before_cycle_ms // 50)
                    print(f"[{cycle}] Waiting {wait_before_cycle_ms}ms before next cycle...")
                    for _ in range(cycle_wait_iterations):
                        if self.triggernade_stop:
                            break
                        self.vsleep(50)


        finally:
            # Release ALL buttons and keys
            pynput_mouse.release(MouseButton.left)  # ctypes left mouse
            pynput_mouse.release(MouseButton.left)
            pynput_mouse.release(MouseButton.right)
            pynput_keyboard.release('e')
            pynput_keyboard.release('q')
            pynput_keyboard.release(Key.tab)

            if is_disconnected:
                stop_packet_drop()
            self.triggernade_running = False
            self.triggernade_stop = False
            self.root.after(0, lambda: self.triggernade_status_var.set("Ready"))
            self.root.after(0, lambda: self.triggernade_status_label.config(foreground="gray"))
            self.root.after(0, lambda: self.show_overlay("Wolfpack/Triggernade stopped."))

    def on_mine_hotkey(self):
        """Toggle mine dupe macro"""
        print(f"[HOTKEY] Mine hotkey PRESSED! running={self.mine_running}")
        if self.mine_running:
            print("[HOTKEY] Setting mine_stop = True")
            self.mine_stop = True
            self.root.after(0, lambda: self.mine_status_var.set("Stopping..."))
        else:
            print("[HOTKEY] Starting mine macro")
            self.mine_stop = False
            self.mine_running = True
            self.root.after(0, lambda: self.mine_status_var.set("RUNNING"))
            self.root.after(0, lambda: self.mine_status_label.config(foreground="orange"))
            self.root.after(0, lambda: self.show_overlay("Mine Dupe started"))
            threading.Thread(target=self.run_mine_macro, daemon=True).start()

    def run_mine_macro(self):
        """
        Mine dupe macro:
        1. M1 hold (place mine - configurable cook time)
        2. TAB to open inventory + Disconnect almost together
        3. Drag item to drop
        4. TAB close inventory
        5. Reconnect
        6. Click to pick up
        """
        repeat = self.mine_repeat_var.get()
        is_disconnected = False
        cycle = 0

        print(f"[MINE] Using drag: {self.mine_drag_start} → {self.mine_drag_end}")

        # Release all buttons before starting
        pynput_mouse.release(MouseButton.left)
        pynput_mouse.release(MouseButton.right)
        pynput_keyboard.release(Key.tab)

        hotkey = self.mine_hotkey_var.get()
        time.sleep(0.2)

        try:
            while True:
                if self.mine_stop:
                    print("[MINE] Stop detected at cycle start")
                    break
                if hotkey and keyboard.is_pressed(hotkey):
                    print("[MINE] Hotkey pressed - stopping")
                    self.mine_stop = True
                    break

                cycle += 1
                print(f"\n{'='*50}")
                print(f"MINE CYCLE {cycle}")
                print(f"{'='*50}")

                # Read all timing values ONCE at cycle start
                cook_time = self.mine_cook_var.get()
                dc_delay = self.mine_dc_delay_var.get()
                x_hold_ms = self.mine_x_hold_var.get()
                click_delay = self.mine_click_delay_var.get()
                dupe_click_hold = self.mine_pickup_hold_var.get()
                e_delay = self.mine_e_delay_var.get()
                loop_delay = self.mine_loop_delay_var.get()
                print(f"[{cycle}] Timings: cook={cook_time}, dc_delay={dc_delay}, x_hold={x_hold_ms}, click_delay={click_delay}, dupe_hold={dupe_click_hold}")

                self.root.after(0, lambda c=cycle: self.show_overlay(f"Mine {c}"))

                # ===== M1 hold (place mine / cook time) =====
                # Clean state - release everything first
                pynput_mouse.release(MouseButton.left)
                self.vsleep(100)
                pynput_mouse.release(MouseButton.left)  # Double release to be sure
                self.vsleep(100)

                print(f"[{cycle}] Cooking for {cook_time}ms...")
                pynput_mouse.press(MouseButton.left)
                self.vsleep(cook_time)
                pynput_mouse.release(MouseButton.left)
                self.vsleep(50)  # Small delay after release
                print(f"[{cycle}] Cook done")

                if self.mine_stop:
                    break

                # ===== TAB to open inventory =====
                pynput_keyboard.press(Key.tab)

                # ===== Delay before DC (recording: 151ms) =====
                dc_delay = self.mine_dc_delay_var.get()
                self.vsleep(dc_delay)

                # ===== Disconnect (outbound only) =====
                start_packet_drop(inbound=False)
                is_disconnected = True
                print(f"[{cycle}] Disconnected (outbound only)")

                self.vsleep(63)  # 63ms after DC, TAB release (recording)
                pynput_keyboard.release(Key.tab)
                print(f"[{cycle}] Inventory opened")

                if self.mine_stop:
                    break

                self.vsleep(30)  # 30ms

                # ===== Drop item =====
                if self.use_drag_drop_var.get():
                    # Drag drop using pynput
                    pynput_mouse.release(MouseButton.left)
                    pynput_mouse.position = self.mine_drag_start
                    self.vsleep(30)

                    pynput_mouse.press(MouseButton.left)
                    self.vsleep(80)

                    # Smooth drag
                    start_x, start_y = self.mine_drag_start
                    end_x, end_y = self.mine_drag_end
                    dx = end_x - start_x
                    dy = end_y - start_y
                    steps = 20
                    for i in range(1, steps + 1):
                        t = i / steps
                        x = int(start_x + dx * t)
                        y = int(start_y + dy * t)
                        pynput_mouse.position = (x, y)
                        self.vsleep(7)

                    pynput_mouse.release(MouseButton.left)
                    print(f"[{cycle}] Dropped with drag")
                else:
                    # Xbox X button using ViGEmBus
                    x_hold_ms = self.mine_x_hold_var.get()
                    pynput_mouse.position = self.mine_slot_pos  # Move to slot position
                    self.vsleep(20)
                    gp = get_gamepad()
                    if gp:
                        gp.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                        gp.update()
                        self.vsleep(x_hold_ms)
                        gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                        gp.update()
                        print(f"[{cycle}] Dropped with Xbox X ({x_hold_ms}ms)")

                if self.mine_stop:
                    break

                # ===== TAB close inventory =====
                self.vsleep(100)
                pynput_keyboard.press(Key.tab)
                self.vsleep(70)
                pynput_keyboard.release(Key.tab)
                print(f"[{cycle}] Inventory closed")

                if self.mine_stop:
                    break

                # ===== Reconnect =====
                self.vsleep(940)  # ~940ms after closing inventory
                stop_packet_drop()
                is_disconnected = False
                print(f"[{cycle}] Reconnected")

                # ===== M1 click to complete dupe =====
                click_delay = self.mine_click_delay_var.get()
                self.vsleep(click_delay)
                dupe_click_hold = self.mine_pickup_hold_var.get()
                pynput_mouse.release(MouseButton.left)  # Clean state
                pynput_mouse.press(MouseButton.left)
                print(f"[{cycle}] M1 pressed, holding {dupe_click_hold}ms...")
                self.vsleep(dupe_click_hold)
                pynput_mouse.release(MouseButton.left)
                print(f"[{cycle}] M1 released")
                print(f"[{cycle}] CYCLE DONE")

                if not repeat:
                    print(f"[{cycle}] Single cycle done")
                    break

                if self.mine_stop:
                    break

                # ===== LOOP ONLY: Pause, then E to pick up, then Q to swap =====
                self.vsleep(e_delay)

                # Single E press to pick up
                pynput_keyboard.press('e')
                self.vsleep(50)
                pynput_keyboard.release('e')
                print(f"[{cycle}] E pressed to pick up")

                if self.mine_stop:
                    break

                # Q to swap back to mine in quick use
                self.vsleep(100)
                pynput_keyboard.press('q')
                self.vsleep(50)
                pynput_keyboard.release('q')
                print(f"[{cycle}] Pressed Q to swap back")

                # Wait before next cycle (scales with variance slider - more extreme)
                loop_delay_ms = self.mine_loop_delay_var.get()
                variance_pct = self.timing_variance_var.get()
                extra_loop_var = random.uniform(0, variance_pct * 10) if variance_pct > 0 else 0
                self.vsleep(loop_delay_ms + extra_loop_var)

        finally:
            pynput_mouse.release(MouseButton.left)
            pynput_keyboard.release(Key.tab)
            if is_disconnected:
                stop_packet_drop()
            self.mine_running = False
            self.mine_stop = False
            self.root.after(0, lambda: self.mine_status_var.set("Ready"))
            self.root.after(0, lambda: self.mine_status_label.config(foreground="gray"))
            self.root.after(0, lambda: self.show_overlay("Mine Dupe stopped."))

    def on_espam_hotkey(self):
        """Toggle E-spam macro"""
        print(f"[HOTKEY] E-Spam hotkey PRESSED! running={self.espam_running}")
        if self.espam_running:
            print("[HOTKEY] Setting espam_stop = True")
            self.espam_stop = True
            self.root.after(0, lambda: self.espam_status_var.set("Stopping..."))
        else:
            print("[HOTKEY] Starting E-spam macro")
            self.espam_stop = False
            self.espam_running = True
            self.root.after(0, lambda: self.espam_status_var.set("SPAMMING E"))
            self.root.after(0, lambda: self.espam_status_label.config(foreground="green"))
            self.root.after(0, lambda: self.show_overlay("E-Spam running..."))
            threading.Thread(target=self.run_espam_macro, daemon=True).start()

    def run_espam_macro(self):
        """E-Spam macro - spams E with configurable repeat delay"""
        from pynput.keyboard import Controller as KeyboardController
        kb = KeyboardController()

        # Brief delay so starting hotkey doesn't trigger stop
        time.sleep(0.2)

        repeat_delay = self.espam_repeat_delay_var.get()  # seconds

        try:
            while not self.espam_stop:
                # Spam E rapidly
                kb.press('e')
                self.vsleep(11)
                kb.release('e')
                self.vsleep(50)

                # If repeat delay > 0, pause between spam bursts
                if repeat_delay > 0 and not self.espam_stop:
                    # Wait for repeat delay (check stop flag periodically)
                    waited = 0
                    while waited < repeat_delay and not self.espam_stop:
                        self.vsleep(100)
                        waited += 0.1
        finally:
            self.espam_running = False
            self.espam_stop = False
            self.root.after(0, lambda: self.espam_status_var.set("Ready"))
            self.root.after(0, lambda: self.espam_status_label.config(foreground="gray"))
            self.root.after(0, lambda: self.show_overlay("E-Spam stopped."))

    def on_untitled1_hotkey(self):
        """Toggle Ammo macro"""
        print(f"[HOTKEY] Untitled1 hotkey PRESSED! running={self.untitled1_running}")
        if self.untitled1_running:
            print("[HOTKEY] Setting untitled1_stop = True")
            self.untitled1_stop = True
            self.root.after(0, lambda: self.untitled1_status_var.set("Stopping..."))
        else:
            print("[HOTKEY] Starting Ammo")
            self.untitled1_stop = False
            self.untitled1_running = True
            self.root.after(0, lambda: self.untitled1_status_var.set("RUNNING"))
            self.root.after(0, lambda: self.untitled1_status_label.config(foreground="orange"))
            self.root.after(0, lambda: self.show_overlay("Ammo started"))
            threading.Thread(target=self.run_untitled1_macro, daemon=True).start()

    def _smooth_move(self, target_pos, steps=8):
        """Smooth mouse movement to target position with variance"""
        current = pynput_mouse.position
        start_x, start_y = current
        end_x, end_y = target_pos
        dx = end_x - start_x
        dy = end_y - start_y
        for i in range(1, steps + 1):
            t = i / steps
            x = int(start_x + dx * t)
            y = int(start_y + dy * t)
            pynput_mouse.position = (x, y)
            self.vsleep(2)  # ~2ms per step with variance

    def run_untitled1_macro(self):
        """
        Ammo:
        1. TAB open
        2. DC outbound
        3. Move to weapon slot + right click
        4. Click context menu
        5. M1 drag to inventory slot
        6. Wait 300ms
        7. Reconnect
        8. Double click on inventory slot
        9. TAB close
        10. Press 1
        11. Wait 500ms
        12. Repeat
        """
        repeat = self.untitled1_repeat_var.get()
        is_disconnected = False
        cycle = 0

        # Release all keys/buttons before starting
        pynput_mouse.release(MouseButton.left)
        pynput_mouse.release(MouseButton.right)
        pynput_keyboard.release(Key.tab)
        pynput_keyboard.release('1')

        hotkey = self.untitled1_hotkey_var.get()
        time.sleep(0.2)  # Brief delay so hotkey doesn't trigger stop

        try:
            while True:
                if self.untitled1_stop:
                    print("[UNTITLED1] Stop detected at cycle start")
                    break
                if hotkey and keyboard.is_pressed(hotkey):
                    print("[UNTITLED1] Hotkey pressed - stopping")
                    self.untitled1_stop = True
                    break

                cycle += 1
                print(f"\n{'='*50}")
                print(f"UNTITLED #1 CYCLE {cycle}")
                print(f"{'='*50}")

                self.root.after(0, lambda c=cycle: self.show_overlay(f"Ammo - {c}"))

                # Get all timing values
                tab_hold = self.um1_tab_hold_var.get()
                after_tab_open = self.um1_after_tab_open_var.get()
                rclick_hold = self.um1_rclick_hold_var.get()
                after_rclick = self.um1_after_rclick_var.get()
                after_dc = self.um1_after_dc_var.get()
                context_hold = self.um1_context_hold_var.get()
                after_context = self.um1_after_context_var.get()
                after_reconnect = self.um1_after_reconnect_var.get()
                dblclick_hold = self.um1_dblclick_hold_var.get()
                dblclick_gap = self.um1_dblclick_gap_var.get()
                after_dblclick = self.um1_after_dblclick_var.get()
                after_tab_close = self.um1_after_tab_close_var.get()
                equip_hold = self.um1_equip_hold_var.get()
                loop_delay = self.um1_loop_delay_var.get()

                # ===== 1. TAB to open inventory =====
                pynput_keyboard.press(Key.tab)
                self.vsleep(tab_hold)
                pynput_keyboard.release(Key.tab)
                self.vsleep(after_tab_open)
                print(f"[{cycle}] Inventory opened")

                if self.untitled1_stop: break

                # ===== 2. Disconnect outbound =====
                start_packet_drop(inbound=False)
                is_disconnected = True
                self.vsleep(after_dc)
                print(f"[{cycle}] Disconnected outbound")

                if self.untitled1_stop: break

                # ===== 3. Move to weapon slot and right click =====
                self._smooth_move(self.um1_item_pos)
                pynput_mouse.press(MouseButton.right)
                self.vsleep(rclick_hold)
                pynput_mouse.release(MouseButton.right)
                self.vsleep(after_rclick)
                print(f"[{cycle}] Right clicked weapon at {self.um1_item_pos}")

                if self.untitled1_stop: break

                # ===== 4. Move to context menu and left click =====
                self._smooth_move(self.um1_context_pos)
                pynput_mouse.press(MouseButton.left)
                self.vsleep(context_hold)
                pynput_mouse.release(MouseButton.left)
                self.vsleep(after_context)
                print(f"[{cycle}] Clicked context menu at {self.um1_context_pos}")

                if self.untitled1_stop: break

                # ===== 5. Drag item from drag_start to drag_end =====
                self._smooth_move(self.um1_drag_start)
                pynput_mouse.press(MouseButton.left)
                self.vsleep(80)  # Hold before drag
                # Smooth drag with variance
                start_x, start_y = self.um1_drag_start
                end_x, end_y = self.um1_drag_end
                dx = end_x - start_x
                dy = end_y - start_y
                steps = 15
                for i in range(1, steps + 1):
                    t = i / steps
                    x = int(start_x + dx * t)
                    y = int(start_y + dy * t)
                    pynput_mouse.position = (x, y)
                    self.vsleep(5)  # ~5ms per step with variance
                pynput_mouse.release(MouseButton.left)
                print(f"[{cycle}] Dragged item {self.um1_drag_start} → {self.um1_drag_end}")

                if self.untitled1_stop: break

                # ===== 6. Wait 300ms before reconnect =====
                self.vsleep(300)
                print(f"[{cycle}] Waited 300ms before reconnect")

                if self.untitled1_stop: break

                # ===== 7. Reconnect =====
                stop_packet_drop()
                is_disconnected = False
                self.vsleep(after_reconnect)
                print(f"[{cycle}] Reconnected")

                if self.untitled1_stop: break

                # ===== 8. Double click at drag_end (transfer back) =====
                self._smooth_move(self.um1_drag_end)
                # First click
                pynput_mouse.press(MouseButton.left)
                self.vsleep(dblclick_hold)
                pynput_mouse.release(MouseButton.left)
                # Small gap with tiny variance (keeps it a double click)
                time.sleep((dblclick_gap + random.uniform(-3, 3)) / 1000.0)
                # Second click
                pynput_mouse.press(MouseButton.left)
                self.vsleep(dblclick_hold)
                pynput_mouse.release(MouseButton.left)
                self.vsleep(after_dblclick)
                print(f"[{cycle}] Double clicked at {self.um1_drag_end}")

                if self.untitled1_stop: break

                # ===== 9. TAB to close inventory =====
                pynput_keyboard.press(Key.tab)
                self.vsleep(tab_hold)
                pynput_keyboard.release(Key.tab)
                self.vsleep(after_tab_close)
                print(f"[{cycle}] Inventory closed")

                if self.untitled1_stop: break

                # ===== 10. Press 1 to equip =====
                pynput_keyboard.press('1')
                self.vsleep(equip_hold)
                pynput_keyboard.release('1')
                print(f"[{cycle}] Pressed 1 to equip")

                print(f"[{cycle}] CYCLE DONE")

                if not repeat:
                    print(f"[{cycle}] Single cycle done")
                    break

                if self.untitled1_stop: break

                # Wait before next cycle
                if loop_delay > 0:
                    self.vsleep(loop_delay)

        finally:
            pynput_mouse.release(MouseButton.left)
            pynput_mouse.release(MouseButton.right)
            pynput_keyboard.release(Key.tab)
            pynput_keyboard.release('1')
            if is_disconnected:
                stop_packet_drop()
            self.untitled1_running = False
            self.untitled1_stop = False
            self.root.after(0, lambda: self.untitled1_status_var.set("Ready"))
            self.root.after(0, lambda: self.untitled1_status_label.config(foreground="gray"))
            self.root.after(0, lambda: self.show_overlay("Ammo stopped."))

    def show_overlay(self, text):
        if not self.show_overlay_var.get():
            return
        if self.overlay_window is None or not self.overlay_window.winfo_exists():
            self.overlay_window = tk.Toplevel(self.root)
            self.overlay_window.overrideredirect(True)
            self.overlay_window.attributes('-topmost', True)
            self.overlay_window.attributes('-transparentcolor', 'black')
            self.overlay_window.configure(bg='black')

            # Use canvas for text with outline
            self.overlay_canvas = tk.Canvas(self.overlay_window, bg='black', highlightthickness=0)
            self.overlay_canvas.pack()

        # Clear and redraw
        self.overlay_canvas.delete('all')
        font = ("Arial", 48, "bold")

        # Measure text first
        temp_id = self.overlay_canvas.create_text(0, 0, text=text, font=font, anchor='nw')
        bbox = self.overlay_canvas.bbox(temp_id)
        self.overlay_canvas.delete(temp_id)

        if bbox:
            w, h = bbox[2] - bbox[0] + 40, bbox[3] - bbox[1] + 40
            cx, cy = w // 2, h // 2
            self.overlay_canvas.config(width=w, height=h)

            # Draw black outline (offset in 8 directions)
            for dx, dy in [(-2,-2), (-2,2), (2,-2), (2,2), (-2,0), (2,0), (0,-2), (0,2)]:
                self.overlay_canvas.create_text(cx+dx, cy+dy, text=text, font=font, fill='black')
            # Draw white text on top
            self.overlay_canvas.create_text(cx, cy, text=text, font=font, fill='white')

        self.overlay_window.update_idletasks()

        # Center on screen
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        overlay_width = self.overlay_window.winfo_reqwidth()
        overlay_height = self.overlay_window.winfo_reqheight()
        x = (screen_width - overlay_width) // 2
        y = (screen_height - overlay_height) // 2
        self.overlay_window.geometry(f"+{x}+{y}")
        self.overlay_window.deiconify()

        if self.overlay_hide_id:
            self.root.after_cancel(self.overlay_hide_id)
        self.overlay_hide_id = self.root.after(3000, self.hide_overlay)

    def hide_overlay(self):
        if self.overlay_window and self.overlay_window.winfo_exists():
            self.overlay_window.withdraw()

    def on_close(self):
        self.throwable_stop = True
        self.keydoor_stop = True
        self.triggernade_stop = True
        self.espam_stop = True

        # ALWAYS ensure network is restored on close
        try:
            stop_packet_drop()
            stop_packet_tamper()
            print("[CLOSE] Network restored")
        except Exception as e:
            print(f"[CLOSE] Error restoring network: {e}")

        # Stop drag recording listener if active
        if self.drag_mouse_listener:
            try:
                self.drag_mouse_listener.stop()
            except:
                pass
        if self.dc_hotkey_registered:
            try:
                keyboard.remove_hotkey(self.dc_hotkey_registered)
            except:
                pass
        if self.throwable_hotkey_registered:
            try:
                keyboard.remove_hotkey(self.throwable_hotkey_registered)
            except:
                pass
        if self.triggernade_hotkey_registered:
            try:
                keyboard.remove_hotkey(self.triggernade_hotkey_registered)
            except:
                pass
        if self.espam_hotkey_registered:
            try:
                keyboard.remove_hotkey(self.espam_hotkey_registered)
            except:
                pass

        # Save window position
        self.config["window_x"] = self.root.winfo_x()
        self.config["window_y"] = self.root.winfo_y()
        save_config(self.config)

        self.root.destroy()


if __name__ == "__main__":
    # Make app DPI-aware so mouse coordinates are consistent
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # Fallback
        except:
            pass

    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

    print("=" * 50)
    print("QD 1.4.0 Starting...")

    # Initialize gamepad once at startup
    init_gamepad()
    print("=" * 50)

    root = tk.Tk()
    app = QuickDupeApp(root)

    # Auto-enable drag drop if ViGEmBus failed
    if get_gamepad() is None:
        app.auto_enable_drag_drop_if_no_vigembus()

    # Apply stay-on-top setting from config
    if app.config.get("stay_on_top", False):
        root.attributes('-topmost', True)
        print("[UI] Stay on top enabled from config")

    print(f"[CONFIG] Loaded config: {app.config}")
    print(f"[CONFIG] Keydoor hotkey: '{app.dc_hotkey_var.get()}'")
    print(f"[CONFIG] Throwable hotkey: '{app.throwable_hotkey_var.get()}'")

    app.register_hotkeys()
    print("[STARTUP] Ready - listening for hotkeys")
    print("=" * 50)

    root.mainloop()
