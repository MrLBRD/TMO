from __future__ import annotations

__version__ = "1.2.0"

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import threading
import time
import sys
from typing import Callable
import webbrowser

from tkinter import filedialog
import tkinter as tk

import customtkinter as ctk
from PIL import Image
from customtkinter import CTkImage
import cv2

from core.config import AppConfig, load_config, log_path, save_config, resolve_output_dir, check_if_just_updated, set_last_run_version
from core.logging_setup import setup_logging
from core.recorder import Recorder, RecorderEvent, list_cameras
from core.storage import clean_old_videos, disk_free_bytes, ensure_dir, format_bytes, is_valid_order_id, sanitize_order_id
from core.updater import UpdateInfo, check_for_updates_async, download_update, run_installer

import logging
log = logging.getLogger(__name__)

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
        recorder: "Recorder",
    ) -> None:
        super().__init__(parent)

        self._on_apply = on_apply
        self._initial_config = config
        self._recorder = recorder
        self._preview_photo: CTkImage | None = None
        self._preview_after_id: str | None = None
        recorder.pause_qr(True)

        self.title("Configuration")
        self.geometry("680x700")

        # Buttons + error always visible at the bottom (outside the scroll)
        # Pack order with side="bottom": first packed = lowest position
        _btn_bar = ctk.CTkFrame(self)
        _btn_bar.pack(side="bottom", fill="x", padx=12, pady=(4, 8))

        self.error_label = ctk.CTkLabel(self, text="", text_color="#ef4444", anchor="w")
        self.error_label.pack(side="bottom", fill="x", padx=12, pady=(0, 2))
        _btn_bar.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(_btn_bar, text="Annuler", command=self._on_cancel).grid(
            row=0, column=1, padx=(6, 0), pady=0
        )
        ctk.CTkButton(_btn_bar, text="Enregistrer", command=self._on_save).grid(
            row=0, column=2, padx=(6, 0), pady=0
        )

        # Scrollable content area
        self._scroll = ctk.CTkScrollableFrame(self)
        self._scroll.pack(fill="both", expand=True)
        self._scroll.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self._scroll, text="Camera index").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        self.camera_var = tk.StringVar(value=str(config.camera_index))
        self.camera_menu = ctk.CTkOptionMenu(self._scroll, variable=self.camera_var, values=[str(config.camera_index)])
        self.camera_menu.grid(row=0, column=1, sticky="ew", padx=12, pady=(12, 6))
        self.refresh_button = ctk.CTkButton(self._scroll, text="Rafraîchir", command=self._refresh_cameras)
        self.refresh_button.grid(row=0, column=2, sticky="e", padx=(0, 12), pady=(12, 6))

        ctk.CTkLabel(self._scroll, text="Flip caméra").grid(
            row=1, column=0, sticky="w", padx=12, pady=6
        )
        self.flip_var = tk.StringVar(value=(config.camera_flip or "none"))
        self.flip_menu = ctk.CTkOptionMenu(
            self._scroll,
            variable=self.flip_var,
            values=["none", "horizontal", "vertical", "both"],
        )
        self.flip_menu.grid(row=1, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(self._scroll, text="Dossier vidéos").grid(
            row=2, column=0, sticky="w", padx=12, pady=6
        )
        self.output_entry = ctk.CTkEntry(self._scroll)
        self.output_entry.insert(0, config.output_dir)
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=12, pady=6)
        ctk.CTkButton(self._scroll, text="Choisir", command=self._browse_output_dir).grid(
            row=2, column=2, sticky="e", padx=(0, 12), pady=6
        )

        ctk.CTkLabel(self._scroll, text="Rétention (jours)").grid(
            row=3, column=0, sticky="w", padx=12, pady=6
        )
        self.retention_entry = ctk.CTkEntry(self._scroll)
        self.retention_entry.insert(0, str(config.retention_days))
        self.retention_entry.grid(row=3, column=1, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(self._scroll, text="Durée max enreg. (min)").grid(
            row=4, column=0, sticky="w", padx=12, pady=6
        )
        self.max_rec_entry = ctk.CTkEntry(self._scroll)
        self.max_rec_entry.insert(0, str(config.max_recording_minutes))
        self.max_rec_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(self._scroll, text="Site").grid(
            row=5, column=0, sticky="w", padx=12, pady=6
        )
        self.site_entry = ctk.CTkEntry(self._scroll)
        self.site_entry.insert(0, config.site_url)
        self.site_entry.grid(row=5, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        # Chrome status indicator
        ctk.CTkLabel(self._scroll, text="Chrome").grid(
            row=6, column=0, sticky="w", padx=12, pady=6
        )
        self.chrome_status_label = ctk.CTkLabel(self._scroll, text="Détection...", anchor="w")
        self.chrome_status_label.grid(row=6, column=1, columnspan=2, sticky="ew", padx=12, pady=6)

        # Separator
        ctk.CTkFrame(self._scroll, height=2, fg_color="#3f3f46").grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=12, pady=12
        )

        # QR detection settings
        ctk.CTkLabel(self._scroll, text="Réglages détection QR", font=("Arial", 13, "bold"), anchor="w").grid(
            row=8, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 6)
        )

        ctk.CTkLabel(self._scroll, text="Zone scan (%)").grid(
            row=9, column=0, sticky="w", padx=12, pady=6
        )
        self.roi_var = tk.IntVar(value=int(config.scan_roi_percent))
        ctk.CTkSlider(
            self._scroll, from_=50, to=100, number_of_steps=50, variable=self.roi_var,
            command=self._on_slider_change,
        ).grid(row=9, column=1, sticky="ew", padx=12, pady=6)
        self.roi_value_label = ctk.CTkLabel(self._scroll, text=f"{config.scan_roi_percent}%", width=50, anchor="w")
        self.roi_value_label.grid(row=9, column=2, sticky="w", padx=(0, 12), pady=6)

        ctk.CTkLabel(self._scroll, text="Luminosité QR").grid(
            row=10, column=0, sticky="w", padx=12, pady=6
        )
        self.brightness_var = tk.IntVar(value=int(config.qr_brightness))
        ctk.CTkSlider(
            self._scroll, from_=-100, to=100, number_of_steps=200, variable=self.brightness_var,
            command=self._on_slider_change,
        ).grid(row=10, column=1, sticky="ew", padx=12, pady=6)
        b_sign = "+" if config.qr_brightness >= 0 else ""
        self.brightness_value_label = ctk.CTkLabel(self._scroll, text=f"{b_sign}{config.qr_brightness}", width=50, anchor="w")
        self.brightness_value_label.grid(row=10, column=2, sticky="w", padx=(0, 12), pady=6)

        ctk.CTkLabel(self._scroll, text="Contraste QR").grid(
            row=11, column=0, sticky="w", padx=12, pady=6
        )
        self.contrast_var = tk.DoubleVar(value=float(config.qr_contrast))
        ctk.CTkSlider(
            self._scroll, from_=0.5, to=3.0, number_of_steps=25, variable=self.contrast_var,
            command=self._on_slider_change,
        ).grid(row=11, column=1, sticky="ew", padx=12, pady=6)
        self.contrast_value_label = ctk.CTkLabel(self._scroll, text=f"{config.qr_contrast:.2f}", width=50, anchor="w")
        self.contrast_value_label.grid(row=11, column=2, sticky="w", padx=(0, 12), pady=6)

        # Camera preview for QR calibration
        self.preview_label = ctk.CTkLabel(self._scroll, text="En attente de la caméra...", width=560, height=315)
        self.preview_label.grid(row=12, column=0, columnspan=3, padx=12, pady=(6, 0))
        ctk.CTkLabel(
            self._scroll, text="Aperçu niveaux de gris — image exacte analysée par le scanner QR",
            font=("Arial", 11), text_color="#9ca3af",
        ).grid(row=13, column=0, columnspan=3, padx=12, pady=(2, 4))

        # Auto-calibration
        self.calibration_label = ctk.CTkLabel(
            self._scroll, text="Cadrez un QR code puis cliquez Calibrer",
            anchor="w", text_color="#9ca3af", font=("Arial", 11),
        )
        self.calibration_label.grid(row=14, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 6))
        self.calibrate_button = ctk.CTkButton(
            self._scroll, text="Calibrer", width=100, command=self._start_calibration
        )
        self.calibrate_button.grid(row=14, column=2, sticky="e", padx=12, pady=(4, 6))

        # Separator 2
        ctk.CTkFrame(self._scroll, height=2, fg_color="#3f3f46").grid(
            row=15, column=0, columnspan=3, sticky="ew", padx=12, pady=8
        )

        # Version and update section
        ctk.CTkLabel(self._scroll, text="Version").grid(
            row=16, column=0, sticky="w", padx=12, pady=6
        )
        self.version_label = ctk.CTkLabel(self._scroll, text=f"v{__version__}", anchor="w")
        self.version_label.grid(row=16, column=1, sticky="w", padx=12, pady=6)
        self.update_button = ctk.CTkButton(
            self._scroll, text="Vérifier MAJ", width=100, command=self._check_for_updates
        )
        self.update_button.grid(row=16, column=2, sticky="e", padx=12, pady=6)

        self.update_status_label = ctk.CTkLabel(self._scroll, text="", anchor="w")
        self.update_status_label.grid(row=17, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))

        self.grab_set()
        self._camera_refreshing = False
        self.after(10, lambda: self._refresh_cameras_async(max_index=10))
        self.after(50, self._detect_chrome)
        self.after(100, self._update_preview)

        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        try:
            self.lift()
        except Exception:
            pass

    def destroy(self) -> None:
        if self._preview_after_id is not None:
            try:
                self.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None
        self._recorder.pause_qr(False)
        super().destroy()

    def _on_slider_change(self, _=None) -> None:
        roi = int(self.roi_var.get())
        self.roi_value_label.configure(text=f"{roi}%")

        b = int(self.brightness_var.get())
        sign = "+" if b >= 0 else ""
        self.brightness_value_label.configure(text=f"{sign}{b}")

        c = float(self.contrast_var.get())
        self.contrast_value_label.configure(text=f"{c:.2f}")

    def _update_preview(self) -> None:
        if not self.winfo_exists():
            return

        frame = self._recorder.get_latest_raw_frame()
        if frame is not None:
            try:
                brightness = int(self.brightness_var.get())
                contrast = float(self.contrast_var.get())
                roi_ratio = int(self.roi_var.get()) / 100.0

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if brightness != 0 or abs(contrast - 1.0) > 0.01:
                    gray = cv2.convertScaleAbs(gray, alpha=contrast, beta=brightness)

                h, w = gray.shape[:2]
                roi_w = int(w * roi_ratio)
                roi_h = int(h * roi_ratio)
                x1 = (w - roi_w) // 2
                y1 = (h - roi_h) // 2
                cv2.rectangle(gray, (x1, y1), (x1 + roi_w, y1 + roi_h), 255, 2)

                resized = cv2.resize(gray, (560, 315))
                img = Image.fromarray(resized)
                photo = CTkImage(light_image=img, dark_image=img, size=(560, 315))
                self._preview_photo = photo
                self.preview_label.configure(image=photo, text="")
            except Exception:
                pass

        self._preview_after_id = self.after(100, self._update_preview)

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
                self._pending_sha256_url = info.sha256_url
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
        sha256_url = getattr(self, "_pending_sha256_url", None)

        self.update_button.configure(state="disabled", text="Téléchargement...")
        self.update_status_label.configure(text="Téléchargement en cours...", text_color="#9ca3af")

        def progress_callback(downloaded: int, total: int) -> None:
            if total > 0:
                percent = int((downloaded / total) * 100)
                self.after(0, lambda p=percent: self._update_download_progress(p))

        def do_download() -> None:
            success, result = download_update(url, progress_callback, sha256_url=sha256_url)
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

    def _start_calibration(self) -> None:
        if not self._recorder.qr_available:
            self.calibration_label.configure(text="Scanner QR non disponible", text_color="#ef4444")
            return
        if self._recorder.qr_backend != "pyzbar":
            self.calibration_label.configure(
                text="Calibration disponible uniquement avec pyzbar", text_color="#f59e0b"
            )
            return

        self.calibrate_button.configure(state="disabled", text="Capture...")
        self.calibration_label.configure(text="Capture des frames en cours...", text_color="#9ca3af")
        roi_ratio = int(self.roi_var.get()) / 100.0

        def _work() -> None:
            frames: list = []
            for _ in range(30):
                frame = self._recorder.get_latest_raw_frame()
                if frame is not None:
                    frames.append(frame)
                time.sleep(0.05)

            if not frames:
                self.after(0, lambda: self._calibration_failed("Aucune frame capturée — caméra active ?"))
                return

            self.after(0, lambda n=len(frames): self.calibration_label.configure(
                text=f"Analyse de {n} frames...", text_color="#9ca3af"
            ))
            self.after(0, lambda: self.calibrate_button.configure(text="Analyse..."))

            def on_progress(p: int) -> None:
                self.after(0, lambda pct=p: self.calibration_label.configure(
                    text=f"Analyse... {pct}%", text_color="#9ca3af"
                ))

            b, c, score = self._recorder.calibrate_qr(frames, roi_ratio, on_progress)

            if score == 0:
                self.after(0, lambda: self._calibration_failed(
                    "Aucun QR code détecté — cadrez un QR code et réessayez"
                ))
            else:
                self.after(0, lambda: self._calibration_done(b, c, score, len(frames)))

        threading.Thread(target=_work, name="tmo_calibrate", daemon=True).start()

    def _calibration_failed(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self.calibration_label.configure(text=msg, text_color="#ef4444")
        self.calibrate_button.configure(state="normal", text="Calibrer")

    def _calibration_done(self, brightness: int, contrast: float, score: int, total: int) -> None:
        if not self.winfo_exists():
            return
        self.brightness_var.set(brightness)
        self.contrast_var.set(contrast)
        self._on_slider_change()
        pct = int(score / total * 100)
        self.calibration_label.configure(
            text=f"Réglages optimaux trouvés — {pct}% de détection ({score}/{total} frames) — pensez à Enregistrer",
            text_color="#10b981",
        )
        self.calibrate_button.configure(state="normal", text="Calibrer")

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

        try:
            max_recording_minutes = int(self.max_rec_entry.get().strip() or "15")
        except ValueError:
            self.error_label.configure(text="Durée max enregistrement invalide")
            return

        if max_recording_minutes < 1:
            self.error_label.configure(text="La durée max doit être >= 1 minute")
            return

        site_url = self.site_entry.get().strip()
        if site_url and not (site_url.startswith("https://") or site_url.startswith("http://")):
            self.error_label.configure(text="L'URL du site doit commencer par https:// ou http://")
            return

        cfg = AppConfig(
            camera_index=camera_index,
            camera_flip=self.flip_var.get().strip(),
            output_dir=self.output_entry.get().strip(),
            retention_days=retention_days,
            max_recording_minutes=max_recording_minutes,
            site_url=site_url,
            scan_roi_percent=int(self.roi_var.get()),
            qr_brightness=int(self.brightness_var.get()),
            qr_contrast=round(float(self.contrast_var.get()), 2),
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


DMS_POPUP_COUNTDOWN_SECONDS = 60


class DeadManSwitchDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        order_id: str,
        on_continue: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        super().__init__(parent)

        self._on_continue = on_continue
        self._on_stop = on_stop
        self._remaining = DMS_POPUP_COUNTDOWN_SECONDS
        self._resolved = False
        self._countdown_after_id: str | None = None

        self.title("TMO - Enregistrement en cours")
        self.geometry("480x240")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._do_continue)

        try:
            self.attributes("-topmost", True)
        except Exception:
            pass

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text=f"Enregistrement en cours : {order_id}",
            font=("Arial", 16, "bold"),
        ).grid(row=0, column=0, padx=24, pady=(24, 8))

        ctk.CTkLabel(
            self,
            text="Êtes-vous toujours là ?",
            font=("Arial", 14),
        ).grid(row=1, column=0, padx=24, pady=(0, 8))

        self._countdown_label = ctk.CTkLabel(
            self,
            text=self._countdown_text(),
            font=("Arial", 13),
            text_color="#f59e0b",
        )
        self._countdown_label.grid(row=2, column=0, padx=24, pady=(0, 16))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=24, pady=(0, 24))

        ctk.CTkButton(
            btn_frame,
            text="Je suis là",
            fg_color="#15803d",
            hover_color="#166534",
            width=160,
            height=40,
            font=("Arial", 14, "bold"),
            command=self._do_continue,
        ).grid(row=0, column=0, padx=(0, 12))

        ctk.CTkButton(
            btn_frame,
            text="Arrêter",
            fg_color="#b91c1c",
            hover_color="#991b1b",
            width=160,
            height=40,
            font=("Arial", 14, "bold"),
            command=self._do_stop,
        ).grid(row=0, column=1)

        self._beep()
        self._force_focus()
        self._tick()

    def _countdown_text(self) -> str:
        return f"Arrêt automatique dans {self._remaining}s"

    def _tick(self) -> None:
        if self._resolved:
            return
        if not self.winfo_exists():
            return

        if self._remaining <= 0:
            self._do_stop()
            return

        self._countdown_label.configure(text=self._countdown_text())

        if self._remaining <= 10:
            self._countdown_label.configure(text_color="#ef4444")
            self._beep()

        self._remaining -= 1
        self._countdown_after_id = self.after(1000, self._tick)

    def _do_continue(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        if self._countdown_after_id is not None:
            try:
                self.after_cancel(self._countdown_after_id)
            except Exception:
                pass
        self._on_continue()
        self.destroy()

    def _do_stop(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        if self._countdown_after_id is not None:
            try:
                self.after_cancel(self._countdown_after_id)
            except Exception:
                pass
        self._on_stop()
        self.destroy()

    def _beep(self) -> None:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            try:
                print("\a", end="", flush=True)
            except Exception:
                pass

    def _force_focus(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

        if os.name == "nt":
            try:
                hwnd = int(self.winfo_id())
                GA_ROOT = 2
                root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
                target = root_hwnd if root_hwnd else hwnd

                SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
                ctypes.windll.user32.SystemParametersInfoW(
                    SPI_SETFOREGROUNDLOCKTIMEOUT, 0, 0, 0
                )
                ctypes.windll.user32.SetForegroundWindow(target)

                FLASHW_ALL = 0x00000003
                FLASHW_TIMERNOFG = 0x0000000C

                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.c_uint),
                        ("hwnd", ctypes.c_void_p),
                        ("dwFlags", ctypes.c_uint),
                        ("uCount", ctypes.c_uint),
                        ("dwTimeout", ctypes.c_uint),
                    ]

                finfo = FLASHWINFO()
                finfo.cbSize = ctypes.sizeof(FLASHWINFO)
                finfo.hwnd = target
                finfo.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG
                finfo.uCount = 5
                finfo.dwTimeout = 0
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(finfo))
            except Exception:
                pass


