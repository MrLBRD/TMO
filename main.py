from __future__ import annotations

__version__ = "1.0.2"

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import threading
import sys
from typing import Callable
import webbrowser
from urllib.parse import urljoin

from tkinter import filedialog
import tkinter as tk

import customtkinter as ctk
from PIL import Image
from customtkinter import CTkImage
import cv2

from core.config import AppConfig, load_config, save_config, resolve_output_dir, check_if_just_updated, set_last_run_version
from core.network import send_status
from core.recorder import Recorder, RecorderEvent, list_cameras
from core.storage import clean_old_videos, disk_free_bytes, ensure_dir, format_bytes, is_valid_order_id, sanitize_order_id
from core.updater import UpdateInfo, check_for_updates_async, download_update, run_installer

DISPLAY_WIDTH = 960
DISPLAY_HEIGHT = 540

DISK_WARN_FREE_BYTES = 10 * 1024 * 1024 * 1024
DISK_CRIT_FREE_BYTES = 2 * 1024 * 1024 * 1024

# Chrome path cache for faster URL opening
_chrome_path_cache: str | None = None
_chrome_path_checked: bool = False


def _get_chrome_path() -> str | None:
    """Get Chrome executable path (cached for performance)."""
    global _chrome_path_cache, _chrome_path_checked
    if _chrome_path_checked:
        return _chrome_path_cache

    _chrome_path_checked = True
    if os.name != "nt":
        return None

    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            _chrome_path_cache = path
            return _chrome_path_cache
    return None


def resource_path(rel: str) -> str:
    """
    Return absolute path to resource, working for dev and PyInstaller (--onefile).
    """
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return str(Path(base) / rel)


class ConfigWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        config: AppConfig,
        on_apply: Callable[[AppConfig], None],
    ) -> None:
        super().__init__(parent)

        self._on_apply = on_apply
        self._initial_config = config

        self.title("Configuration")
        self.geometry("560x520")

        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Camera index").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        self.camera_var = tk.StringVar(value=str(config.camera_index))
        self.camera_menu = ctk.CTkOptionMenu(self, variable=self.camera_var, values=[str(config.camera_index)])
        self.camera_menu.grid(row=0, column=1, sticky="ew", padx=12, pady=(12, 6))
        self.refresh_button = ctk.CTkButton(self, text="Rafraîchir", command=self._refresh_cameras)
        self.refresh_button.grid(row=0, column=2, sticky="e", padx=(0, 12), pady=(12, 6))

        ctk.CTkLabel(self, text="Flip caméra").grid(
            row=1, column=0, sticky="w", padx=12, pady=6
        )
        self.flip_var = tk.StringVar(value=(config.camera_flip or "none"))
        self.flip_menu = ctk.CTkOptionMenu(
            self,
            variable=self.flip_var,
            values=["none", "horizontal", "vertical", "both"],
        )
        self.flip_menu.grid(row=1, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(self, text="Dossier vidéos").grid(
            row=2, column=0, sticky="w", padx=12, pady=6
        )
        self.output_entry = ctk.CTkEntry(self)
        self.output_entry.insert(0, config.output_dir)
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=12, pady=6)
        ctk.CTkButton(self, text="Choisir", command=self._browse_output_dir).grid(
            row=2, column=2, sticky="e", padx=(0, 12), pady=6
        )

        ctk.CTkLabel(self, text="Rétention (jours)").grid(
            row=3, column=0, sticky="w", padx=12, pady=6
        )
        self.retention_entry = ctk.CTkEntry(self)
        self.retention_entry.insert(0, str(config.retention_days))
        self.retention_entry.grid(row=3, column=1, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(self, text="Site").grid(
            row=4, column=0, sticky="w", padx=12, pady=6
        )
        self.site_entry = ctk.CTkEntry(self)
        self.site_entry.insert(0, config.site_url)
        self.site_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        # Chrome status indicator
        ctk.CTkLabel(self, text="Chrome").grid(
            row=5, column=0, sticky="w", padx=12, pady=6
        )
        self.chrome_status_label = ctk.CTkLabel(self, text="Détection...", anchor="w")
        self.chrome_status_label.grid(row=5, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        # Separator
        separator = ctk.CTkFrame(self, height=2, fg_color="#3f3f46")
        separator.grid(row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=12)

        # Version and update section
        ctk.CTkLabel(self, text="Version").grid(
            row=7, column=0, sticky="w", padx=12, pady=6
        )
        self.version_label = ctk.CTkLabel(self, text=f"v{__version__}", anchor="w")
        self.version_label.grid(row=7, column=1, sticky="w", padx=12, pady=6)
        self.update_button = ctk.CTkButton(
            self, text="Vérifier MAJ", width=100, command=self._check_for_updates
        )
        self.update_button.grid(row=7, column=2, sticky="e", padx=12, pady=6)

        self.update_status_label = ctk.CTkLabel(self, text="", anchor="w")
        self.update_status_label.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))

        self.error_label = ctk.CTkLabel(self, text="", text_color="#ef4444", anchor="w")
        self.error_label.grid(row=9, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 0))

        buttons = ctk.CTkFrame(self)
        buttons.grid(row=10, column=0, columnspan=3, sticky="ew", padx=12, pady=12)
        buttons.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(buttons, text="Annuler", command=self._on_cancel).grid(
            row=0, column=1, padx=(6, 0), pady=0
        )
        ctk.CTkButton(buttons, text="Enregistrer", command=self._on_save).grid(
            row=0, column=2, padx=(6, 0), pady=0
        )

        self.grab_set()
        self._camera_refreshing = False
        self.after(10, lambda: self._refresh_cameras_async(max_index=10))
        self.after(50, self._detect_chrome)

        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        try:
            self.lift()
        except Exception:
            pass

    def _detect_chrome(self) -> None:
        try:
            if os.name == "nt":
                possible_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        self.chrome_status_label.configure(text=f"✓ Trouvé : {path}", text_color="#10b981")
                        return
                self.chrome_status_label.configure(text="✗ Non trouvé (utilisera navigateur par défaut)", text_color="#f59e0b")
            else:
                self.chrome_status_label.configure(text="Non Windows", text_color="#9ca3af")
        except Exception:
            self.chrome_status_label.configure(text="Erreur détection", text_color="#9ca3af")

    def _check_for_updates(self) -> None:
        """Check for updates in background."""
        self.update_button.configure(state="disabled", text="Vérification...")
        self.update_status_label.configure(text="Connexion à GitHub...", text_color="#9ca3af")

        def on_result(info: UpdateInfo) -> None:
            self.after(0, lambda: self._handle_update_result(info))

        check_for_updates_async(__version__, on_result)

    def _handle_update_result(self, info: UpdateInfo) -> None:
        """Handle update check result."""
        if not self.winfo_exists():
            return

        if info.error:
            self.update_status_label.configure(
                text=f"Erreur: {info.error}", text_color="#ef4444"
            )
            self.update_button.configure(state="normal", text="Vérifier MAJ")
            return

        if info.available and info.latest_version:
            self.update_status_label.configure(
                text=f"Nouvelle version disponible: v{info.latest_version}",
                text_color="#10b981",
            )
            if info.download_url:
                self._pending_download_url = info.download_url
                self.update_button.configure(
                    state="normal",
                    text="Télécharger",
                    command=self._download_update,
                )
            else:
                self.update_status_label.configure(
                    text=f"v{info.latest_version} disponible (téléchargez sur GitHub)",
                    text_color="#f59e0b",
                )
                self.update_button.configure(state="normal", text="Vérifier MAJ")
        else:
            self.update_status_label.configure(
                text=f"Vous êtes à jour (v{__version__})", text_color="#10b981"
            )
            self.update_button.configure(state="normal", text="Vérifier MAJ")

    def _download_update(self) -> None:
        """Download and install update."""
        url = getattr(self, "_pending_download_url", None)
        if not url:
            return

        self.update_button.configure(state="disabled", text="Téléchargement...")
        self.update_status_label.configure(text="Téléchargement en cours...", text_color="#9ca3af")

        def progress_callback(downloaded: int, total: int) -> None:
            if total > 0:
                percent = int((downloaded / total) * 100)
                self.after(0, lambda p=percent: self._update_download_progress(p))

        def do_download() -> None:
            success, result = download_update(url, progress_callback)
            self.after(0, lambda: self._handle_download_result(success, result))

        threading.Thread(target=do_download, name="tmo_download_update", daemon=True).start()

    def _update_download_progress(self, percent: int) -> None:
        """Update download progress in UI."""
        if not self.winfo_exists():
            return
        self.update_status_label.configure(text=f"Téléchargement: {percent}%")

    def _handle_download_result(self, success: bool, result: str) -> None:
        """Handle download completion."""
        if not self.winfo_exists():
            return

        if success:
            self.update_status_label.configure(
                text="Téléchargement terminé. Lancement de l'installation...",
                text_color="#10b981",
            )
            self.update_button.configure(state="disabled", text="Installation...")

            # Launch installer after short delay
            self.after(500, lambda: self._run_installer(result))
        else:
            self.update_status_label.configure(
                text=f"Échec: {result}", text_color="#ef4444"
            )
            self.update_button.configure(
                state="normal", text="Réessayer", command=self._download_update
            )

    def _run_installer(self, installer_path: str) -> None:
        """Run the installer and exit."""
        success, error = run_installer(installer_path)
        if success:
            self.update_status_label.configure(
                text="Fermeture de l'application...", text_color="#10b981"
            )
            # Exit application after installer starts
            self.after(1000, lambda: sys.exit(0))
        else:
            self.update_status_label.configure(
                text=f"Erreur: {error}", text_color="#ef4444"
            )
            self.update_button.configure(state="normal", text="Vérifier MAJ")

    def _refresh_cameras(self) -> None:
        self._refresh_cameras_async(max_index=20)

    def _refresh_cameras_async(self, max_index: int = 20) -> None:
        if getattr(self, "_camera_refreshing", False):
            return

        self._camera_refreshing = True
        try:
            self.refresh_button.configure(state="disabled")
        except Exception:
            pass

        def _work() -> None:
            cameras = list_cameras(max_index=max_index)
            self.after(0, lambda: self._apply_camera_list(cameras))

        threading.Thread(target=_work, name="tmo_list_cameras", daemon=True).start()

    def _apply_camera_list(self, cameras: list[tuple[int, int | None, int | None]]) -> None:
        # Check if window still exists
        if not self.winfo_exists():
            return

        values: list[str] = []
        for idx, w, h in cameras:
            if w is not None and h is not None:
                values.append(f"{idx} ({w}x{h})")
            else:
                values.append(str(idx))

        current = self.camera_var.get().strip()
        if not values:
            values = [current or str(self._initial_config.camera_index)]

        current_idx: int | None = None
        if current:
            try:
                current_idx = int(current.split()[0])
            except ValueError:
                current_idx = None

        selected = None
        if current_idx is not None:
            for v in values:
                try:
                    if int(v.split()[0]) == current_idx:
                        selected = v
                        break
                except ValueError:
                    continue

        if selected is None:
            selected = values[0]

        try:
            self.camera_menu.configure(values=values)
            self.camera_var.set(selected)
        except Exception:
            pass

        self._camera_refreshing = False
        try:
            self.refresh_button.configure(state="normal")
        except Exception:
            pass

    def _browse_output_dir(self) -> None:
        initial = str(resolve_output_dir(self._initial_config))
        selected = filedialog.askdirectory(initialdir=initial)
        if not selected:
            return
        self.output_entry.delete(0, "end")
        self.output_entry.insert(0, selected)

    def _on_cancel(self) -> None:
        self.destroy()

    def _on_save(self) -> None:
        self.error_label.configure(text="")

        try:
            camera_index = int((self.camera_var.get().strip().split() or ["0"])[0])
        except ValueError:
            self.error_label.configure(text="Camera index invalide")
            return

        try:
            retention_days = int(self.retention_entry.get().strip() or "45")
        except ValueError:
            self.error_label.configure(text="Rétention invalide")
            return

        if retention_days <= 0:
            self.error_label.configure(text="La rétention doit être > 0")
            return

        cfg = AppConfig(
            camera_index=camera_index,
            camera_flip=self.flip_var.get().strip(),
            output_dir=self.output_entry.get().strip(),
            retention_days=retention_days,
            api_url=self._initial_config.api_url,
            site_url=self.site_entry.get().strip(),
            api_key=self._initial_config.api_key,
        )

        self._on_apply(cfg)
        self.destroy()


class OverlayWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        on_start: Callable[[str], None],
        on_stop: Callable[[], None],
    ) -> None:
        super().__init__(parent)

        self._start_cb = on_start
        self._stop_cb = on_stop

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._win_start_x = 0
        self._win_start_y = 0
        self._clickthrough_enabled = False

        self.title("TMO")
        self.geometry("200x70+20+20")
        self.resizable(False, False)

        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        try:
            self.attributes("-alpha", 0.92)
        except Exception:
            pass
        try:
            self.overrideredirect(True)
        except Exception:
            pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        body = ctk.CTkFrame(self)
        body.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        body.grid_columnconfigure(1, weight=1)

        self._dot = ctk.CTkLabel(body, text="●", text_color="#9ca3af", width=32, font=("Arial", 24, "bold"))
        self._dot.grid(row=0, column=0, sticky="w", padx=(8, 6), pady=(8, 0))

        self.status_label = ctk.CTkLabel(body, text="PRÊT", anchor="w", font=("Arial", 24, "bold"), text_color="#d1d5db")
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))

        self.order_id_label = ctk.CTkLabel(body, text="", anchor="w", font=("Arial", 13, "bold"))
        self.order_id_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        body.bind("<ButtonPress-1>", self._start_move)
        body.bind("<B1-Motion>", self._do_move)
        self._dot.bind("<ButtonPress-1>", self._start_move)
        self._dot.bind("<B1-Motion>", self._do_move)
        self.status_label.bind("<ButtonPress-1>", self._start_move)
        self.status_label.bind("<B1-Motion>", self._do_move)
        self.order_id_label.bind("<ButtonPress-1>", self._start_move)
        self.order_id_label.bind("<B1-Motion>", self._do_move)

        try:
            self.lift()
        except Exception:
            pass

        if os.name == "nt":
            self.after(120, self._clickthrough_loop)

    def set_status(self, text: str) -> None:
        t = str(text or "").strip()
        order_id: str | None = None
        try:
            # Only extract order ID from "Enregistrement en cours : XXXXX" format
            if "Enregistrement en cours" in t and ":" in t:
                candidate = t.split(":")[-1].strip()
                candidate = sanitize_order_id(candidate)
                if is_valid_order_id(candidate):
                    order_id = candidate
        except Exception:
            order_id = None

        try:
            if order_id:
                # Mode enregistrement : Rouge vif + texte clair
                self._dot.configure(text_color="#ef4444")
                self.status_label.configure(text="REC", text_color="#ef4444")
                self.order_id_label.configure(text=f"📦 {order_id}", text_color="#fecaca")
            else:
                # Mode prêt : Gris + texte normal
                self._dot.configure(text_color="#9ca3af")
                self.status_label.configure(text="PRÊT", text_color="#d1d5db")
                self.order_id_label.configure(text="", text_color="#9ca3af")
        except Exception:
            return

    def set_qr_debug(self, text: str) -> None:
        return

    def _start_move(self, event) -> None:
        try:
            self._drag_start_x = int(event.x_root)
            self._drag_start_y = int(event.y_root)
            self._win_start_x = int(self.winfo_x())
            self._win_start_y = int(self.winfo_y())
        except Exception:
            return

    def _do_move(self, event) -> None:
        try:
            dx = int(event.x_root) - self._drag_start_x
            dy = int(event.y_root) - self._drag_start_y
            self.geometry(f"+{self._win_start_x + dx}+{self._win_start_y + dy}")
        except Exception:
            return

    def _set_clickthrough(self, enabled: bool) -> None:
        if os.name != "nt":
            return

        try:
            hwnd = int(self.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            LWA_ALPHA = 0x00000002
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            GA_ROOT = 2
            root_hwnd = 0
            try:
                root_hwnd = int(ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or 0)
            except Exception:
                root_hwnd = 0

            targets: list[int] = [hwnd]
            if root_hwnd and root_hwnd != hwnd:
                targets.append(root_hwnd)

            alpha = 235
            try:
                current_alpha = float(self.attributes("-alpha"))
                alpha = max(1, min(255, int(round(current_alpha * 255))))
            except Exception:
                alpha = 235

            for target in targets:
                ex_style = int(ctypes.windll.user32.GetWindowLongW(target, GWL_EXSTYLE))
                want_layered = True
                want_transparent = bool(enabled)

                has_layered = bool(ex_style & WS_EX_LAYERED)
                has_transparent = bool(ex_style & WS_EX_TRANSPARENT)
                needs_update = (has_layered != want_layered) or (has_transparent != want_transparent)
                if not needs_update and enabled == self._clickthrough_enabled:
                    continue

                new_style = int(ex_style) | WS_EX_LAYERED
                if enabled:
                    new_style |= WS_EX_TRANSPARENT
                else:
                    new_style &= ~WS_EX_TRANSPARENT

                try:
                    ctypes.windll.user32.SetWindowLongW(target, GWL_EXSTYLE, int(new_style))
                except Exception:
                    continue

                try:
                    ctypes.windll.user32.SetLayeredWindowAttributes(target, 0, int(alpha), LWA_ALPHA)
                except Exception:
                    pass
                try:
                    ctypes.windll.user32.SetWindowPos(
                        target,
                        0,
                        0,
                        0,
                        0,
                        0,
                        SWP_NOMOVE
                        | SWP_NOSIZE
                        | SWP_NOZORDER
                        | SWP_FRAMECHANGED
                        | SWP_NOACTIVATE,
                    )
                except Exception:
                    pass
            self._clickthrough_enabled = enabled
        except Exception:
            return

    def _clickthrough_loop(self) -> None:
        if os.name != "nt":
            return
        if not self.winfo_exists():
            return

        try:
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            x0 = int(self.winfo_rootx())
            y0 = int(self.winfo_rooty())
            w = int(self.winfo_width())
            h = int(self.winfo_height())

            inside = (x0 <= int(pt.x) <= (x0 + w)) and (y0 <= int(pt.y) <= (y0 + h))
            ctrl_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)

            self._set_clickthrough(enabled=not (inside and ctrl_down))
        except Exception:
            pass

        try:
            self.after(50, self._clickthrough_loop)
        except Exception:
            return


