import keyboard
import subprocess
import ctypes
import sys
import threading
import json
import os
import time
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
    while _on and _handle:
        try:
            _handle.recv()  # recv but don't send = drop
        except:
            break

def stop_packet_drop():
    """STOP DROPPING NOW"""
    global _handle, _on
    if not _on:
        return
    _on = False
    if _handle:
        try:
            _handle.close()
        except:
            pass
        _handle = None

def is_dropping():
    return _on

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
        self.root.title("Quick Dupe")
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
        self.espam_running = False
        self.espam_stop = False
        self.espam_hotkey_registered = None
        self.escape_hotkey_registered = None
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
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

            self.tray_icon = pystray.Icon("QuickDupe", image, "Quick Dupe", menu)
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
        title_label = tk.Label(title_bar, text="QD", bg=self.colors['bg_light'],
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

        # ===== DRAG DROP FALLBACK =====
        # Only use drag drop if: user manually enabled it, OR vigembus failed and user hasn't disabled it
        self.use_drag_drop_var = tk.BooleanVar(value=self.config.get("use_drag_drop", False))
        drag_drop_frame = ttk.Frame(frame)
        drag_drop_frame.pack(anchor='w', padx=10, pady=5)
        ttk.Checkbutton(drag_drop_frame, text="Use drag & drop (if ViGEmBus fails)", variable=self.use_drag_drop_var, command=self.on_drag_drop_manual_toggle).pack(side='left')

        # Drag timing values (used for drag drop fallback)
        self.drag_wait_after = 150    # ms after drop before Tab close

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== KEYDOOR METHOD SECTION =====
        ttk.Label(frame, text="── Keydoor Method ──", style='Header.TLabel').pack(pady=(0, 5))

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
        self.keydoor_drag_btn = ttk.Button(keydoor_drag_frame, text="Record Pos", width=12, command=self.start_keydoor_drag_recording)
        self.keydoor_drag_btn.pack(side='left')
        self.keydoor_drag_var = tk.StringVar()
        # Load keydoor drag positions
        kd_start = self.config.get("keydoor_drag_start", [3024, 669])
        kd_end = self.config.get("keydoor_drag_end", [550, 1247])
        self.keydoor_drag_start = tuple(kd_start)
        self.keydoor_drag_end = tuple(kd_end)
        self.keydoor_drag_var.set(f"({kd_start[0]},{kd_start[1]}) → ({kd_end[0]},{kd_end[1]})")
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
        ttk.Label(frame, text="── Throwable Dupe ──", style='Header.TLabel').pack(pady=(5, 5))

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
        self.throwable_repeat_var = tk.BooleanVar(value=self.config.get("throwable_repeat", True))
        ttk.Checkbutton(frame, text="Auto (loop until pressed again)", variable=self.throwable_repeat_var, command=self.save_settings).pack(anchor='w', padx=10, pady=5)

        # Throwable Timings
        self.create_slider(frame, "Throw hold time:", "throw_hold_time", 45, 10, 200, "ms")
        self.create_slider(frame, "Delay before DC:", "throw_dc_delay_before", 40, 0, 200, "ms")
        self.create_slider(frame, "Wait before E:", "throw_wait_before_e", 200, 0, 2000, "ms")
        self.create_slider(frame, "Wait after E:", "throw_wait_after_e", 100, 0, 1000, "ms")
        self.create_slider(frame, "Wait after Q:", "throw_wait_after_q", 750, 0, 2000, "ms")
        self.create_slider(frame, "Throws while DC'd:", "throw_dc_count", 12, 1, 30, "")
        self.create_slider(frame, "Time between throws:", "throw_dc_delay", 86, 10, 500, "ms")

        ttk.Button(frame, text="Reset Throwable Defaults", command=self.reset_throwable_defaults).pack(pady=5)
        self.throwable_status_var = tk.StringVar(value="Ready")
        self.throwable_status_label = ttk.Label(frame, textvariable=self.throwable_status_var, style='Dim.TLabel')
        self.throwable_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== TRIGGERNADE SECTION =====
        ttk.Label(frame, text="── Wolfpack/Triggernade Dupe ──", style='Header.TLabel').pack(pady=(5, 5), anchor='center')

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
        self.trig_drag_btn = ttk.Button(trig_drag_frame, text="Record Pos", width=12, command=self.start_trig_drag_recording)
        self.trig_drag_btn.pack(side='left')
        self.trig_drag_var = tk.StringVar()
        # Load triggernade drag positions
        trig_start = self.config.get("trig_drag_start", [3024, 669])
        trig_end = self.config.get("trig_drag_end", [550, 1247])
        self.trig_drag_start = tuple(trig_start)
        self.trig_drag_end = tuple(trig_end)
        self.trig_drag_var.set(f"({trig_start[0]},{trig_start[1]}) → ({trig_end[0]},{trig_end[1]})")
        ttk.Label(trig_drag_frame, textvariable=self.trig_drag_var, font=("Consolas", 8)).pack(side='left', padx=5)

        # Repeat checkbox
        self.triggernade_repeat_var = tk.BooleanVar(value=self.config.get("triggernade_repeat", True))
        ttk.Checkbutton(frame, text="Auto (loop until pressed again)", variable=self.triggernade_repeat_var, command=self.save_settings).pack(anchor='w', padx=10, pady=5)

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
                val = max(10, min(500, val))
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
        self.create_slider(frame, "M1s while DC'd:", "trig_dc_throws", 10, 1, 30, "")
        self.create_slider(frame, "Time between M1s:", "trig_throw_delay", 100, 10, 500, "ms")
        self.create_slider(frame, "Reconnect after M1 #:", "trig_reconnect_after", 1, 1, 20, "")
        self.create_slider(frame, "Wait before E spam:", "wait_before_espam", 0, 0, 2000, "ms")
        self.create_slider(frame, "E spam duration:", "espam_duration", 1000, 0, 5000, "ms")
        self.create_slider(frame, "Wait before next cycle:", "wait_before_cycle", 100, 0, 2000, "ms")

        # Slot position for X drop
        slot_frame = ttk.Frame(frame)
        slot_frame.pack(fill='x', padx=10, pady=5)
        ttk.Label(slot_frame, text="Drop position:").pack(side='left')

        # Record button
        self.slot_record_btn = ttk.Button(slot_frame, text="Record", width=8, command=self.start_slot_recording)
        self.slot_record_btn.pack(side='left', padx=(10, 5))

        # Position display
        self.slot_pos_var = tk.StringVar()
        saved_pos = self.config.get("drop_position", [3024, 669])  # Default position
        self.drag_start = tuple(saved_pos)
        self.slot_pos_var.set(f"({saved_pos[0]}, {saved_pos[1]})")
        ttk.Label(slot_frame, textvariable=self.slot_pos_var, font=("Consolas", 8)).pack(side='left')

        ttk.Button(frame, text="Reset Triggernade Defaults", command=self.reset_triggernade_defaults).pack(pady=5)
        self.triggernade_status_var = tk.StringVar(value="Ready")
        self.triggernade_status_label = ttk.Label(frame, textvariable=self.triggernade_status_var, style='Dim.TLabel')
        self.triggernade_status_label.pack(pady=5)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=10, pady=10)

        # ===== E-SPAM COLLECTION SECTION =====
        ttk.Label(frame, text="── E-Spam Collection ──", style='Header.TLabel').pack(pady=(5, 5), anchor='center')

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

        # ===== MANUAL DISCONNECT SECTION =====
        ttk.Label(frame, text="── Manual Disconnect ──", style='Header.TLabel').pack(pady=(5, 5))

        # Inbound/Outbound checkboxes
        dc_options_frame = ttk.Frame(frame)
        dc_options_frame.pack(fill='x', padx=10, pady=5)
        self.dc_outbound_var = tk.BooleanVar(value=self.config.get("dc_outbound", True))
        self.dc_inbound_var = tk.BooleanVar(value=self.config.get("dc_inbound", True))
        ttk.Checkbutton(dc_options_frame, text="Outbound", variable=self.dc_outbound_var, command=self.save_settings).pack(side='left', padx=(0, 10))
        ttk.Checkbutton(dc_options_frame, text="Inbound", variable=self.dc_inbound_var, command=self.save_settings).pack(side='left')

        # Disconnect button and hotkey
        test_dc_frame = ttk.Frame(frame)
        test_dc_frame.pack(fill='x', padx=10, pady=5)
        self.test_dc_btn = ttk.Button(test_dc_frame, text="DISCONNECT", width=15, command=self.toggle_test_disconnect)
        self.test_dc_btn.pack(side='left', padx=5)
        ttk.Label(test_dc_frame, text="Hotkey:").pack(side='left', padx=(10, 0))
        self.test_dc_hotkey_var = tk.StringVar(value=self.config.get("test_dc_hotkey", "["))
        self.test_dc_hotkey_entry = tk.Entry(test_dc_frame, textvariable=self.test_dc_hotkey_var, width=8, state="readonly",
                                           bd=0, highlightthickness=0, bg='#2d2d2d', fg='#e0e0e0', readonlybackground='#2d2d2d')
        self.test_dc_hotkey_entry.pack(side='left', padx=5)
        self.test_dc_record_btn = ttk.Button(test_dc_frame, text="Set", width=4, command=self.start_recording_test_dc)
        self.test_dc_record_btn.pack(side='left')
        self.test_disconnected = False
        self.recording_test_dc = False

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

    def create_slider(self, parent, label, config_key, default, min_val, max_val, unit):
        """Create a slider row with label, slider, and editable value entry"""
        row = ttk.Frame(parent)
        row.pack(fill='x', padx=10, pady=2)

        ttk.Label(row, text=label, width=20, anchor='w').pack(side='left')

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
                val = max(min_val, min(max_val, val))  # Clamp to range
                var.set(val)
                entry.delete(0, 'end')
                entry.insert(0, str(val))
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

    def start_recording_espam(self):
        self.recording_espam = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.espam_record_btn.config(text="...")
        self.espam_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_triggernade(self):
        self.recording_triggernade = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_espam = False
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
                    self.keydoor_drag_start = pos
                    self.config["keydoor_drag_start"] = list(pos)
                    self.keydoor_drag_var.set(f"Pos: ({x}, {y})")
                    print(f"[KEYDOOR POS] Recorded: {pos}")
                else:
                    self.trig_drag_start = pos
                    self.config["trig_drag_start"] = list(pos)
                    self.trig_drag_var.set(f"Pos: ({x}, {y})")
                    print(f"[TRIG POS] Recorded: {pos}")

                save_config(self.config)
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

    def start_recording_dc(self):
        self.recording_dc = True
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.dc_record_btn.config(text="...")
        self.dc_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def start_recording_throwable(self):
        self.recording_throwable = True
        self.recording_dc = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.throwable_record_btn.config(text="...")
        self.throwable_hotkey_var.set("Press key...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def on_key_press(self, event):
        if not self.recording_dc and not self.recording_throwable and not self.recording_triggernade and not self.recording_espam and not self.recording_test_dc:
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
        }

        key = event.keysym.lower()
        key = tkinter_to_keyboard.get(key, key)  # Map if exists, otherwise use as-is

        modifier_keys = ['ctrl', 'alt', 'shift', 'control_l', 'control_r', 'alt_l', 'alt_r', 'shift_l', 'shift_r', 'meta_l', 'meta_r']
        if key not in modifier_keys:
            parts.append(key)
            hotkey = "+".join(parts)
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
            elif self.recording_espam:
                self.espam_hotkey_var.set(hotkey)
                self.espam_record_btn.config(text="Set")
                self.recording_espam = False
            elif self.recording_test_dc:
                self.test_dc_hotkey_var.set(hotkey)
                self.test_dc_record_btn.config(text="Set")
                self.recording_test_dc = False
            self.root.unbind("<KeyPress>")
            self.save_settings()
            self.register_hotkeys()

    def toggle_stay_on_top(self):
        """Toggle window always-on-top setting"""
        stay_on_top = self.stay_on_top_var.get()
        self.root.attributes('-topmost', stay_on_top)
        self.save_settings()
        print(f"[UI] Stay on top: {stay_on_top}")

    def toggle_test_disconnect(self):
        """Toggle test disconnect - drops packets based on checkbox settings"""
        if self.test_disconnected:
            # Reconnect
            stop_packet_drop()
            self.test_dc_btn.config(text="DISCONNECT")
            self.test_disconnected = False
            self.root.after(0, lambda: self.show_overlay("RECONNECTED"))
        else:
            # Disconnect using checkbox settings
            outbound = self.dc_outbound_var.get()
            inbound = self.dc_inbound_var.get()
            if not outbound and not inbound:
                self.root.after(0, lambda: self.show_overlay("Select inbound or outbound!"))
                return
            start_packet_drop(outbound=outbound, inbound=inbound)
            self.test_dc_btn.config(text="RECONNECT")
            self.test_disconnected = True
            self.root.after(0, lambda: self.show_overlay("DISCONNECTED"))

    def start_recording_test_dc(self):
        """Start recording hotkey for test disconnect"""
        self.recording_test_dc = True
        self.recording_dc = False
        self.recording_throwable = False
        self.recording_triggernade = False
        self.recording_espam = False
        self.test_dc_record_btn.config(text="...")
        self.test_dc_hotkey_var.set("...")
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.focus_set()

    def on_drag_drop_manual_toggle(self):
        """User manually toggled drag drop - remember their preference and update button text"""
        self.config["drag_drop_user_set"] = True  # User explicitly set this
        self._update_record_button_text()
        self.save_settings()

    def _update_record_button_text(self):
        """Update record button text based on drag drop mode"""
        if self.use_drag_drop_var.get():
            self.keydoor_drag_btn.config(text="Record Drag")
            self.trig_drag_btn.config(text="Record Drag")
        else:
            self.keydoor_drag_btn.config(text="Record Pos")
            self.trig_drag_btn.config(text="Record Pos")

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
        self.config["throw_wait_after_e"] = self.throw_wait_after_e_var.get()
        self.config["throw_wait_after_q"] = self.throw_wait_after_q_var.get()
        self.config["throw_dc_count"] = self.throw_dc_count_var.get()
        self.config["throw_dc_delay"] = self.throw_dc_delay_var.get()
        # Triggernade settings
        self.config["triggernade_hotkey"] = self.triggernade_hotkey_var.get()
        self.config["triggernade_repeat"] = self.triggernade_repeat_var.get()
        self.config["espam_hotkey"] = self.espam_hotkey_var.get()
        self.config["wait_before_espam"] = self.wait_before_espam_var.get()
        self.config["espam_duration"] = self.espam_duration_var.get()
        self.config["wait_before_cycle"] = self.wait_before_cycle_var.get()
        self.config["trig_dc_throws"] = self.trig_dc_throws_var.get()
        self.config["trig_throw_delay"] = self.trig_throw_delay_var.get()
        self.config["trig_reconnect_after"] = self.trig_reconnect_after_var.get()
        self.config["trig_m1_hold"] = self.trig_m1_hold_var.get()
        self.config["trig_m2_hold"] = self.trig_m2_hold_var.get()
        # E-spam settings
        self.config["espam_hold_mode"] = self.espam_hold_mode_var.get()
        self.config["espam_repeat_delay"] = self.espam_repeat_delay_var.get()
        # Manual disconnect settings
        self.config["test_dc_hotkey"] = self.test_dc_hotkey_var.get()
        self.config["dc_outbound"] = self.dc_outbound_var.get()
        self.config["dc_inbound"] = self.dc_inbound_var.get()
        # General settings
        self.config["stay_on_top"] = self.stay_on_top_var.get()
        self.config["show_overlay"] = self.show_overlay_var.get()
        self.config["use_drag_drop"] = self.use_drag_drop_var.get()
        save_config(self.config)

    def reset_keydoor_defaults(self):
        """Reset all keydoor timing parameters to defaults"""
        self.keydoor_x_hold_var.set(1250)
        self.keydoor_tab_hold_var.set(21)
        self.keydoor_wait_before_e_var.set(73)
        self.keydoor_espam_count_var.set(30)
        self.keydoor_e_hold_var.set(13)
        self.keydoor_e_delay_var.set(12)
        self.save_settings()
        print("[RESET] Keydoor parameters reset to defaults")

    def reset_throwable_defaults(self):
        """Reset all throwable timing parameters to defaults"""
        self.throw_hold_time_var.set(45)
        self.throw_dc_delay_before_var.set(40)
        self.throw_wait_before_e_var.set(200)
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
        self.save_settings()
        print("[RESET] Triggernade parameters reset to defaults")

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
        self.test_dc_hotkey_var.set("[")

        # Reset checkboxes
        self.use_drag_drop_var.set(False)
        self.show_overlay_var.set(True)
        self.stay_on_top_var.set(False)
        self.throwable_repeat_var.set(True)
        self.triggernade_repeat_var.set(True)
        self.dc_outbound_var.set(True)
        self.dc_inbound_var.set(True)

        # Reset drag positions to defaults
        self.keydoor_drag_start = (3024, 669)
        self.keydoor_drag_end = (550, 1247)
        self.trig_drag_start = (3024, 669)
        self.trig_drag_end = (550, 1247)
        self.keydoor_drag_var.set("(3024,669) → (550,1247)")
        self.trig_drag_var.set("(3024,669) → (550,1247)")

        # Reset all timing sliders
        self.reset_keydoor_defaults()
        self.reset_throwable_defaults()
        self.reset_triggernade_defaults()

        # Re-register hotkeys (will be empty now)
        self.register_hotkeys()

        print("[RESET] ALL settings reset to factory defaults")
        self.show_overlay("All settings reset!")

    def register_hotkeys(self):
        # Clear ALL hotkeys first to prevent ghost hotkeys
        try:
            keyboard.unhook_all_hotkeys()
            print("[HOTKEY] Cleared all previous hotkeys")
        except Exception as e:
            print(f"[HOTKEY] Error clearing hotkeys: {e}")

        self.dc_hotkey_registered = None
        self.throwable_hotkey_registered = None
        self.triggernade_hotkey_registered = None
        self.espam_hotkey_registered = None
        self.escape_hotkey_registered = None
        self.test_dc_hotkey_registered = None

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

        # Register test disconnect hotkey
        test_dc_hk = self.test_dc_hotkey_var.get()
        if test_dc_hk and test_dc_hk != "Press key..." and test_dc_hk != "...":
            try:
                self.test_dc_hotkey_registered = keyboard.add_hotkey(test_dc_hk, self.toggle_test_disconnect, suppress=False)
                print(f"[HOTKEY] Test DC registered OK: '{test_dc_hk}' -> {self.test_dc_hotkey_registered}")
            except Exception as e:
                print(f"[HOTKEY] FAILED test_dc '{test_dc_hk}': {e}")

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

        if gp is None:
            print("[KEYDOOR] Skipping - ViGEmBus not installed")
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
        if self.use_drag_drop_var.get():
            # Drag fallback using pynput
            print(f"[KEYDOOR] Using drag drop: {self.keydoor_drag_start} → {self.keydoor_drag_end}")

            # Clear any stuck mouse state first
            pynput_mouse.release(MouseButton.left)

            # Move to start position
            pynput_mouse.position = self.keydoor_drag_start
            time.sleep(0.03)

            # Press and drag
            pynput_mouse.press(MouseButton.left)
            time.sleep(0.08)  # Click registers

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
                time.sleep(0.007)

            pynput_mouse.release(MouseButton.left)
            print(f"[KEYDOOR] Drag complete")
        else:
            # Xbox X button - move to recorded position first
            print(f"[KEYDOOR] Moving to {self.keydoor_drag_start}, holding X for {x_hold_ms}ms")
            pynput_mouse.position = self.keydoor_drag_start
            time.sleep(0.02)
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
                time.sleep(0.01)
                t += 10

            gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
            gp.update()
            print("[KEYDOOR] X released - key should be dropped")

        if self.keydoor_stop:
            self.finish_keydoor(is_disconnected)
            return

        # TAB to exit inventory
        pynput_keyboard.press(Key.tab)
        time.sleep(tab_hold_ms / 1000.0)
        pynput_keyboard.release(Key.tab)
        time.sleep(wait_before_e_ms / 1000.0)
        print("[KEYDOOR] TAB - exited inventory")

        if self.keydoor_stop:
            self.finish_keydoor(is_disconnected)
            return

        # ===== E spam - reconnect after just 1 press =====
        print("[KEYDOOR] Starting E spam...")
        pynput_keyboard.press('e')
        time.sleep(e_hold_ms / 1000.0)
        pynput_keyboard.release('e')
        time.sleep(0.007)

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
            time.sleep(e_hold_ms / 1000.0)
            pynput_keyboard.release('e')
            time.sleep(e_delay_ms / 1000.0)

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
        time.sleep(0.010)
        pynput_keyboard.release('q')
        time.sleep(0.500)
        print("[PREP] Done, starting loop")

        try:
            while True:
                cycle += 1
                cycle_start = time.perf_counter()
                print(f"\n=== CYCLE {cycle} ===")

                # ===== Initial throw =====
                throw_hold = self.throw_hold_time_var.get() / 1000.0
                dc_delay = self.throw_dc_delay_before_var.get() / 1000.0

                time.sleep(0.005)
                pynput_mouse.press(MouseButton.left)
                time.sleep(throw_hold)
                pynput_mouse.release(MouseButton.left)
                print(f"[{cycle}] Throw done (held {int(throw_hold*1000)}ms)")

                # ===== Delay before disconnect =====
                if dc_delay > 0:
                    time.sleep(dc_delay)
                    print(f"[{cycle}] Waited {int(dc_delay*1000)}ms before DC")

                start_packet_drop()
                is_disconnected = True
                print(f"[{cycle}] Disconnected")

                # ===== Spam M1 while disconnected (configurable) =====
                throw_count = self.throw_dc_count_var.get()
                throw_delay = self.throw_dc_delay_var.get() / 1000.0 / 2  # Split between down and up
                print(f"[{cycle}] Throwing {throw_count}x with {self.throw_dc_delay_var.get()}ms between")
                for i in range(throw_count):
                    if self.throwable_stop:
                        break
                    pynput_mouse.press(MouseButton.left)
                    time.sleep(throw_delay)
                    pynput_mouse.release(MouseButton.left)
                    time.sleep(throw_delay)

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
                    time.sleep(0.050)
                    pynput_mouse.release(MouseButton.left)
                    time.sleep(0.050)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED during M1 spam after reconnect")
                    break

                # ===== Wait before E (configurable) =====
                wait_before_e_ms = self.throw_wait_before_e_var.get()
                wait_after_e_ms = self.throw_wait_after_e_var.get()
                wait_after_q_ms = self.throw_wait_after_q_var.get()

                print(f"[{cycle}] Waiting {wait_before_e_ms}ms before E...")
                time.sleep(wait_before_e_ms / 1000.0)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED before E")
                    break

                # ===== E (pickup) =====
                pynput_keyboard.press('e')
                time.sleep(0.050)
                pynput_keyboard.release('e')
                print(f"[{cycle}] E pressed, waiting {wait_after_e_ms}ms...")
                time.sleep(wait_after_e_ms / 1000.0)

                if self.throwable_stop:
                    print(f"[{cycle}] STOPPED before Q")
                    break

                # ===== Q (re-equip) =====
                pynput_keyboard.press('q')
                time.sleep(0.050)
                pynput_keyboard.release('q')
                print(f"[{cycle}] Q pressed, waiting {wait_after_q_ms}ms...")
                time.sleep(wait_after_q_ms / 1000.0)

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
                m1_hold = self.trig_m1_hold_var.get() / 1000.0
                m2_hold = self.trig_m2_hold_var.get() / 1000.0

                pynput_mouse.press(MouseButton.left)
                time.sleep(m1_hold)

                # ===== Right click during throw (configurable) =====
                pynput_mouse.press(MouseButton.right)
                time.sleep(m2_hold)
                pynput_mouse.release(MouseButton.right)
                print(f"[{cycle}] Throw (M1:{int(m1_hold*1000)}ms) + M2:{int(m2_hold*1000)}ms")

                pynput_mouse.release(MouseButton.left)

                # ===== E key 11ms =====
                pynput_keyboard.press('e')
                time.sleep(0.011)
                pynput_keyboard.release('e')
                print(f"[{cycle}] E pressed")

                # ===== Disconnect (outbound only for triggernade) =====
                start_packet_drop(inbound=False)
                is_disconnected = True
                time.sleep(0.051)
                print(f"[{cycle}] Disconnected (outbound only)")

                if self.triggernade_stop:
                    break

                # ===== TAB to open inventory 51ms =====
                time.sleep(0.020)
                pynput_keyboard.press(Key.tab)
                time.sleep(0.301)
                pynput_keyboard.release(Key.tab)
                print(f"[{cycle}] Inventory opened")

                if self.triggernade_stop:
                    break

                # ===== Wait then drop (uses recorded timing) =====
                if self.use_drag_drop_var.get():
                    # Drag fallback using pynput
                    time.sleep(0.12)  # Wait for inventory to open

                    # Clear any stuck mouse state first
                    pynput_mouse.release(MouseButton.left)

                    # Move to start position
                    pynput_mouse.position = self.trig_drag_start
                    time.sleep(0.03)

                    # Press and drag
                    pynput_mouse.press(MouseButton.left)
                    time.sleep(0.08)  # Click registers

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
                        time.sleep(0.007)

                    pynput_mouse.release(MouseButton.left)
                    print(f"[{cycle}] Dropped with drag: {self.trig_drag_start} → {self.trig_drag_end}")
                else:
                    # Xbox X button - uses original hardcoded timing
                    time.sleep(0.300)  # Wait before drop
                    x_hold_ms = self.keydoor_x_hold_var.get()
                    pynput_mouse.position = self.trig_drag_start
                    time.sleep(0.020)
                    gp = get_gamepad()
                    if gp:
                        gp.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                        gp.update()
                        time.sleep(x_hold_ms / 1000.0)
                        gp.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
                        gp.update()
                        print(f"[{cycle}] Dropped with X ({x_hold_ms}ms)")
                    else:
                        print(f"[{cycle}] ERROR: No gamepad for X drop")

                if self.triggernade_stop:
                    break

                # ===== Wait then TAB close =====
                time.sleep(self.drag_wait_after / 1000.0)

                pynput_keyboard.press(Key.tab)
                time.sleep(0.051)
                pynput_keyboard.release(Key.tab)
                print(f"[{cycle}] Inventory closed")

                if self.triggernade_stop:
                    break

                # ===== Wait 300ms then M1 spam =====
                time.sleep(0.300)

                # Get configurable values
                total_throws = self.trig_dc_throws_var.get()
                throw_delay = self.trig_throw_delay_var.get() / 1000.0
                reconnect_after = self.trig_reconnect_after_var.get()

                # Clamp reconnect_after to be within valid range
                reconnect_after = min(reconnect_after, total_throws)
                print(f"[{cycle}] M1 spam: {total_throws} throws, reconnect after #{reconnect_after}")

                # ===== M1 spam with reconnect, then interleaved E+M1 =====
                # Phase 1: First 5 M1s (reconnect after #1)
                for i in range(5):
                    if self.triggernade_stop:
                        break

                    pynput_mouse.press(MouseButton.left)
                    time.sleep(throw_delay / 2)
                    pynput_mouse.release(MouseButton.left)

                    # Reconnect after specified throw number
                    if i + 1 == reconnect_after and is_disconnected:
                        time.sleep(0.021)
                        stop_packet_drop()
                        is_disconnected = False
                        print(f"[{cycle}] Reconnected after M1 #{i+1}")
                        time.sleep(0.059)  # Wait after reconnect before next M1
                    else:
                        time.sleep(throw_delay / 2)

                # Safety: ensure we're reconnected
                if is_disconnected:
                    stop_packet_drop()
                    is_disconnected = False

                if self.triggernade_stop:
                    break

                # Phase 2: Interleaved E spam + M1 throws (like the recording)
                # E every ~22ms, M1 every ~100ms = about 4-5 E's per M1
                remaining_throws = max(0, total_throws - 5)
                print(f"[{cycle}] Interleaved E+M1: {remaining_throws} more M1s with E spam")

                for i in range(remaining_throws):
                    if self.triggernade_stop:
                        break

                    # M1 throw
                    pynput_mouse.press(MouseButton.left)

                    # E spam during M1 hold (~50ms hold, fit 2 E's)
                    for _ in range(2):
                        pynput_keyboard.press('e')
                        time.sleep(0.006)
                        pynput_keyboard.release('e')
                        time.sleep(0.016)

                    pynput_mouse.release(MouseButton.left)

                    # E spam between M1s (~50ms gap, fit 2-3 E's)
                    for _ in range(2):
                        if self.triggernade_stop:
                            break
                        pynput_keyboard.press('e')
                        time.sleep(0.006)
                        pynput_keyboard.release('e')
                        time.sleep(0.016)

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
                    time.sleep(0.006)
                    pynput_keyboard.release('e')
                    time.sleep(0.016)  # ~22ms per E press

                # If single cycle (not repeat), skip Q spam and exit
                if not repeat:
                    print(f"[{cycle}] Single cycle done - E pickup complete")
                    break

                if self.triggernade_stop:
                    break

                # Q spam to ready next throw
                for _ in range(5):
                    pynput_keyboard.press('q')
                    time.sleep(0.011)
                    pynput_keyboard.release('q')
                    time.sleep(0.011)
                print(f"[{cycle}] Q spam done")

                # Wait before next cycle (configurable)
                if wait_before_cycle_ms > 0:
                    cycle_wait_iterations = max(1, wait_before_cycle_ms // 50)
                    print(f"[{cycle}] Waiting {wait_before_cycle_ms}ms before next cycle...")
                    for _ in range(cycle_wait_iterations):
                        if self.triggernade_stop:
                            break
                        time.sleep(0.050)


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
                time.sleep(0.011)
                kb.release('e')
                time.sleep(0.050)

                # If repeat delay > 0, pause between spam bursts
                if repeat_delay > 0 and not self.espam_stop:
                    # Wait for repeat delay (check stop flag periodically)
                    waited = 0
                    while waited < repeat_delay and not self.espam_stop:
                        time.sleep(0.1)
                        waited += 0.1
        finally:
            self.espam_running = False
            self.espam_stop = False
            self.root.after(0, lambda: self.espam_status_var.set("Ready"))
            self.root.after(0, lambda: self.espam_status_label.config(foreground="gray"))
            self.root.after(0, lambda: self.show_overlay("E-Spam stopped."))

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
    print("Quick Dupe Starting...")

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