class TmoApp(ctk.CTk):
    def __init__(self, recorder: Recorder, config: AppConfig) -> None:
        super().__init__()

        self.recorder = recorder
        self.config = config
        self.site_url = config.site_url.strip() or None

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
        self._dms_dialog: DeadManSwitchDialog | None = None
        self._dms_last_reset: float = 0.0

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

        self._check_dead_man_switch()

        if not self._closing:
            self.after(20, self._poll_events)  # 20ms for faster event response

    def _handle_event(self, ev: RecorderEvent) -> None:
        if ev.type == "recording_started" and ev.order_id:
            self._dms_last_reset = time.time()
            self._dismiss_dms_dialog()
            self._set_status(f"Enregistrement en cours : {ev.order_id}")
            self.update_idletasks()
            self._open_order_modal(ev.order_id)

        elif ev.type == "recording_stopped" and ev.order_id:
            self._dismiss_dms_dialog()
            self._set_status(self._ready_status_text())

        elif ev.type == "error":
            msg = ev.message or "unknown"
            log.error("recorder_error message=%s", msg)
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


    def _restore_recording_status(self) -> None:
        order_id = self.recorder.recording_order_id
        if order_id:
            self._set_status(f"Enregistrement en cours : {order_id}")
        else:
            self._set_status(self._ready_status_text())

    def _check_dead_man_switch(self) -> None:
        if not self.recorder.is_recording:
            return

        max_minutes = self.config.max_recording_minutes
        if max_minutes <= 0:
            return

        if self._dms_dialog is not None:
            return

        elapsed = time.time() - self._dms_last_reset
        if elapsed < max_minutes * 60:
            return

        order_id = self.recorder.recording_order_id or "?"
        self._dms_dialog = DeadManSwitchDialog(
            parent=self,
            order_id=order_id,
            on_continue=self._dms_on_continue,
            on_stop=self._dms_on_stop,
        )

    def _dms_on_continue(self) -> None:
        self._dms_last_reset = time.time()
        self._dms_dialog = None

    def _dms_on_stop(self) -> None:
        self._dms_dialog = None
        self.recorder.stop_recording(wait=False)

    def _dismiss_dms_dialog(self) -> None:
        if self._dms_dialog is not None:
            try:
                self._dms_dialog._resolved = True
                self._dms_dialog.destroy()
            except Exception:
                pass
            self._dms_dialog = None

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
            recorder=self.recorder,
        )
        try:
            self._config_window.lift()
            self._config_window.focus_force()
        except Exception:
            self._config_window.focus()

    def _apply_config(self, cfg: AppConfig) -> None:
        save_config(cfg)

        self.config = cfg
        self.site_url = cfg.site_url.strip() or None

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
            scan_roi_percent=cfg.scan_roi_percent,
            qr_brightness=cfg.qr_brightness,
            qr_contrast=cfg.qr_contrast,
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