class TmoApp(ctk.CTk):
    def __init__(self, recorder: Recorder, config: AppConfig) -> None:
        super().__init__()

        self.recorder = recorder
        self.config = config
        self.api_url = config.api_url.strip() or None
        self.site_url = config.site_url.strip() or None
        self.api_key = config.api_key.strip() or None

        self.title("TMO")
        self.geometry("1024x720")
        self.after(150, self._bring_to_front)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(self, text="")
        self.video_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        bottom = ctk.CTkFrame(self)
        bottom.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=0)
        bottom.grid_columnconfigure(2, weight=0)

        self.status_label = ctk.CTkLabel(bottom, text="", anchor="w")
        self.status_label.grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6)
        )

        self.config_button = ctk.CTkButton(
            bottom,
            text="CONFIG",
            width=90,
            command=self._on_config_clicked,
        )
        self.config_button.grid(row=0, column=2, sticky="e", padx=12, pady=(12, 6))

        self.qr_debug_label = ctk.CTkLabel(bottom, text="", anchor="w")
        self.qr_debug_label.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))

        self.manual_entry = ctk.CTkEntry(
            bottom,
            placeholder_text="ID commande",
        )
        self.manual_entry.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.start_button = ctk.CTkButton(
            bottom,
            text="START",
            fg_color="#15803d",
            hover_color="#166534",
            width=90,
            command=self._on_start_clicked,
        )
        self.start_button.grid(row=2, column=1, sticky="e", padx=(0, 12), pady=(0, 12))

        self.stop_button = ctk.CTkButton(
            bottom,
            text="STOP",
            fg_color="#b91c1c",
            hover_color="#991b1b",
            width=90,
            command=self._on_stop_clicked,
        )
        self.stop_button.grid(row=2, column=2, sticky="e", padx=12, pady=(0, 12))

        self.disk_label = ctk.CTkLabel(bottom, text="", anchor="w")
        self.disk_label.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))

        self._photo: CTkImage | None = None
        self._config_window: ConfigWindow | None = None
        self._disk_check_after_id: str | None = None
        self._overlay_window: OverlayWindow | None = None
        self._closing: bool = False

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._set_status(self._ready_status_text())
        self._set_qr_debug("")
        self._update_disk_label()
        self._schedule_disk_check()

        try:
            self._overlay_window = OverlayWindow(
                parent=self,
                on_start=self._start_from_raw,
                on_stop=self._on_stop_clicked,
            )
            self._overlay_window.set_status(self.status_label.cget("text"))
        except Exception:
            self._overlay_window = None

        self.after(10, self._update_frame)
        self.after(100, self._poll_events)

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)
        if self._overlay_window is not None and self._overlay_window.winfo_exists():
            try:
                self._overlay_window.set_status(text)
            except Exception:
                pass

    def _set_qr_debug(self, text: str) -> None:
        self.qr_debug_label.configure(text=text)
        if self._overlay_window is not None and self._overlay_window.winfo_exists():
            try:
                self._overlay_window.set_qr_debug(text)
            except Exception:
                pass

    def _bring_to_front(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _update_disk_label(self) -> None:
        free = disk_free_bytes(self.recorder.output_dir)
        if free is None:
            self.disk_label.configure(text="Disque: inconnu")
            return

        text = f"Disque: {format_bytes(free)} libres"
        color: str | None
        if free < DISK_CRIT_FREE_BYTES:
            color = "#ef4444"
        elif free < DISK_WARN_FREE_BYTES:
            color = "#f59e0b"
        else:
            color = None

        if color is None:
            self.disk_label.configure(text=text)
        else:
            self.disk_label.configure(text=text, text_color=color)

    def _schedule_disk_check(self) -> None:
        if self._disk_check_after_id is not None:
            try:
                self.after_cancel(self._disk_check_after_id)
            except Exception:
                pass
            self._disk_check_after_id = None

        self._disk_check_after_id = self.after(5000, self._on_disk_check_timer)

    def _on_disk_check_timer(self) -> None:
        self._update_disk_label()
        self._disk_check_after_id = self.after(5000, self._on_disk_check_timer)

    def _update_frame(self) -> None:
        if self._closing:
            return

        frame = self.recorder.get_latest_frame()
        if frame is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                resized = cv2.resize(rgb, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
                img = Image.fromarray(resized)
                self._photo = CTkImage(light_image=img, dark_image=img, size=(DISPLAY_WIDTH, DISPLAY_HEIGHT))
                self.video_label.configure(image=self._photo)
            except Exception:
                pass

        if not self._closing:
            self.after(33, self._update_frame)  # ~30fps display refresh

    def _poll_events(self) -> None:
        if self._closing:
            return

        try:
            while True:
                ev = self.recorder.events.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass

        if not self._closing:
            self.after(20, self._poll_events)  # 20ms for faster event response

    def _handle_event(self, ev: RecorderEvent) -> None:
        if ev.type == "recording_started" and ev.order_id:
            self._set_status(f"Enregistrement en cours : {ev.order_id}")
            self.update_idletasks()
            self._send_status_async(ev.order_id, "video_started")
            self._open_order_modal(ev.order_id)

        elif ev.type == "recording_stopped" and ev.order_id:
            self._set_status(self._ready_status_text())
            self._send_status_async(ev.order_id, "video_stopped")

        elif ev.type == "error":
            if ev.message:
                self._set_status(f"Erreur : {ev.message}")
            else:
                self._set_status("Erreur")

        elif ev.type == "qr_detected":
            raw = (ev.message or "").strip()
            if not raw:
                return
            if ev.order_id:
                self._set_qr_debug(f"QR: {raw} -> {ev.order_id}")
            else:
                self._set_qr_debug(f"QR: {raw} (invalide)")

    def _ready_status_text(self) -> str:
        if not self.recorder.qr_available:
            return "Prêt (QR indisponible)"
        backend = self.recorder.qr_backend
        if backend:
            return f"Prêt (QR: {backend})"
        return "Prêt"

    def _send_status_async(self, order_id: str, status: str) -> None:
        def _work() -> None:
            ok, _ = send_status(
                api_url=self.api_url,
                site_url=self.site_url,
                api_key=self.api_key,
                order_id=order_id,
                status=status,
            )
            if not ok:
                self.after(0, self._handle_network_error)

        threading.Thread(target=_work, name="tmo_network", daemon=True).start()

    def _handle_network_error(self) -> None:
        self._set_status("Erreur Réseau")
        self.after(2000, self._restore_recording_status)

    def _restore_recording_status(self) -> None:
        order_id = self.recorder.recording_order_id
        if order_id:
            self._set_status(f"Enregistrement en cours : {order_id}")
        else:
            self._set_status(self._ready_status_text())

    def _start_from_raw(self, raw: str) -> None:
        raw = str(raw or "").strip()
        if raw.lower().startswith("tk-"):
            raw = raw[3:].strip()
        safe_id = sanitize_order_id(raw)
        if not is_valid_order_id(safe_id):
            self._set_status("ID commande invalide")
            return

        current = self.recorder.recording_order_id
        if current == safe_id:
            return

        if current is not None:
            self.recorder.stop_recording(wait=False)

        self.recorder.start_recording(safe_id)

    def _on_start_clicked(self) -> None:
        self._start_from_raw(self.manual_entry.get())

    def _on_config_clicked(self) -> None:
        if self._config_window is not None and self._config_window.winfo_exists():
            try:
                self._config_window.lift()
                self._config_window.focus_force()
            except Exception:
                self._config_window.focus()
            return

        self._config_window = ConfigWindow(
            parent=self,
            config=self.config,
            on_apply=self._apply_config,
        )
        try:
            self._config_window.lift()
            self._config_window.focus_force()
        except Exception:
            self._config_window.focus()

    def _apply_config(self, cfg: AppConfig) -> None:
        save_config(cfg)

        self.config = cfg
        self.api_url = cfg.api_url.strip() or None
        self.site_url = cfg.site_url.strip() or None
        self.api_key = cfg.api_key.strip() or None

        output_dir = resolve_output_dir(cfg)
        ensure_dir(output_dir)
        clean_old_videos(output_dir=output_dir, retention_days=cfg.retention_days)

        try:
            self.recorder.stop()
        except Exception:
            pass

        self.recorder = Recorder(
            camera_index=cfg.camera_index,
            camera_flip=cfg.camera_flip,
            output_dir=output_dir,
        )
        self.recorder.start()
        try:
            self.manual_entry.configure(placeholder_text="ID commande")
        except Exception:
            pass
        self._set_status(self._ready_status_text())
        self._update_disk_label()

    def _on_stop_clicked(self) -> None:
        self.recorder.stop_recording(wait=False)

    def _on_close(self) -> None:
        self._closing = True
        try:
            if self._disk_check_after_id is not None:
                try:
                    self.after_cancel(self._disk_check_after_id)
                except Exception:
                    pass
            self.recorder.stop()
        finally:
            self.destroy()

    def _open_order_modal(self, order_id: str) -> None:
        base = (self.site_url or "").strip()
        if not base:
            self._set_qr_debug("URL du site non configurée")
            return
        try:
            url = urljoin(base if base.endswith("/") else base + "/", f"wp-admin/admin.php?page=wc-better-management&orderCheck={order_id}")
        except Exception:
            url = f"{base.rstrip('/')}/wp-admin/admin.php?page=wc-better-management&orderCheck={order_id}"

        def _open_browser() -> None:
            try:
                chrome_path = _get_chrome_path()  # Use cached path for performance
                if chrome_path:
                    webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(chrome_path))
                    webbrowser.get('chrome').open_new_tab(url)
                else:
                    webbrowser.open_new_tab(url)
            except Exception:
                self.after(0, lambda: self._set_qr_debug(f"Ouverture navigateur échouée pour {url}"))

        threading.Thread(target=_open_browser, name="tmo_browser", daemon=True).start()


def _show_extension_reload_notice(parent: ctk.CTk) -> None:
    """Show a dialog reminding user to reload the Chrome extension after update."""
    dialog = ctk.CTkToplevel(parent)
    dialog.title("Extension mise à jour")
    dialog.geometry("420x180")
    dialog.resizable(False, False)
    dialog.grab_set()

    try:
        dialog.attributes("-topmost", True)
    except Exception:
        pass

    dialog.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        dialog,
        text="🔄 L'application a été mise à jour !",
        font=("Arial", 16, "bold"),
    ).grid(row=0, column=0, padx=20, pady=(20, 10))

    ctk.CTkLabel(
        dialog,
        text="Pensez à recharger l'extension Chrome :\n"
             "1. Ouvrir chrome://extensions\n"
             "2. Cliquer sur 🔄 à côté de \"TMO Woo Admin Cleaner\"",
        justify="left",
    ).grid(row=1, column=0, padx=20, pady=10)

    ctk.CTkButton(
        dialog,
        text="Compris",
        command=dialog.destroy,
    ).grid(row=2, column=0, padx=20, pady=(10, 20))

    dialog.lift()


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    # Check if app was just updated
    just_updated = check_if_just_updated(__version__)
    set_last_run_version(__version__)

    cfg = load_config()
    output_dir = resolve_output_dir(cfg)

    ensure_dir(output_dir)
    clean_old_videos(output_dir=output_dir, retention_days=cfg.retention_days)

    recorder = Recorder(
        camera_index=cfg.camera_index,
        camera_flip=cfg.camera_flip,
        output_dir=output_dir,
    )
    recorder.start()

    app = TmoApp(recorder=recorder, config=cfg)

    # Show extension reload notice after update
    if just_updated:
        app.after(500, lambda: _show_extension_reload_notice(app))

    app.mainloop()


if __name__ == "__main__":
    main()