def _show_config_error_notice(parent: ctk.CTk, message: str) -> None:
    """Show a dialog when config.json is corrupted and defaults were used."""
    dialog = ctk.CTkToplevel(parent)
    dialog.title("Erreur de configuration")
    dialog.geometry("480x220")
    dialog.resizable(False, False)
    dialog.grab_set()

    try:
        dialog.attributes("-topmost", True)
    except Exception:
        pass

    dialog.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        dialog,
        text="⚠️ Fichier de configuration corrompu",
        font=("Arial", 16, "bold"),
    ).grid(row=0, column=0, padx=20, pady=(20, 10))

    ctk.CTkLabel(
        dialog,
        text=message,
        justify="left",
        wraplength=440,
    ).grid(row=1, column=0, padx=20, pady=10)

    ctk.CTkButton(
        dialog,
        text="Compris",
        command=dialog.destroy,
    ).grid(row=2, column=0, padx=20, pady=(10, 20))

    dialog.lift()


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
    setup_logging(log_path())

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    # Check if app was just updated
    just_updated = check_if_just_updated(__version__)
    set_last_run_version(__version__)

    log.info("app_started version=%s", __version__)

    cfg, config_error = load_config()
    output_dir = resolve_output_dir(cfg)

    ensure_dir(output_dir)
    clean_old_videos(output_dir=output_dir, retention_days=cfg.retention_days)

    recorder = Recorder(
        camera_index=cfg.camera_index,
        camera_flip=cfg.camera_flip,
        output_dir=output_dir,
        scan_roi_percent=cfg.scan_roi_percent,
        qr_brightness=cfg.qr_brightness,
        qr_contrast=cfg.qr_contrast,
    )
    recorder.start()

    app = TmoApp(recorder=recorder, config=cfg)

    # Show config error notice if config.json was corrupted
    if config_error:
        log.warning("config_corrupted: %s", config_error)
        app.after(300, lambda: _show_config_error_notice(app, config_error))

    # Show extension reload notice after update
    if just_updated:
        app.after(500, lambda: _show_extension_reload_notice(app))

    app.mainloop()
    log.info("app_stopped")


if __name__ == "__main__":
    main()
