import json
import copy
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from openai import OpenAI
from social_integrations import (
    FacebookAPI,
    SOCIAL_DEFAULT_SIZE,
    SOCIAL_SIZE_OPTIONS,
    SocialIntegrationError,
    TikTokAPI,
    delete_secret,
    dependencies_error,
    is_social_size,
    load_secret_json,
    normalize_social_posts,
    save_secret_json,
)


ENV_PATH = ".env"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = "sora-2"
DEFAULT_PROMPT = (
    "Plan cinema, 8 secondes: Deux hommes qui marchent dans la rue habilles en rastas."
)
DEFAULT_SECONDS = "8"
DEFAULT_SIZE = "1280x720"
DEFAULT_OUTPUT_PATH = os.path.join(APP_DIR, "videos", "sora2_test.mp4")
DEFAULT_OUTPUT_NAME = os.path.splitext(os.path.basename(DEFAULT_OUTPUT_PATH))[0]
DEFAULT_POLL_SECONDS = "2"
SECONDS_OPTIONS = ("4", "8", "12")
SIZE_OPTIONS = ("720x1280", "1280x720", "1024x1792", "1792x1024")
VIDEO_HISTORY_PATH = "sora_videos_history.json"
SOCIAL_ACCOUNTS_PATH = "social_accounts.json"
DEFAULT_FACEBOOK_GRAPH_VERSION = "v23.0"
TIKTOK_DEVELOPER_PORTAL_URL = "https://developers.tiktok.com/"
FACEBOOK_DEVELOPER_PORTAL_URL = "https://developers.facebook.com/"
APP_MANAGED_ENV_KEYS = {
    "OPENAI_API_KEY",
    "TIKTOK_CLIENT_KEY",
    "TIKTOK_CLIENT_SECRET",
    "TIKTOK_REDIRECT_PORT",
    "FACEBOOK_APP_ID",
    "FACEBOOK_APP_SECRET",
    "FACEBOOK_GRAPH_VERSION",
    "FACEBOOK_REDIRECT_PORT",
}
TIKTOK_CLIENT_SECRET_KEYRING_NAME = "tiktok_client_secret"
FACEBOOK_APP_SECRET_KEYRING_NAME = "facebook_app_secret"

WIN11_THEME = {
    "colors": {
        "bg": "#202123",
        "bg_alt": "#1B1C1F",
        "hero_top": "#171717",
        "hero_bottom": "#202123",
        "hero_soft": "#10312B",
        "panel": "#2A2B32",
        "panel_border": "#3B3D47",
        "panel_alt": "#24252C",
        "panel_alt_2": "#2F3037",
        "panel_tint": "#26272F",
        "card_shadow": "#141518",
        "ink": "#ECECF1",
        "muted": "#A9AAB4",
        "muted_soft": "#7D7F8B",
        "hero_subtle": "#C5C7D0",
        "accent": "#10A37F",
        "accent_alt": "#0E8F6F",
        "accent_soft": "#173931",
        "accent_soft_2": "#123028",
        "highlight": "#3B3D47",
        "violet": "#6F7BF7",
        "violet_soft": "#252742",
        "warm": "#F26D7D",
        "warm_soft": "#3C2026",
        "success": "#16342C",
        "success_text": "#6FE6BE",
        "error": "#3A1F25",
        "error_text": "#FFB3BC",
        "info": "#17302A",
        "info_text": "#A4E7D4",
        "log_bg": "#202123",
        "log_info": "#DADBE4",
        "log_success": "#6FE6BE",
        "log_warn": "#F0C36A",
        "log_error": "#FFB3BC",
        "log_system": "#95F0D8",
        "button_face": "#2A2B32",
        "button_light": "#343541",
        "button_shadow": "#23242A",
        "button_dark": "#1E1F24",
        "button_hover": "#35363F",
        "tab_shell": "#171717",
        "tab_active": "#2F3037",
        "tab_active_border": "#494B57",
        "tab_idle_text": "#B8B9C4",
        "input_bg": "#343541",
        "input_border": "#4B4D59",
        "input_focus": "#10A37F",
        "input_disabled": "#282930",
        "scroll_trough": "#171717",
        "scroll_thumb": "#4A4B57",
        "scroll_thumb_active": "#666878",
        "sidebar": "#171717",
        "sidebar_alt": "#1F2025",
        "sidebar_item": "#222329",
        "sidebar_item_hover": "#2A2B32",
        "sidebar_item_active": "#343541",
        "composer_bg": "#343541",
        "composer_border": "#4E5261",
        "banner_info_bg": "#17332B",
        "banner_warn_bg": "#3B2E16",
        "banner_error_bg": "#3A2025",
        "toast_bg": "#2B2C33",
    },
    "fonts": {
        "ui": ("Segoe UI Variable Text", 10),
        "ui_small": ("Segoe UI Variable Text", 9),
        "ui_caption": ("Segoe UI Variable Text", 8),
        "ui_bold": ("Segoe UI Variable Display Semibold", 10),
        "ui_bold_small": ("Segoe UI Variable Display Semibold", 9),
        "section": ("Segoe UI Variable Display Semibold", 12),
        "title": ("Segoe UI Variable Display Semibold", 14),
        "hero": ("Segoe UI Variable Display Semibold", 24),
        "hero_sub": ("Segoe UI Variable Display Semibold", 11),
        "mono": ("Consolas", 9),
    },
    "metrics": {
        "root_padding": (18, 18, 18, 18),
        "hero_height": 96,
        "content_top_spacing": 12,
        "card_padding": (20, 18),
        "status_padding": (18, 18),
        "log_padding": (0, 0),
        "history_padding": (18, 18),
        "section_gap": 14,
        "logo_max": 72,
    },
}


def build_prompt_preview(prompt: str, fallback: str = "", max_length: int = 72) -> str:
    source = " ".join(str(prompt or "").split())
    if not source:
        source = " ".join(str(fallback or "").split())
    if not source:
        return "Nouveau rendu"
    if len(source) <= max_length:
        return source
    return f"{source[: max_length - 1].rstrip()}…"


def normalize_history_record(raw: dict[str, Any], app_dir: str) -> Optional[dict[str, Any]]:
    raw_path = str(raw.get("path", "")).strip()
    if not raw_path:
        return None
    if os.path.isabs(raw_path):
        path = os.path.abspath(raw_path)
    else:
        path = os.path.abspath(os.path.join(app_dir, raw_path))
    if not path:
        return None
    normalized_resolution = str(raw.get("resolution") or raw.get("size") or "-").strip() or "-"

    duration_value: Optional[int] = None
    try:
        if raw.get("duration_seconds") is not None:
            duration_value = int(raw.get("duration_seconds"))
    except (TypeError, ValueError):
        duration_value = None

    bytes_value: Optional[int] = None
    try:
        if raw.get("bytes") is not None:
            bytes_value = int(raw.get("bytes"))
    except (TypeError, ValueError):
        bytes_value = None

    name = str(raw.get("name") or os.path.basename(path))
    prompt = str(raw.get("prompt") or "")
    return {
        "name": name,
        "path": path,
        "created_at": str(raw.get("created_at") or ""),
        "duration_seconds": duration_value,
        "resolution": normalized_resolution,
        "model": str(raw.get("model") or "-"),
        "bytes": bytes_value,
        "video_id": str(raw.get("video_id") or ""),
        "prompt": prompt,
        "prompt_preview": build_prompt_preview(
            prompt or str(raw.get("prompt_preview") or ""),
            fallback=name,
        ),
        "social_ready": bool(raw.get("social_ready") or is_social_size(normalized_resolution)),
        "social_posts": normalize_social_posts(raw.get("social_posts")),
    }


def load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                if key in APP_MANAGED_ENV_KEYS:
                    os.environ[key] = value
                else:
                    os.environ.setdefault(key, value)


class SoraVideoApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SoraStudio")
        self.geometry("1440x900")
        self.minsize(1180, 760)

        self.colors = WIN11_THEME["colors"].copy()
        self.fonts = WIN11_THEME["fonts"].copy()
        self.metrics = WIN11_THEME["metrics"].copy()
        self.configure(bg=self.colors["bg"])

        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.seconds_var = tk.StringVar(value=DEFAULT_SECONDS)
        self.size_var = tk.StringVar(value=DEFAULT_SIZE)
        self.video_name_var = tk.StringVar(value=DEFAULT_OUTPUT_NAME)
        self.output_var = tk.StringVar(value=DEFAULT_OUTPUT_PATH)
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_text_var = tk.StringVar(value="0%")

        self.preview_model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.preview_seconds_var = tk.StringVar(value=f"{DEFAULT_SECONDS}s")
        self.preview_size_var = tk.StringVar(value=DEFAULT_SIZE)
        self.preview_output_var = tk.StringVar(value=os.path.basename(DEFAULT_OUTPUT_PATH))
        self.social_mode_var = tk.BooleanVar(value=False)
        self.social_note_var = tk.StringVar(
            value="Active un rendu vertical 9:16 optimise TikTok et Facebook Reels."
        )
        self.social_status_var = tk.StringVar(
            value="Connecte tes comptes puis publie une vidéo depuis l'espace Publication."
        )
        self.social_video_var = tk.StringVar(value="")
        self.social_caption_var = tk.StringVar(value="")
        self.social_tiktok_var = tk.BooleanVar(value=False)
        self.social_facebook_var = tk.BooleanVar(value=False)
        self.tiktok_account_var = tk.StringVar(value="Non connecte")
        self.facebook_account_var = tk.StringVar(value="Non connecte")
        self.facebook_page_var = tk.StringVar(value="")
        self.tiktok_privacy_var = tk.StringVar(value="")
        self.tiktok_client_key_var = tk.StringVar(value="")
        self.tiktok_client_secret_var = tk.StringVar(value="")
        self.tiktok_redirect_port_var = tk.StringVar(value="8765")
        self.facebook_app_id_var = tk.StringVar(value="")
        self.facebook_app_secret_var = tk.StringVar(value="")
        self.facebook_graph_version_var = tk.StringVar(value=DEFAULT_FACEBOOK_GRAPH_VERSION)
        self.facebook_redirect_port_var = tk.StringVar(value="8766")

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.running = False
        self.indeterminate = False
        self.last_status_seen: Optional[str] = None
        self._syncing_output_name = False
        self.social_events: "queue.Queue[tuple]" = queue.Queue()
        self.social_worker: Optional[threading.Thread] = None
        self.social_busy = False
        self.last_manual_size = DEFAULT_SIZE
        self.active_view = "generate"
        self.selected_record_id = ""
        self.activity_feed: list[dict[str, Any]] = []
        self._mousewheel_canvas: Optional[tk.Canvas] = None

        self.controls: list[Any] = []
        self.social_controls: list[Any] = []
        self.size_combo: Optional[ttk.Combobox] = None
        self.social_mode_check: Optional[tk.Checkbutton] = None
        self.status_chip: Optional[tk.Label] = None
        self.prompt_text: Optional[tk.Text] = None
        self.progress: Optional[ttk.Progressbar] = None
        self.log_text: Optional[tk.Text] = None
        self.generate_btn: Optional[ttk.Button] = None
        self.reset_btn: Optional[ttk.Button] = None
        self.hero_canvas: Optional[tk.Canvas] = None
        self.notebook: Optional[ttk.Notebook] = None
        self.logo_image: Optional[tk.PhotoImage] = None
        self.logo_load_attempted = False
        self.tab_buttons: dict[int, ttk.Button] = {}
        self.view_frames: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.recent_history_list: Optional[tk.Frame] = None
        self.recent_history_empty_var = tk.StringVar(value="Aucun rendu pour l'instant.")
        self.inline_banner_wrap: Optional[tk.Frame] = None
        self.inline_banner_label: Optional[tk.Label] = None
        self.toast_host: Optional[tk.Frame] = None
        self.feed_canvas: Optional[tk.Canvas] = None
        self.feed_frame: Optional[tk.Frame] = None
        self.feed_window_id: Optional[int] = None
        self.advanced_settings_frame: Optional[tk.Frame] = None
        self.advanced_toggle_btn: Optional[ttk.Button] = None
        self.advanced_settings_visible = False
        self.generate_feed_title_var = tk.StringVar(value="Rendus en cours")
        self.status_detail_var = tk.StringVar(value="Prêt à recevoir un prompt.")
        self.history_filter_var = tk.StringVar(value="")
        self.library_cards_frame: Optional[tk.Frame] = None
        self.history_title_var = tk.StringVar(value="Aucune vidéo sélectionnée")
        self.history_meta_var = tk.StringVar(value="Sélectionne un rendu pour voir ses détails.")
        self.history_prompt_var = tk.StringVar(value="")
        self.history_reuse_btn: Optional[ttk.Button] = None
        self.library_empty_var = tk.StringVar(value="Aucun rendu ne correspond au filtre.")
        self.social_posts_list_frame: Optional[tk.Frame] = None
        self.social_posts_empty_var = tk.StringVar(value="Aucune publication récente.")

        self.history_tree: Optional[ttk.Treeview] = None
        self.history_count_var = tk.StringVar(value="0 videos")
        self.history_details_var = tk.StringVar(
            value="Selectionne une video pour afficher son resume, son etat et son chemin complet."
        )
        self.history_open_btn: Optional[ttk.Button] = None
        self.history_export_btn: Optional[ttk.Button] = None
        self.history_delete_btn: Optional[ttk.Button] = None
        self.video_records: list[dict[str, Any]] = []
        self.video_records_by_id: dict[str, dict[str, Any]] = {}
        self.history_file = os.path.join(APP_DIR, VIDEO_HISTORY_PATH)
        self.social_accounts_file = os.path.join(APP_DIR, SOCIAL_ACCOUNTS_PATH)
        self.social_accounts: dict[str, dict[str, Any]] = {"tiktok": {}, "facebook": {}}
        self.social_video_labels: dict[str, dict[str, Any]] = {}
        self.tiktok_privacy_options: list[str] = []
        self.facebook_page_tokens: dict[str, str] = {}

        self.social_video_combo: Optional[ttk.Combobox] = None
        self.social_caption_entry: Optional[ttk.Entry] = None
        self.tiktok_privacy_combo: Optional[ttk.Combobox] = None
        self.facebook_page_combo: Optional[ttk.Combobox] = None
        self.social_tiktok_check: Optional[tk.Checkbutton] = None
        self.social_facebook_check: Optional[tk.Checkbutton] = None
        self.social_publish_btn: Optional[ttk.Button] = None
        self.social_posts_tree: Optional[ttk.Treeview] = None
        self.tiktok_connect_btn: Optional[ttk.Button] = None
        self.tiktok_disconnect_btn: Optional[ttk.Button] = None
        self.tiktok_save_btn: Optional[ttk.Button] = None
        self.facebook_connect_btn: Optional[ttk.Button] = None
        self.facebook_disconnect_btn: Optional[ttk.Button] = None
        self.facebook_save_btn: Optional[ttk.Button] = None
        self.social_help_btn: Optional[ttk.Button] = None
        self.social_tiktok_portal_btn: Optional[ttk.Button] = None
        self.social_facebook_portal_btn: Optional[ttk.Button] = None
        self.facebook_page_labels: dict[str, dict[str, Any]] = {}
        self.social_scroll_canvas: Optional[tk.Canvas] = None
        self.social_scroll_frame: Optional[tk.Frame] = None
        self.social_scroll_window_id: Optional[int] = None
        self.social_scroll_binding_active = False

        self.tiktok_client_key_entry: Optional[ttk.Entry] = None
        self.tiktok_client_secret_entry: Optional[ttk.Entry] = None
        self.tiktok_redirect_port_entry: Optional[ttk.Entry] = None
        self.facebook_app_id_entry: Optional[ttk.Entry] = None
        self.facebook_app_secret_entry: Optional[ttk.Entry] = None
        self.facebook_graph_version_entry: Optional[ttk.Entry] = None
        self.facebook_redirect_port_entry: Optional[ttk.Entry] = None

        self.history_filter_var.trace_add("write", lambda *_args: self._refresh_history_view())

        self._setup_style()
        self._setup_live_preview()
        self._build_ui()
        self._load_video_history()
        self._refresh_history_view()
        self._set_history_actions_state(has_selection=False, file_exists=False)
        self._load_social_accounts()
        self._refresh_social_state()

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", "{Segoe UI Variable Text} 10")
        self.option_add("*TCombobox*Listbox.font", "{Segoe UI Variable Text} 10")
        self.option_add("*TCombobox*Listbox.background", self.colors["panel"])
        self.option_add("*TCombobox*Listbox.foreground", self.colors["ink"])
        self.option_add("*TCombobox*Listbox.selectBackground", self.colors["accent_soft"])
        self.option_add("*TCombobox*Listbox.selectForeground", self.colors["ink"])

        style.configure(".", background=self.colors["bg"], foreground=self.colors["ink"])
        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("TSeparator", background=self.colors["panel_border"])
        style.configure("CardTitle.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=self.fonts["title"])
        style.configure("CardSub.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=self.fonts["ui_small"])
        style.configure("FieldName.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=self.fonts["ui_bold_small"])
        style.configure("Hint.TLabel", background=self.colors["panel_alt_2"], foreground=self.colors["muted"], font=self.fonts["ui_small"])
        style.configure("SectionTitle.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=self.fonts["section"])
        style.configure("SectionNote.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=self.fonts["ui_small"])
        style.configure("SidebarTitle.TLabel", background=self.colors["sidebar"], foreground=self.colors["ink"], font=self.fonts["section"])
        style.configure("Muted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=self.fonts["ui_small"])

        style.configure(
            "Primary.TButton",
            background=self.colors["accent"],
            foreground="#FFFFFF",
            bordercolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
            lightcolor=self.colors["accent"],
            focuscolor=self.colors["accent"],
            focusthickness=0,
            padding=(18, 12),
            font=self.fonts["ui_bold"],
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.colors["accent_alt"]), ("pressed", self.colors["accent_alt"]), ("disabled", self.colors["button_shadow"])],
            foreground=[("disabled", "#F7F7FA")],
            bordercolor=[("active", self.colors["accent_alt"]), ("pressed", self.colors["accent_alt"]), ("disabled", self.colors["button_shadow"])],
        )
        style.configure(
            "Secondary.TButton",
            background=self.colors["panel_alt_2"],
            foreground=self.colors["ink"],
            bordercolor=self.colors["input_border"],
            darkcolor=self.colors["panel_alt_2"],
            lightcolor=self.colors["panel_alt_2"],
            focuscolor=self.colors["input_focus"],
            focusthickness=0,
            padding=(14, 10),
            font=self.fonts["ui_bold"],
            relief="flat",
        )
        style.map(
            "Secondary.TButton",
            background=[("active", self.colors["button_hover"]), ("pressed", self.colors["button_light"]), ("disabled", self.colors["panel_alt_2"])],
            foreground=[("disabled", self.colors["muted"])],
            bordercolor=[("focus", self.colors["input_focus"]), ("active", self.colors["panel_border"]), ("disabled", self.colors["panel_border"])],
        )
        style.configure(
            "Ghost.TButton",
            background=self.colors["panel_alt"],
            foreground=self.colors["muted"],
            bordercolor=self.colors["panel_border"],
            darkcolor=self.colors["panel_alt"],
            lightcolor=self.colors["panel_alt"],
            focuscolor=self.colors["input_focus"],
            focusthickness=0,
            padding=(10, 7),
            font=self.fonts["ui_small"],
            relief="flat",
        )
        style.map(
            "Ghost.TButton",
            background=[("active", self.colors["panel_alt_2"]), ("pressed", self.colors["button_hover"]), ("disabled", self.colors["panel_alt"])],
            foreground=[("active", self.colors["ink"]), ("disabled", self.colors["muted"])],
        )
        style.configure(
            "SmallGhost.TButton",
            background=self.colors["panel"],
            foreground=self.colors["muted"],
            bordercolor=self.colors["panel"],
            darkcolor=self.colors["panel"],
            lightcolor=self.colors["panel"],
            focuscolor=self.colors["input_focus"],
            focusthickness=0,
            padding=(6, 4),
            font=self.fonts["ui_small"],
            relief="flat",
        )
        style.map(
            "SmallGhost.TButton",
            background=[("active", self.colors["panel_alt_2"]), ("pressed", self.colors["button_hover"])],
            foreground=[("active", self.colors["ink"])],
        )
        style.configure(
            "SidebarNav.TButton",
            background=self.colors["sidebar"],
            foreground=self.colors["muted"],
            bordercolor=self.colors["sidebar"],
            darkcolor=self.colors["sidebar"],
            lightcolor=self.colors["sidebar"],
            focuscolor=self.colors["input_focus"],
            focusthickness=0,
            padding=(14, 12),
            font=self.fonts["ui_bold"],
            relief="flat",
            anchor="w",
        )
        style.map(
            "SidebarNav.TButton",
            background=[("active", self.colors["sidebar_item_hover"]), ("pressed", self.colors["sidebar_item_hover"])],
            foreground=[("active", self.colors["ink"])],
        )
        style.configure(
            "SidebarNavActive.TButton",
            background=self.colors["sidebar_item_active"],
            foreground=self.colors["ink"],
            bordercolor=self.colors["sidebar_item_active"],
            darkcolor=self.colors["sidebar_item_active"],
            lightcolor=self.colors["sidebar_item_active"],
            focuscolor=self.colors["input_focus"],
            focusthickness=0,
            padding=(14, 12),
            font=self.fonts["ui_bold"],
            relief="flat",
            anchor="w",
        )
        style.map(
            "SidebarNavActive.TButton",
            background=[("active", self.colors["sidebar_item_active"])],
            foreground=[("active", self.colors["ink"])],
        )
        style.configure(
            "Danger.TButton",
            background=self.colors["warm_soft"],
            foreground=self.colors["error_text"],
            bordercolor=self.colors["warm_soft"],
            darkcolor=self.colors["warm_soft"],
            lightcolor=self.colors["warm_soft"],
            focuscolor=self.colors["input_focus"],
            focusthickness=0,
            padding=(14, 10),
            font=self.fonts["ui_bold"],
            relief="flat",
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#47252C"), ("pressed", "#4B282F"), ("disabled", "#241217")],
            foreground=[("disabled", "#9F7277")],
        )

        style.configure(
            "TEntry",
            fieldbackground=self.colors["input_bg"],
            foreground=self.colors["ink"],
            bordercolor=self.colors["input_border"],
            lightcolor=self.colors["input_border"],
            darkcolor=self.colors["input_border"],
            insertcolor=self.colors["ink"],
            padding=10,
            relief="flat",
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", self.colors["input_focus"])],
            lightcolor=[("focus", self.colors["input_focus"])],
            darkcolor=[("focus", self.colors["input_focus"])],
            fieldbackground=[("disabled", self.colors["input_disabled"])],
            foreground=[("disabled", self.colors["muted"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.colors["input_bg"],
            foreground=self.colors["ink"],
            bordercolor=self.colors["input_border"],
            lightcolor=self.colors["input_border"],
            darkcolor=self.colors["input_border"],
            arrowcolor=self.colors["muted"],
            padding=10,
            arrowsize=14,
            relief="flat",
        )
        style.map(
            "TCombobox",
            bordercolor=[("focus", self.colors["input_focus"]), ("readonly", self.colors["input_border"])],
            lightcolor=[("focus", self.colors["input_focus"])],
            darkcolor=[("focus", self.colors["input_focus"])],
            fieldbackground=[("disabled", self.colors["input_disabled"])],
            foreground=[("disabled", self.colors["muted"])],
            arrowcolor=[("focus", self.colors["accent"]), ("disabled", self.colors["muted"])],
        )
        style.configure(
            "Readable.TCombobox",
            fieldbackground=self.colors["input_bg"],
            foreground=self.colors["ink"],
            bordercolor=self.colors["input_border"],
            lightcolor=self.colors["input_border"],
            darkcolor=self.colors["input_border"],
            arrowcolor=self.colors["muted"],
            padding=10,
            arrowsize=14,
            relief="flat",
        )
        style.map(
            "Readable.TCombobox",
            fieldbackground=[("focus", self.colors["button_light"]), ("readonly", self.colors["input_bg"]), ("!disabled", self.colors["input_bg"])],
            foreground=[("readonly", self.colors["ink"]), ("!disabled", self.colors["ink"])],
            selectbackground=[("readonly", self.colors["accent_soft"]), ("!disabled", self.colors["accent_soft"])],
            selectforeground=[("readonly", self.colors["ink"]), ("!disabled", self.colors["ink"])],
            bordercolor=[("focus", self.colors["input_focus"]), ("readonly", self.colors["input_border"])],
            lightcolor=[("focus", self.colors["input_focus"])],
            darkcolor=[("focus", self.colors["input_focus"])],
            arrowcolor=[("focus", self.colors["accent"]), ("active", self.colors["accent_alt"]), ("readonly", self.colors["muted"]), ("!disabled", self.colors["muted"])],
        )

        style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor=self.colors["accent_soft_2"],
            bordercolor=self.colors["accent_soft_2"],
            background=self.colors["accent"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
            thickness=10,
        )
        style.configure("History.Treeview", background=self.colors["panel_alt"], fieldbackground=self.colors["panel_alt"], foreground=self.colors["ink"], rowheight=34, font=self.fonts["ui_small"], relief="flat")
        style.map("History.Treeview", background=[("selected", self.colors["accent_soft_2"])], foreground=[("selected", self.colors["ink"])], bordercolor=[("focus", self.colors["input_focus"])])
        style.configure("History.Treeview.Heading", background=self.colors["panel_alt_2"], foreground=self.colors["muted"], relief="flat", font=self.fonts["ui_bold_small"], bordercolor=self.colors["panel_border"], lightcolor=self.colors["panel_alt_2"], darkcolor=self.colors["panel_alt_2"], borderwidth=1)
        style.map("History.Treeview.Heading", background=[("active", self.colors["button_hover"])], foreground=[("active", self.colors["ink"])])
        style.configure("App.Vertical.TScrollbar", background=self.colors["scroll_thumb"], troughcolor=self.colors["scroll_trough"], bordercolor=self.colors["panel_border"], lightcolor=self.colors["scroll_thumb"], darkcolor=self.colors["scroll_thumb"], arrowcolor=self.colors["muted"], relief="flat")
        style.map("App.Vertical.TScrollbar", background=[("active", self.colors["scroll_thumb_active"])], arrowcolor=[("active", self.colors["ink"])])

    def _setup_live_preview(self) -> None:
        self.model_var.trace_add("write", self._refresh_preview_event)
        self.seconds_var.trace_add("write", self._refresh_preview_event)
        self.size_var.trace_add("write", self._refresh_preview_event)
        self.size_var.trace_add("write", self._remember_manual_size_event)
        self.video_name_var.trace_add("write", self._sync_output_from_name_event)
        self.output_var.trace_add("write", self._refresh_preview_event)
        self.output_var.trace_add("write", self._sync_name_from_output_event)
        self.social_mode_var.trace_add("write", self._apply_social_mode_event)
        self.social_caption_var.trace_add("write", self._update_social_publish_state_event)
        self._sync_output_from_name()
        self._refresh_preview()

    def _refresh_preview_event(self, *_args: Any) -> None:
        self._refresh_preview()

    def _remember_manual_size_event(self, *_args: Any) -> None:
        self._remember_manual_size()

    def _remember_manual_size(self) -> None:
        if self.social_mode_var.get():
            return
        size = self.size_var.get().strip()
        if size in SIZE_OPTIONS:
            self.last_manual_size = size

    def _apply_social_mode_event(self, *_args: Any) -> None:
        self._apply_social_mode()

    def _update_social_publish_state_event(self, *_args: Any) -> None:
        self._update_social_publish_state()

    def _apply_social_mode(self) -> None:
        if self.social_mode_var.get():
            current_size = self.size_var.get().strip()
            if current_size in SIZE_OPTIONS and current_size != SOCIAL_DEFAULT_SIZE:
                self.last_manual_size = current_size
            if self.size_var.get() != SOCIAL_DEFAULT_SIZE:
                self.size_var.set(SOCIAL_DEFAULT_SIZE)
            if self.size_combo is not None:
                self.size_combo.configure(state="disabled")
            self.social_note_var.set(
                "Mode reseaux actif: generation 9:16 premium prete pour TikTok et Facebook Reels."
            )
            return

        if self.size_combo is not None and not self.running:
            self.size_combo.configure(state="readonly")
        restored_size = self.last_manual_size if self.last_manual_size in SIZE_OPTIONS else DEFAULT_SIZE
        if self.size_var.get() != restored_size:
            self.size_var.set(restored_size)
        self.social_note_var.set(
            "Active un rendu vertical 9:16 optimise TikTok et Facebook Reels."
        )

    def _sanitize_video_name(self, raw_name: str) -> str:
        invalid_chars = '<>:"/\\|?*'
        cleaned = "".join("_" if ch in invalid_chars else ch for ch in raw_name).strip()
        cleaned = cleaned.rstrip(". ")
        return cleaned

    def _normalize_video_stem(self, raw_name: str) -> str:
        cleaned = self._sanitize_video_name(raw_name)
        if cleaned.lower().endswith(".mp4"):
            cleaned = cleaned[:-4].rstrip(". ")
        return cleaned

    def _build_output_filename(self, raw_name: str) -> str:
        stem = self._normalize_video_stem(raw_name)
        if not stem:
            return ""
        return f"{stem}.MP4"

    def _default_output_dir(self) -> str:
        current = self.output_var.get().strip()
        if current:
            current_dir = os.path.dirname(current)
            if current_dir:
                return current_dir
        return os.path.dirname(DEFAULT_OUTPUT_PATH)

    def _sync_output_from_name_event(self, *_args: Any) -> None:
        self._sync_output_from_name()

    def _sync_output_from_name(self) -> None:
        if self._syncing_output_name:
            return

        stem = self._normalize_video_stem(self.video_name_var.get())
        if not stem:
            return
        filename = f"{stem}.MP4"

        output_dir = self._default_output_dir()
        next_path = os.path.abspath(os.path.join(output_dir, filename))
        current_raw = self.output_var.get().strip()
        current_path = os.path.abspath(current_raw) if current_raw else ""
        if current_path == next_path and self.video_name_var.get() == stem:
            return

        self._syncing_output_name = True
        try:
            if self.video_name_var.get() != stem:
                self.video_name_var.set(stem)
            self.output_var.set(next_path)
        finally:
            self._syncing_output_name = False

    def _sync_name_from_output_event(self, *_args: Any) -> None:
        self._sync_name_from_output()

    def _sync_name_from_output(self) -> None:
        if self._syncing_output_name:
            return

        path = self.output_var.get().strip()
        if not path:
            return

        output_dir = os.path.dirname(path) or self._default_output_dir()
        stem = os.path.splitext(os.path.basename(path))[0]
        cleaned_stem = self._normalize_video_stem(stem)
        if not cleaned_stem:
            return

        normalized_filename = self._build_output_filename(cleaned_stem)
        normalized_path = os.path.abspath(os.path.join(output_dir, normalized_filename))

        self._syncing_output_name = True
        try:
            if self.video_name_var.get() != cleaned_stem:
                self.video_name_var.set(cleaned_stem)
            if os.path.abspath(path) != normalized_path:
                self.output_var.set(normalized_path)
        finally:
            self._syncing_output_name = False

    def _bind_dropdown_open(self, combo: ttk.Combobox) -> None:
        combo.bind("<ButtonRelease-1>", self._open_combobox_dropdown_click, add="+")
        combo.bind("<Return>", self._open_combobox_dropdown_key, add="+")
        combo.bind("<space>", self._open_combobox_dropdown_key, add="+")

    def _post_combobox_dropdown(self, combo: ttk.Combobox) -> None:
        if "disabled" in combo.state():
            return
        try:
            combo.tk.call("::ttk::combobox::Post", str(combo))
        except tk.TclError:
            combo.event_generate("<Down>")

    def _open_combobox_dropdown_click(self, event: Any) -> None:
        widget = event.widget
        if not isinstance(widget, ttk.Combobox):
            return
        if "disabled" in widget.state():
            return

        hit_area = str(widget.identify(event.x, event.y)).lower()
        if hit_area and all(token not in hit_area for token in ("downarrow", "textarea", "field")):
            return

        widget.after_idle(lambda: self._post_combobox_dropdown(widget))

    def _open_combobox_dropdown_key(self, event: Any) -> Optional[str]:
        widget = event.widget
        if not isinstance(widget, ttk.Combobox):
            return None
        if "disabled" in widget.state():
            return None

        self._post_combobox_dropdown(widget)
        return "break"

    def _refresh_preview(self) -> None:
        model = self.model_var.get().strip() or "Modele a definir"
        seconds = self.seconds_var.get().strip()
        size = self.size_var.get().strip() or "Format a choisir"
        output = self.output_var.get().strip()

        self.preview_model_var.set(model)
        if seconds.isdigit():
            self.preview_seconds_var.set(f"{seconds}s")
        else:
            self.preview_seconds_var.set("Duree a choisir")
        self.preview_size_var.set(size)
        self.preview_output_var.set(os.path.basename(output) if output else "Sortie a definir")
        self.generate_feed_title_var.set(f"{model} • {self.preview_seconds_var.get()} • {size}")
        self.status_detail_var.set(
            "Prêt à générer. Entrée lance le rendu, Shift+Entrée ajoute une nouvelle ligne."
            if not self.running
            else "Le moteur vidéo est occupé. Le fil central reçoit les étapes importantes."
        )

    def _get_logo_image(self) -> Optional[tk.PhotoImage]:
        if self.logo_load_attempted:
            return self.logo_image
        self.logo_load_attempted = True

        logo_path = os.path.join(APP_DIR, "logo.png")
        if not os.path.exists(logo_path):
            return None

        try:
            image = tk.PhotoImage(file=logo_path)
        except tk.TclError:
            return None

        max_w = int(self.metrics["logo_max"])
        max_h = int(self.metrics["logo_max"])
        width = max(int(image.width()), 1)
        height = max(int(image.height()), 1)
        scale_w = (width + max_w - 1) // max_w
        scale_h = (height + max_h - 1) // max_h
        factor = max(1, scale_w, scale_h)
        if factor > 1:
            image = image.subsample(factor, factor)

        self.logo_image = image
        return self.logo_image

    def _create_card(
        self, parent: tk.Widget, inner_padding: tuple[int, int]
    ) -> tuple[tk.Frame, tk.Frame]:
        shell = tk.Frame(parent, bg=self.colors["card_shadow"], bd=0, highlightthickness=0)
        border = tk.Frame(shell, bg=self.colors["panel_border"], bd=0, highlightthickness=0)
        border.pack(fill="both", expand=True, padx=(0, 1), pady=(0, 1))
        inner = tk.Frame(
            border,
            bg=self.colors["panel"],
            padx=inner_padding[0],
            pady=inner_padding[1],
            bd=0,
            highlightthickness=0,
        )
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return shell, inner

    def _create_soft_panel(
        self,
        parent: tk.Widget,
        bg_key: str,
        inner_padding: tuple[int, int],
    ) -> tuple[tk.Frame, tk.Frame]:
        shell = tk.Frame(parent, bg=self.colors["card_shadow"], bd=0, highlightthickness=0)
        inner = tk.Frame(
            shell,
            bg=self.colors[bg_key],
            padx=inner_padding[0],
            pady=inner_padding[1],
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        inner.pack(fill="both", expand=True, padx=(0, 1), pady=(0, 1))
        return shell, inner

    def _select_tab(self, index: int) -> None:
        if self.notebook is None:
            return
        tabs = self.notebook.tabs()
        if 0 <= index < len(tabs):
            self.notebook.select(tabs[index])
        self._sync_tab_buttons()

    def _sync_tab_buttons(self, _event: Any = None) -> None:
        if self.notebook is None:
            return
        current_index = self.notebook.index(self.notebook.select())
        for index, button in self.tab_buttons.items():
            button.configure(
                style="SegmentedActive.TButton" if index == current_index else "Segmented.TButton"
            )

    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=self.colors["bg"])
        root.pack(fill="both", expand=True)

        self.toast_host = tk.Frame(root, bg=self.colors["bg"])
        self.toast_host.place(relx=1.0, x=-20, y=18, anchor="ne")

        self.inline_banner_wrap = tk.Frame(
            root,
            bg=self.colors["banner_info_bg"],
            padx=16,
            pady=10,
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        self.inline_banner_label = tk.Label(
            self.inline_banner_wrap,
            bg=self.colors["banner_info_bg"],
            fg=self.colors["ink"],
            font=self.fonts["ui_small"],
            justify="left",
            anchor="w",
        )
        self.inline_banner_label.pack(fill="x")
        self.inline_banner_wrap.pack(fill="x", padx=18, pady=(18, 0))
        self.inline_banner_wrap.pack_forget()

        shell = tk.Frame(root, bg=self.colors["bg"], padx=18, pady=18)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=0)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)
        self.main_shell = shell

        sidebar = tk.Frame(shell, bg=self.colors["sidebar"], width=290, padx=14, pady=14)
        sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 18))
        sidebar.grid_propagate(False)
        self._build_sidebar(sidebar)

        workspace = tk.Frame(shell, bg=self.colors["bg"])
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)

        generate_view = tk.Frame(workspace, bg=self.colors["bg"])
        library_view = tk.Frame(workspace, bg=self.colors["bg"])
        social_view = tk.Frame(workspace, bg=self.colors["bg"])
        self.view_frames = {
            "generate": generate_view,
            "library": library_view,
            "social": social_view,
        }
        for frame in self.view_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._build_generate_view(generate_view)
        self._build_library_view(library_view)
        self._build_social_workspace(social_view)
        self._show_view("generate")

        self._set_status("Ready", "info")
        self._push_activity(
            "system",
            "Configure le prompt puis appuie sur Entrée pour lancer un rendu.",
            title="Bienvenue dans SoraStudio",
        )

    def _create_scrollable_region(
        self,
        parent: tk.Widget,
        bg: str,
    ) -> tuple[tk.Frame, tk.Canvas, tk.Frame, int]:
        shell = tk.Frame(parent, bg=bg)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, bg=bg, relief="flat", bd=0, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=canvas.yview,
            style="App.Vertical.TScrollbar",
        )
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)

        inner = tk.Frame(canvas, bg=bg)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda event, c=canvas, wid=window_id: c.itemconfigure(wid, width=event.width),
        )
        canvas.bind("<Enter>", lambda _event, c=canvas: self._bind_mousewheel_to_canvas(c))
        canvas.bind("<Leave>", lambda _event: self._unbind_mousewheel_canvas())
        return shell, canvas, inner, window_id

    def _bind_mousewheel_to_canvas(self, canvas: tk.Canvas) -> None:
        self._mousewheel_canvas = canvas
        self.bind_all("<MouseWheel>", self._on_bound_canvas_mousewheel)

    def _unbind_mousewheel_canvas(self) -> None:
        self._mousewheel_canvas = None
        self.unbind_all("<MouseWheel>")

    def _on_bound_canvas_mousewheel(self, event: Any) -> None:
        if self._mousewheel_canvas is None:
            return
        delta = int(-1 * (event.delta / 120))
        self._mousewheel_canvas.yview_scroll(delta, "units")

    def _show_view(self, view_name: str) -> None:
        self.active_view = view_name
        for name, frame in self.view_frames.items():
            if name == view_name:
                frame.tkraise()
        for name, button in self.nav_buttons.items():
            button.configure(
                style="SidebarNavActive.TButton" if name == view_name else "SidebarNav.TButton"
            )

    def _build_sidebar(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)

        brand = tk.Frame(parent, bg=self.colors["sidebar"])
        brand.grid(row=0, column=0, sticky="ew")
        tk.Label(
            brand,
            text="SoraStudio",
            bg=self.colors["sidebar"],
            fg=self.colors["ink"],
            font=self.fonts["hero_sub"],
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="Studio vidéo IA, version workspace",
            bg=self.colors["sidebar"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
        ).pack(anchor="w", pady=(4, 0))

        ttk.Button(
            parent,
            text="Nouveau rendu",
            style="Primary.TButton",
            command=self._start_new_session,
        ).grid(row=1, column=0, sticky="ew", pady=(18, 16))

        nav = tk.Frame(parent, bg=self.colors["sidebar"])
        nav.grid(row=2, column=0, sticky="ew")
        nav.columnconfigure(0, weight=1)
        self.nav_buttons = {
            "generate": ttk.Button(
                nav,
                text="Créer",
                style="SidebarNavActive.TButton",
                command=lambda: self._show_view("generate"),
            ),
            "library": ttk.Button(
                nav,
                text="Bibliothèque",
                style="SidebarNav.TButton",
                command=lambda: self._show_view("library"),
            ),
            "social": ttk.Button(
                nav,
                text="Publication",
                style="SidebarNav.TButton",
                command=lambda: self._show_view("social"),
            ),
        }
        self.nav_buttons["generate"].grid(row=0, column=0, sticky="ew")
        self.nav_buttons["library"].grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.nav_buttons["social"].grid(row=2, column=0, sticky="ew", pady=(6, 0))

        ttk.Separator(parent).grid(row=3, column=0, sticky="ew", pady=18)

        recent_shell = tk.Frame(parent, bg=self.colors["sidebar"])
        recent_shell.grid(row=4, column=0, sticky="nsew")
        recent_shell.columnconfigure(0, weight=1)
        recent_shell.rowconfigure(1, weight=1)

        tk.Label(
            recent_shell,
            text="Rendus récents",
            bg=self.colors["sidebar"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=0, column=0, sticky="w")
        recent_list_shell, _recent_canvas, recent_inner, _recent_window = self._create_scrollable_region(
            recent_shell,
            self.colors["sidebar"],
        )
        recent_list_shell.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.recent_history_list = recent_inner

        tk.Label(
            parent,
            textvariable=self.history_count_var,
            bg=self.colors["sidebar"],
            fg=self.colors["muted_soft"],
            font=self.fonts["ui_caption"],
        ).grid(row=5, column=0, sticky="w", pady=(12, 0))

    def _start_new_session(self) -> None:
        if self.running:
            self._show_banner(
                "Le rendu en cours doit se terminer avant de démarrer une nouvelle session.",
                "warn",
            )
            return
        self.selected_record_id = ""
        self.activity_feed = []
        self._render_activity_feed()
        self._show_view("generate")
        self._reset_form()

    def _build_generate_view(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=0)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)

        feed_shell, feed_card = self._create_card(parent, inner_padding=(0, 0))
        feed_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        feed_card.columnconfigure(0, weight=1)
        feed_card.rowconfigure(1, weight=1)

        feed_header = tk.Frame(feed_card, bg=self.colors["panel"], padx=20, pady=18)
        feed_header.grid(row=0, column=0, sticky="ew")
        feed_header.columnconfigure(0, weight=1)
        tk.Label(
            feed_header,
            text="Créer un rendu",
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["title"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            feed_header,
            textvariable=self.generate_feed_title_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        feed_body_shell, self.feed_canvas, self.feed_frame, self.feed_window_id = self._create_scrollable_region(
            feed_card,
            self.colors["panel"],
        )
        feed_body_shell.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        rail_shell, rail_card = self._create_card(parent, inner_padding=(18, 16))
        rail_shell.grid(row=0, column=1, sticky="nsew")
        rail_card.configure(width=320)
        rail_card.grid_propagate(False)
        self._build_generate_status_rail(rail_card)

        composer_shell, composer_card = self._create_card(parent, inner_padding=(18, 16))
        composer_shell.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self._build_generate_composer(composer_card)

    def _build_generate_status_rail(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        top = tk.Frame(parent, bg=self.colors["panel"])
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        tk.Label(
            top,
            text="Statut live",
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).grid(row=0, column=0, sticky="w")
        self.status_chip = tk.Label(
            top,
            text="PRET",
            bg=self.colors["info"],
            fg=self.colors["info_text"],
            font=self.fonts["ui_bold_small"],
            padx=10,
            pady=4,
        )
        self.status_chip.grid(row=0, column=1, sticky="e")

        tk.Label(
            parent,
            textvariable=self.status_var,
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["ui_bold"],
            wraplength=250,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(14, 6))
        tk.Label(
            parent,
            textvariable=self.status_detail_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            wraplength=250,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew")

        progress_shell, progress_card = self._create_soft_panel(parent, "panel_tint", inner_padding=(12, 12))
        progress_shell.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        progress_card.columnconfigure(0, weight=1)
        tk.Label(
            progress_card,
            text="Progression",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            progress_card,
            textvariable=self.progress_text_var,
            bg=self.colors["panel_tint"],
            fg=self.colors["accent"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(
            progress_card,
            style="Blue.Horizontal.TProgressbar",
            mode="determinate",
            variable=self.progress_var,
            maximum=100,
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        metrics = tk.Frame(parent, bg=self.colors["panel"])
        metrics.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        metrics.columnconfigure(0, weight=1)
        metrics.columnconfigure(1, weight=1)
        self._make_metric(metrics, 0, 0, "Modèle", self.preview_model_var)
        self._make_metric(metrics, 0, 1, "Durée", self.preview_seconds_var)
        self._make_metric(metrics, 1, 0, "Format", self.preview_size_var)
        self._make_metric(metrics, 1, 1, "Sortie", self.preview_output_var)

        actions = tk.Frame(parent, bg=self.colors["panel"])
        actions.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(
            actions,
            text="Voir bibliothèque",
            style="Secondary.TButton",
            command=lambda: self._show_view("library"),
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            actions,
            text="Ouvrir sortie",
            style="Ghost.TButton",
            command=self._open_current_output,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _build_generate_composer(self, parent: tk.Frame) -> None:
        section_gap = int(self.metrics["section_gap"])
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        controls_row = tk.Frame(parent, bg=self.colors["panel"])
        controls_row.grid(row=0, column=0, sticky="ew")
        controls_row.columnconfigure(0, weight=2)
        controls_row.columnconfigure(1, weight=1)
        controls_row.columnconfigure(2, weight=1)
        controls_row.columnconfigure(3, weight=0)

        model_entry = ttk.Entry(controls_row, textvariable=self.model_var)
        model_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.controls.append(model_entry)

        seconds_combo = ttk.Combobox(
            controls_row,
            textvariable=self.seconds_var,
            values=SECONDS_OPTIONS,
            state="readonly",
            style="Readable.TCombobox",
            width=10,
        )
        seconds_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self._bind_dropdown_open(seconds_combo)

        size_combo = ttk.Combobox(
            controls_row,
            textvariable=self.size_var,
            values=SIZE_OPTIONS,
            state="readonly",
            style="Readable.TCombobox",
        )
        size_combo.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self._bind_dropdown_open(size_combo)
        self.size_combo = size_combo
        self.controls.extend([seconds_combo, size_combo])

        self.advanced_toggle_btn = ttk.Button(
            controls_row,
            text="Paramètres avancés",
            style="Ghost.TButton",
            command=self._toggle_advanced_settings,
        )
        self.advanced_toggle_btn.grid(row=0, column=3, sticky="e")

        composer_wrap = tk.Frame(
            parent,
            bg=self.colors["composer_border"],
            bd=0,
            highlightthickness=0,
            padx=1,
            pady=1,
        )
        composer_wrap.grid(row=1, column=0, sticky="nsew", pady=(section_gap, 0))
        composer_wrap.columnconfigure(0, weight=1)
        composer_wrap.rowconfigure(0, weight=1)

        self.prompt_text = tk.Text(
            composer_wrap,
            height=7,
            font=self.fonts["ui"],
            wrap="word",
            bg=self.colors["composer_bg"],
            fg=self.colors["ink"],
            insertbackground=self.colors["ink"],
            relief="flat",
            bd=0,
            padx=16,
            pady=16,
            highlightthickness=0,
        )
        self.prompt_text.grid(row=0, column=0, sticky="nsew")
        self.prompt_text.insert("1.0", DEFAULT_PROMPT)
        self.prompt_text.bind("<Return>", self._on_prompt_return)
        self.controls.append(self.prompt_text)

        self.advanced_settings_frame = tk.Frame(parent, bg=self.colors["panel"], padx=0, pady=0)
        self.advanced_settings_frame.columnconfigure(0, weight=1)

        output_shell, output_card = self._create_soft_panel(
            self.advanced_settings_frame,
            "panel_tint",
            inner_padding=(14, 14),
        )
        output_shell.grid(row=0, column=0, sticky="ew", pady=(section_gap, 0))
        output_card.columnconfigure(0, weight=1)
        tk.Label(
            output_card,
            text="Sortie",
            bg=self.colors["panel_tint"],
            fg=self.colors["ink"],
            font=self.fonts["ui_bold"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            output_card,
            text="Nom de la vidéo",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=1, column=0, sticky="w", pady=(12, 0))
        name_wrap = tk.Frame(output_card, bg=self.colors["panel_tint"])
        name_wrap.grid(row=2, column=0, sticky="ew", pady=(6, 10))
        name_wrap.columnconfigure(0, weight=1)
        name_entry = ttk.Entry(name_wrap, textvariable=self.video_name_var)
        name_entry.grid(row=0, column=0, sticky="ew")
        tk.Label(
            name_wrap,
            text=".MP4",
            bg=self.colors["accent_soft_2"],
            fg=self.colors["accent"],
            font=self.fonts["ui_bold_small"],
            padx=10,
            pady=6,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.controls.append(name_entry)

        tk.Label(
            output_card,
            text="Chemin de sortie",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=3, column=0, sticky="w")
        output_wrap = tk.Frame(output_card, bg=self.colors["panel_tint"])
        output_wrap.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        output_wrap.columnconfigure(0, weight=1)
        output_entry = ttk.Entry(output_wrap, textvariable=self.output_var)
        output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        browse_btn = ttk.Button(
            output_wrap,
            text="Parcourir",
            style="Secondary.TButton",
            command=self._pick_output,
        )
        browse_btn.grid(row=0, column=1, sticky="e")
        self.controls.extend([output_entry, browse_btn])

        footer = tk.Frame(parent, bg=self.colors["panel"])
        footer.grid(row=3, column=0, sticky="ew", pady=(section_gap, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=0)
        footer.columnconfigure(2, weight=0)

        self.social_mode_check = tk.Checkbutton(
            footer,
            text="Pour réseaux",
            variable=self.social_mode_var,
            command=self._apply_social_mode,
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            selectcolor=self.colors["panel_alt"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["ink"],
            font=self.fonts["ui_bold_small"],
            highlightthickness=0,
            bd=0,
        )
        self.social_mode_check.grid(row=0, column=0, sticky="w")
        tk.Label(
            footer,
            textvariable=self.social_note_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            wraplength=540,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.controls.append(self.social_mode_check)

        self.reset_btn = ttk.Button(
            footer,
            text="Réinitialiser",
            style="Secondary.TButton",
            command=self._reset_form,
        )
        self.reset_btn.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        self.generate_btn = ttk.Button(
            footer,
            text="Générer",
            style="Primary.TButton",
            command=self._start_generation,
        )
        self.generate_btn.grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 0))
        self.controls.extend([self.generate_btn, self.reset_btn])

    def _toggle_advanced_settings(self) -> None:
        if self.advanced_settings_frame is None:
            return
        self.advanced_settings_visible = not self.advanced_settings_visible
        if self.advanced_settings_visible:
            self.advanced_settings_frame.grid(row=2, column=0, sticky="ew")
        else:
            self.advanced_settings_frame.grid_forget()
        if self.advanced_toggle_btn is not None:
            self.advanced_toggle_btn.configure(
                text="Masquer les paramètres" if self.advanced_settings_visible else "Paramètres avancés"
            )

    def _on_prompt_return(self, event: Any) -> Optional[str]:
        if bool(event.state & 0x1):
            return None
        self._start_generation()
        return "break"

    def _open_current_output(self) -> None:
        path = self.output_var.get().strip()
        if not path:
            self._show_banner("Aucune sortie active à ouvrir.", "warn")
            return
        if not os.path.exists(path):
            self._show_banner("Le fichier de sortie n'existe pas encore sur le disque.", "warn")
            return
        try:
            self._open_in_system(path)
        except Exception as exc:
            self._show_banner(f"Ouverture impossible: {exc}", "error")

    def _build_library_view(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=5)
        parent.columnconfigure(1, weight=4)
        parent.rowconfigure(1, weight=1)

        header = tk.Frame(parent, bg=self.colors["bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Bibliothèque",
            bg=self.colors["bg"],
            fg=self.colors["ink"],
            font=self.fonts["title"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="Retrouve chaque rendu, son prompt et ses publications.",
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(header, textvariable=self.history_filter_var).grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(16, 0),
        )

        list_shell, list_card = self._create_card(parent, inner_padding=(16, 16))
        list_shell.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        tk.Label(
            list_card,
            text="Rendus",
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).grid(row=0, column=0, sticky="w")
        cards_shell, _cards_canvas, cards_inner, _cards_window = self._create_scrollable_region(
            list_card,
            self.colors["panel"],
        )
        cards_shell.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.library_cards_frame = cards_inner

        detail_shell, detail_card = self._create_card(parent, inner_padding=(18, 18))
        detail_shell.grid(row=1, column=1, sticky="nsew")
        detail_card.columnconfigure(0, weight=1)

        tk.Label(
            detail_card,
            textvariable=self.history_title_var,
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["title"],
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            detail_card,
            textvariable=self.history_meta_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            justify="left",
            anchor="w",
            wraplength=360,
        ).grid(row=1, column=0, sticky="ew", pady=(10, 16))

        prompt_shell, prompt_card = self._create_soft_panel(detail_card, "panel_alt", inner_padding=(14, 12))
        prompt_shell.grid(row=2, column=0, sticky="ew")
        tk.Label(
            prompt_card,
            text="Prompt",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w")
        tk.Message(
            prompt_card,
            textvariable=self.history_prompt_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["ink"],
            font=self.fonts["ui_small"],
            width=360,
            justify="left",
        ).pack(fill="x", pady=(8, 0))

        details_shell, details_card = self._create_soft_panel(detail_card, "panel_tint", inner_padding=(14, 12))
        details_shell.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        tk.Label(
            details_card,
            text="Détails",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w")
        tk.Message(
            details_card,
            textvariable=self.history_details_var,
            bg=self.colors["panel_tint"],
            fg=self.colors["ink"],
            font=self.fonts["ui_small"],
            width=360,
            justify="left",
        ).pack(fill="x", pady=(8, 0))

        actions = tk.Frame(detail_card, bg=self.colors["panel"])
        actions.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        actions.columnconfigure(3, weight=1)
        self.history_open_btn = ttk.Button(actions, text="Ouvrir", style="Secondary.TButton", command=self._history_open_selected)
        self.history_open_btn.grid(row=0, column=0, sticky="ew")
        self.history_export_btn = ttk.Button(actions, text="Exporter", style="Ghost.TButton", command=self._history_export_selected)
        self.history_export_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.history_reuse_btn = ttk.Button(actions, text="Réutiliser", style="Ghost.TButton", command=self._history_reuse_selected)
        self.history_reuse_btn.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.history_delete_btn = ttk.Button(actions, text="Supprimer", style="Danger.TButton", command=self._history_delete_selected)
        self.history_delete_btn.grid(row=0, column=3, sticky="ew", padx=(8, 0))

    def _build_social_workspace(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        scroll_shell, scroll_canvas, scroll_inner, scroll_window = self._create_scrollable_region(
            parent,
            self.colors["bg"],
        )
        scroll_shell.grid(row=0, column=0, sticky="nsew")
        self.social_scroll_canvas = scroll_canvas
        self.social_scroll_frame = scroll_inner
        self.social_scroll_window_id = scroll_window
        scroll_inner.columnconfigure(0, weight=1)

        header_shell, header_card = self._create_card(scroll_inner, inner_padding=(18, 18))
        header_shell.grid(row=0, column=0, sticky="ew")
        header_card.columnconfigure(0, weight=1)
        title_wrap = tk.Frame(header_card, bg=self.colors["panel"])
        title_wrap.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_wrap,
            text="Publication",
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["title"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            title_wrap,
            text="Connecte TikTok et Facebook puis publie un rendu optimisé.",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        action_wrap = tk.Frame(header_card, bg=self.colors["panel"])
        action_wrap.grid(row=0, column=1, sticky="e")
        self.social_help_btn = ttk.Button(action_wrap, text="Aide", style="Secondary.TButton", command=self._show_social_help)
        self.social_help_btn.pack(side="left")
        self.social_tiktok_portal_btn = ttk.Button(action_wrap, text="Portail TikTok", style="SmallGhost.TButton", command=lambda: self._open_url(TIKTOK_DEVELOPER_PORTAL_URL))
        self.social_tiktok_portal_btn.pack(side="left", padx=(8, 0))
        self.social_facebook_portal_btn = ttk.Button(action_wrap, text="Portail Facebook", style="SmallGhost.TButton", command=lambda: self._open_url(FACEBOOK_DEVELOPER_PORTAL_URL))
        self.social_facebook_portal_btn.pack(side="left", padx=(8, 0))

        status_shell, status_card = self._create_soft_panel(header_card, "panel_alt_2", inner_padding=(12, 10))
        status_shell.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        tk.Label(
            status_card,
            textvariable=self.social_status_var,
            bg=self.colors["panel_alt_2"],
            fg=self.colors["ink"],
            font=self.fonts["ui_small"],
            justify="left",
            anchor="w",
            wraplength=980,
        ).pack(fill="x")

        body = tk.Frame(scroll_inner, bg=self.colors["bg"])
        body.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=4)

        accounts = tk.Frame(body, bg=self.colors["bg"])
        accounts.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        accounts.columnconfigure(0, weight=1)

        tiktok_shell, tiktok_card = self._create_card(accounts, inner_padding=(16, 16))
        tiktok_shell.grid(row=0, column=0, sticky="ew")
        tiktok_card.columnconfigure(0, weight=4)
        tiktok_card.columnconfigure(1, weight=2)
        tk.Label(tiktok_card, text="TikTok", bg=self.colors["panel"], fg=self.colors["ink"], font=self.fonts["section"]).grid(row=0, column=0, sticky="w")
        tk.Label(tiktok_card, textvariable=self.tiktok_account_var, bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_small"], justify="left", anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        tk.Label(tiktok_card, text="Client key", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=2, column=0, sticky="w")
        tk.Label(tiktok_card, text="Redirect port", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=2, column=1, sticky="w", padx=(10, 0))
        self.tiktok_client_key_entry = ttk.Entry(tiktok_card, textvariable=self.tiktok_client_key_var)
        self.tiktok_client_key_entry.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.tiktok_redirect_port_entry = ttk.Entry(tiktok_card, textvariable=self.tiktok_redirect_port_var, width=10)
        self.tiktok_redirect_port_entry.grid(row=3, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        tk.Label(tiktok_card, text="Client secret", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.tiktok_client_secret_entry = ttk.Entry(tiktok_card, textvariable=self.tiktok_client_secret_var, show="*")
        self.tiktok_client_secret_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        tk.Label(tiktok_card, text="OAuth via navigateur puis retour automatique vers SoraStudio.", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_small"], justify="left", wraplength=380).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tiktok_actions = tk.Frame(tiktok_card, bg=self.colors["panel"])
        tiktok_actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.tiktok_save_btn = ttk.Button(tiktok_actions, text="Enregistrer", style="Ghost.TButton", command=self._save_tiktok_settings)
        self.tiktok_save_btn.pack(side="left")
        self.tiktok_connect_btn = ttk.Button(tiktok_actions, text="Connecter", style="Secondary.TButton", command=self._connect_tiktok)
        self.tiktok_connect_btn.pack(side="left", padx=(8, 0))
        self.tiktok_disconnect_btn = ttk.Button(tiktok_actions, text="Déconnecter", style="Ghost.TButton", command=self._disconnect_tiktok)
        self.tiktok_disconnect_btn.pack(side="left", padx=(8, 0))

        facebook_shell, facebook_card = self._create_card(accounts, inner_padding=(16, 16))
        facebook_shell.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        facebook_card.columnconfigure(0, weight=4)
        facebook_card.columnconfigure(1, weight=2)
        tk.Label(facebook_card, text="Facebook Page", bg=self.colors["panel"], fg=self.colors["ink"], font=self.fonts["section"]).grid(row=0, column=0, sticky="w")
        tk.Label(facebook_card, textvariable=self.facebook_account_var, bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_small"], justify="left", anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        tk.Label(facebook_card, text="App ID", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=2, column=0, sticky="w")
        tk.Label(facebook_card, text="Redirect port", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=2, column=1, sticky="w", padx=(10, 0))
        self.facebook_app_id_entry = ttk.Entry(facebook_card, textvariable=self.facebook_app_id_var)
        self.facebook_app_id_entry.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.facebook_redirect_port_entry = ttk.Entry(facebook_card, textvariable=self.facebook_redirect_port_var, width=10)
        self.facebook_redirect_port_entry.grid(row=3, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        tk.Label(facebook_card, text="App secret", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=4, column=0, sticky="w", pady=(8, 0))
        tk.Label(facebook_card, text="Graph version", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=4, column=1, sticky="w", pady=(8, 0), padx=(10, 0))
        self.facebook_app_secret_entry = ttk.Entry(facebook_card, textvariable=self.facebook_app_secret_var, show="*")
        self.facebook_app_secret_entry.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        self.facebook_graph_version_entry = ttk.Entry(facebook_card, textvariable=self.facebook_graph_version_var)
        self.facebook_graph_version_entry.grid(row=5, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        tk.Label(facebook_card, text="Page active", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.facebook_page_combo = ttk.Combobox(facebook_card, textvariable=self.facebook_page_var, values=(), state="disabled", style="Readable.TCombobox")
        self.facebook_page_combo.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.facebook_page_combo.bind("<<ComboboxSelected>>", self._on_facebook_page_change)
        self._bind_dropdown_open(self.facebook_page_combo)
        facebook_actions = tk.Frame(facebook_card, bg=self.colors["panel"])
        facebook_actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.facebook_save_btn = ttk.Button(facebook_actions, text="Enregistrer", style="Ghost.TButton", command=self._save_facebook_settings)
        self.facebook_save_btn.pack(side="left")
        self.facebook_connect_btn = ttk.Button(facebook_actions, text="Connecter", style="Secondary.TButton", command=self._connect_facebook)
        self.facebook_connect_btn.pack(side="left", padx=(8, 0))
        self.facebook_disconnect_btn = ttk.Button(facebook_actions, text="Déconnecter", style="Ghost.TButton", command=self._disconnect_facebook)
        self.facebook_disconnect_btn.pack(side="left", padx=(8, 0))

        publish_shell, publish_card = self._create_card(body, inner_padding=(16, 16))
        publish_shell.grid(row=0, column=1, sticky="nsew")
        publish_card.columnconfigure(0, weight=1)
        publish_card.columnconfigure(1, weight=1)
        tk.Label(publish_card, text="Publier un rendu", bg=self.colors["panel"], fg=self.colors["ink"], font=self.fonts["section"]).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(publish_card, text="Vidéo source", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.social_video_combo = ttk.Combobox(publish_card, textvariable=self.social_video_var, values=(), state="readonly", style="Readable.TCombobox")
        self.social_video_combo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.social_video_combo.bind("<<ComboboxSelected>>", self._on_social_video_change)
        self._bind_dropdown_open(self.social_video_combo)
        tk.Label(publish_card, text="Légende", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.social_caption_entry = ttk.Entry(publish_card, textvariable=self.social_caption_var)
        self.social_caption_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        tk.Label(publish_card, text="Cibles", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=5, column=0, sticky="w", pady=(12, 0))
        tk.Label(publish_card, text="Confidentialité TikTok", bg=self.colors["panel"], fg=self.colors["muted"], font=self.fonts["ui_bold_small"]).grid(row=5, column=1, sticky="w", pady=(12, 0), padx=(10, 0))
        targets = tk.Frame(publish_card, bg=self.colors["panel"])
        targets.grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.social_tiktok_check = self._build_social_target_check(targets, "TikTok", self.social_tiktok_var)
        self.social_tiktok_check.pack(side="left")
        self.social_facebook_check = self._build_social_target_check(targets, "Facebook Page", self.social_facebook_var)
        self.social_facebook_check.pack(side="left", padx=(12, 0))
        self.tiktok_privacy_combo = ttk.Combobox(publish_card, textvariable=self.tiktok_privacy_var, values=(), state="disabled", style="Readable.TCombobox")
        self.tiktok_privacy_combo.grid(row=6, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        self._bind_dropdown_open(self.tiktok_privacy_combo)
        self.social_publish_btn = ttk.Button(publish_card, text="Publier la vidéo", style="Primary.TButton", command=self._publish_selected_social)
        self.social_publish_btn.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        posts_shell, posts_card = self._create_card(scroll_inner, inner_padding=(16, 16))
        posts_shell.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        posts_card.columnconfigure(0, weight=1)
        tk.Label(posts_card, text="Publications récentes", bg=self.colors["panel"], fg=self.colors["ink"], font=self.fonts["section"]).grid(row=0, column=0, sticky="w")
        posts_list_shell, _posts_canvas, posts_inner, _posts_window = self._create_scrollable_region(posts_card, self.colors["panel"])
        posts_list_shell.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.social_posts_list_frame = posts_inner

    def _show_banner(self, message: str, level: str = "info", auto_hide_ms: int = 5000) -> None:
        if self.inline_banner_wrap is None or self.inline_banner_label is None:
            return
        palettes = {
            "info": (self.colors["banner_info_bg"], self.colors["info_text"]),
            "warn": (self.colors["banner_warn_bg"], self.colors["log_warn"]),
            "error": (self.colors["banner_error_bg"], self.colors["error_text"]),
        }
        bg, fg = palettes.get(level, palettes["info"])
        self.inline_banner_wrap.configure(bg=bg, highlightbackground=self.colors["panel_border"])
        self.inline_banner_label.configure(bg=bg, fg=fg, text=message)
        if not self.inline_banner_wrap.winfo_ismapped():
            pack_kwargs: dict[str, Any] = {"fill": "x", "padx": 18, "pady": (18, 0)}
            if getattr(self, "main_shell", None) is not None:
                pack_kwargs["before"] = self.main_shell
            self.inline_banner_wrap.pack(**pack_kwargs)
        if getattr(self, "_banner_after_id", None):
            self.after_cancel(self._banner_after_id)
            self._banner_after_id = None
        if auto_hide_ms > 0:
            self._banner_after_id = self.after(auto_hide_ms, self._hide_banner)

    def _hide_banner(self) -> None:
        if self.inline_banner_wrap is not None and self.inline_banner_wrap.winfo_ismapped():
            self.inline_banner_wrap.pack_forget()

    def _show_toast(self, message: str, level: str = "info", auto_hide_ms: int = 3200) -> None:
        if self.toast_host is None:
            return
        palettes = {
            "info": (self.colors["toast_bg"], self.colors["ink"]),
            "success": (self.colors["success"], self.colors["success_text"]),
            "warn": (self.colors["banner_warn_bg"], self.colors["log_warn"]),
            "error": (self.colors["error"], self.colors["error_text"]),
        }
        bg, fg = palettes.get(level, palettes["info"])
        toast = tk.Frame(
            self.toast_host,
            bg=bg,
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        tk.Label(
            toast,
            text=message,
            bg=bg,
            fg=fg,
            font=self.fonts["ui_small"],
            justify="left",
        ).pack(fill="x")
        toast.pack(fill="x", pady=(0, 8))
        self.after(auto_hide_ms, toast.destroy)

    def _push_activity(
        self,
        kind: str,
        message: str,
        title: str = "",
    ) -> None:
        self.activity_feed.append(
            {
                "kind": kind,
                "title": title,
                "message": message,
                "timestamp": time.strftime("%H:%M:%S"),
            }
        )
        self.activity_feed = self.activity_feed[-120:]
        self._render_activity_feed()

    def _render_activity_feed(self) -> None:
        if self.feed_frame is None:
            return
        for child in self.feed_frame.winfo_children():
            child.destroy()

        if not self.activity_feed:
            empty_shell, empty_card = self._create_soft_panel(
                self.feed_frame,
                "panel_alt",
                inner_padding=(18, 18),
            )
            empty_shell.pack(fill="x", padx=12, pady=12)
            tk.Label(
                empty_card,
                text="Décris la scène, le style, le mouvement et la durée désirée.",
                bg=self.colors["panel_alt"],
                fg=self.colors["ink"],
                font=self.fonts["ui_bold"],
                justify="left",
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                empty_card,
                text="Le fil d'activité affichera ensuite le prompt, les statuts, les erreurs et le résultat final.",
                bg=self.colors["panel_alt"],
                fg=self.colors["muted"],
                font=self.fonts["ui_small"],
                justify="left",
                wraplength=720,
            ).pack(anchor="w", pady=(8, 0))
            return

        palette = {
            "system": (self.colors["panel_alt"], self.colors["ink"], self.colors["muted"]),
            "info": (self.colors["panel_alt"], self.colors["ink"], self.colors["muted"]),
            "prompt": (self.colors["accent_soft_2"], self.colors["ink"], self.colors["accent"]),
            "success": (self.colors["success"], self.colors["success_text"], self.colors["success_text"]),
            "warn": (self.colors["banner_warn_bg"], self.colors["log_warn"], self.colors["log_warn"]),
            "error": (self.colors["error"], self.colors["error_text"], self.colors["error_text"]),
            "result": (self.colors["panel_tint"], self.colors["ink"], self.colors["accent"]),
        }
        for item in self.activity_feed:
            bg, fg, meta = palette.get(str(item.get("kind") or "info"), palette["info"])
            shell, card = self._create_soft_panel(self.feed_frame, "panel", inner_padding=(0, 0))
            shell.pack(fill="x", padx=12, pady=(12, 0))
            card.configure(bg=bg, padx=18, pady=16)
            top = tk.Frame(card, bg=bg)
            top.pack(fill="x")
            tk.Label(
                top,
                text=str(item.get("title") or "Journal"),
                bg=bg,
                fg=fg,
                font=self.fonts["ui_bold_small"],
            ).pack(side="left")
            tk.Label(
                top,
                text=str(item.get("timestamp") or ""),
                bg=bg,
                fg=meta,
                font=self.fonts["ui_caption"],
            ).pack(side="right")
            tk.Label(
                card,
                text=str(item.get("message") or ""),
                bg=bg,
                fg=self.colors["ink"] if item.get("kind") not in {"success", "warn", "error"} else fg,
                font=self.fonts["ui_small"],
                justify="left",
                wraplength=760,
            ).pack(fill="x", pady=(10, 0))
        if self.feed_canvas is not None:
            self.after_idle(lambda: self.feed_canvas.yview_moveto(1.0))

    def _on_hero_resize(self, event: tk.Event) -> None:
        if self.hero_canvas is None:
            return
        canvas = self.hero_canvas
        width = event.width
        height = event.height

        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill=self.colors["hero_top"], outline="")

        gradient_bands = (
            self.colors["hero_top"],
            self.colors["bg_alt"],
            self.colors["hero_bottom"],
        )
        for idx, color in enumerate(gradient_bands):
            y0 = int(idx * height / len(gradient_bands))
            y1 = int((idx + 1) * height / len(gradient_bands))
            canvas.create_rectangle(0, y0, width, y1, fill=color, outline="")

        canvas.create_polygon(
            0,
            int(height * 0.2),
            int(width * 0.36),
            0,
            width,
            0,
            width,
            height,
            0,
            height,
            fill=self.colors["bg_alt"],
            outline="",
        )
        canvas.create_oval(
            width - 320,
            -110,
            width + 80,
            190,
            fill=self.colors["hero_soft"],
            outline="",
        )
        canvas.create_oval(
            width - 230,
            -30,
            width + 150,
            220,
            fill=self.colors["panel_alt"],
            outline="",
        )

        title_x = 28
        title_y = 38
        canvas.create_text(
            title_x,
            title_y,
            anchor="nw",
            text="SoraStudio",
            fill=self.colors["ink"],
            font=self.fonts["hero"],
        )
        canvas.create_line(
            title_x,
            title_y + 40,
            title_x + 150,
            title_y + 40,
            fill=self.colors["accent"],
            width=3,
            capstyle="round",
        )

        logo = self._get_logo_image()
        if logo is not None:
            logo_w = int(logo.width())
            logo_h = int(logo.height())
            image_x = width - logo_w - 42
            image_y = max(16, (height - logo_h) // 2)
            canvas.create_oval(
                image_x - 36,
                image_y - 22,
                image_x + logo_w + 16,
                image_y + logo_h + 22,
                fill=self.colors["accent_soft"],
                outline="",
            )
            canvas.create_image(image_x, image_y, image=logo, anchor="nw")

    def _build_left_panel(self, parent: tk.Frame) -> None:
        section_gap = int(self.metrics["section_gap"])

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        controls_row = tk.Frame(parent, bg=self.colors["panel"])
        controls_row.grid(row=0, column=0, sticky="ew")
        controls_row.columnconfigure(0, weight=3)
        controls_row.columnconfigure(1, weight=1)
        controls_row.columnconfigure(2, weight=1)

        model_shell, model_card = self._create_soft_panel(
            controls_row, "panel_alt_2", inner_padding=(12, 10)
        )
        model_shell.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        tk.Label(
            model_card,
            text="Modele",
            bg=self.colors["panel_alt_2"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w", pady=(0, 8))
        model_entry = ttk.Entry(model_card, textvariable=self.model_var)
        model_entry.pack(fill="x")
        self.controls.append(model_entry)

        duration_shell, duration_card = self._create_soft_panel(
            controls_row, "panel_alt_2", inner_padding=(12, 10)
        )
        duration_shell.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        tk.Label(
            duration_card,
            text="Duree (s)",
            bg=self.colors["panel_alt_2"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w", pady=(0, 8))
        seconds_combo = ttk.Combobox(
            duration_card,
            textvariable=self.seconds_var,
            values=SECONDS_OPTIONS,
            state="readonly",
            style="Readable.TCombobox",
            width=9,
        )
        seconds_combo.pack(fill="x")
        self._bind_dropdown_open(seconds_combo)

        size_shell, size_card = self._create_soft_panel(
            controls_row, "panel_alt_2", inner_padding=(12, 10)
        )
        size_shell.grid(row=0, column=2, sticky="ew")
        tk.Label(
            size_card,
            text="Format",
            bg=self.colors["panel_alt_2"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w", pady=(0, 8))
        size_combo = ttk.Combobox(
            size_card,
            textvariable=self.size_var,
            values=SIZE_OPTIONS,
            state="readonly",
            style="Readable.TCombobox",
        )
        size_combo.pack(fill="x")
        self._bind_dropdown_open(size_combo)
        self.size_combo = size_combo
        self.controls.extend([seconds_combo, size_combo])

        social_shell, social_card = self._create_soft_panel(
            parent, "panel_alt_2", inner_padding=(12, 10)
        )
        social_shell.grid(row=1, column=0, sticky="ew", pady=(section_gap, 0))
        self.social_mode_check = tk.Checkbutton(
            social_card,
            text="Pour reseaux",
            variable=self.social_mode_var,
            command=self._apply_social_mode,
            bg=self.colors["panel_alt_2"],
            fg=self.colors["ink"],
            selectcolor=self.colors["panel_alt"],
            activebackground=self.colors["panel_alt_2"],
            activeforeground=self.colors["ink"],
            font=self.fonts["ui_bold_small"],
            highlightthickness=0,
            bd=0,
        )
        self.social_mode_check.pack(anchor="w")
        tk.Label(
            social_card,
            textvariable=self.social_note_var,
            bg=self.colors["panel_alt_2"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))
        self.controls.append(self.social_mode_check)

        prompt_section = tk.Frame(parent, bg=self.colors["panel"])
        prompt_section.grid(row=2, column=0, sticky="nsew", pady=(section_gap, 0))
        prompt_section.columnconfigure(0, weight=1)
        prompt_section.rowconfigure(1, weight=1)

        prompt_header = tk.Frame(prompt_section, bg=self.colors["panel"])
        prompt_header.grid(row=0, column=0, sticky="ew")
        prompt_header.columnconfigure(0, weight=1)
        ttk.Label(prompt_header, text="Prompt", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        prompt_border = tk.Frame(prompt_section, bg=self.colors["input_border"], bd=0, padx=1, pady=1)
        prompt_border.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        prompt_border.columnconfigure(0, weight=1)
        prompt_border.rowconfigure(0, weight=1)

        self.prompt_text = tk.Text(
            prompt_border,
            height=9,
            font=self.fonts["ui"],
            wrap="word",
            bg=self.colors["input_bg"],
            fg=self.colors["ink"],
            insertbackground=self.colors["ink"],
            relief="flat",
            bd=0,
            padx=14,
            pady=14,
            highlightthickness=0,
        )
        self.prompt_text.grid(row=0, column=0, sticky="nsew")
        self.prompt_text.insert("1.0", DEFAULT_PROMPT)
        self.controls.append(self.prompt_text)

        output_shell, output_card = self._create_soft_panel(
            parent, "panel_tint", inner_padding=(14, 14)
        )
        output_shell.grid(row=3, column=0, sticky="ew", pady=(section_gap, 0))
        tk.Label(
            output_card,
            text="Sortie",
            bg=self.colors["panel_tint"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).pack(anchor="w", pady=(2, 12))

        tk.Label(
            output_card,
            text="Nom de la video",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w")
        name_wrap = tk.Frame(output_card, bg=self.colors["panel_tint"])
        name_wrap.pack(fill="x", pady=(6, 10))
        name_wrap.columnconfigure(0, weight=1)
        name_entry = ttk.Entry(name_wrap, textvariable=self.video_name_var)
        name_entry.grid(row=0, column=0, sticky="ew")
        name_hint = tk.Label(
            name_wrap,
            text=".MP4",
            bg=self.colors["accent_soft_2"],
            fg=self.colors["accent"],
            font=self.fonts["ui_bold_small"],
            padx=10,
            pady=6,
        )
        name_hint.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.controls.append(name_entry)

        tk.Label(
            output_card,
            text="Fichier de sortie",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w")
        output_wrap = tk.Frame(output_card, bg=self.colors["panel_tint"])
        output_wrap.pack(fill="x", pady=(6, 0))
        output_wrap.columnconfigure(0, weight=1)
        output_entry = ttk.Entry(output_wrap, textvariable=self.output_var)
        output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        browse_btn = ttk.Button(
            output_wrap,
            text="Parcourir",
            style="Secondary.TButton",
            command=self._pick_output,
        )
        browse_btn.grid(row=0, column=1, sticky="e")
        self.controls.extend([output_entry, browse_btn])

        action_wrap = tk.Frame(parent, bg=self.colors["panel"])
        action_wrap.grid(row=4, column=0, sticky="ew", pady=(section_gap, 0))
        action_wrap.columnconfigure(0, weight=3)
        action_wrap.columnconfigure(1, weight=2)

        self.generate_btn = ttk.Button(
            action_wrap,
            text="Generer la video",
            style="Primary.TButton",
            command=self._start_generation,
        )
        self.generate_btn.grid(row=0, column=0, sticky="ew")

        self.reset_btn = ttk.Button(
            action_wrap,
            text="Reinitialiser",
            style="Secondary.TButton",
            command=self._reset_form,
        )
        self.reset_btn.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        self.controls.extend([self.generate_btn, self.reset_btn])

    def _build_status_panel(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=self.colors["panel"])
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Production Live", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.status_chip = tk.Label(
            header,
            text="PRET",
            bg=self.colors["info"],
            fg=self.colors["info_text"],
            font=self.fonts["ui_bold_small"],
            padx=10,
            pady=4,
            bd=0,
        )
        self.status_chip.grid(row=0, column=1, sticky="e")

        status_copy = tk.Label(
            parent,
            textvariable=self.status_var,
            bg=self.colors["panel"],
            fg=self.colors["ink"],
            font=self.fonts["ui_bold"],
            anchor="w",
        )
        status_copy.pack(fill="x", pady=(14, 10))

        progress_shell, progress_card = self._create_soft_panel(
            parent, "panel_tint", inner_padding=(12, 12)
        )
        progress_shell.pack(fill="x")
        tk.Label(
            progress_card,
            text="Progression",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            progress_card,
            textvariable=self.progress_text_var,
            bg=self.colors["panel_tint"],
            fg=self.colors["accent"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=0, column=1, sticky="e")
        progress_card.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(
            progress_card,
            style="Blue.Horizontal.TProgressbar",
            mode="determinate",
            variable=self.progress_var,
            maximum=100,
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        metrics = tk.Frame(parent, bg=self.colors["panel"])
        metrics.pack(fill="x", pady=(14, 0))
        metrics.columnconfigure(0, weight=1)
        metrics.columnconfigure(1, weight=1)

        self._make_metric(metrics, 0, 0, "Modele", self.preview_model_var)
        self._make_metric(metrics, 0, 1, "Duree", self.preview_seconds_var)
        self._make_metric(metrics, 1, 0, "Format", self.preview_size_var)
        self._make_metric(metrics, 1, 1, "Sortie", self.preview_output_var)

    def _make_metric(
        self,
        parent: tk.Frame,
        row: int,
        column: int,
        title: str,
        value_var: tk.StringVar,
    ) -> None:
        box_shell = tk.Frame(parent, bg=self.colors["card_shadow"], bd=0, highlightthickness=0)
        box_shell.grid(
            row=row,
            column=column,
            sticky="ew",
            padx=(0, 8) if column == 0 else (0, 0),
            pady=(0, 8),
        )
        box = tk.Frame(
            box_shell,
            bg=self.colors["panel_alt_2"],
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        box.pack(fill="both", expand=True, padx=(0, 1), pady=(0, 1))

        tk.Label(
            box,
            text=title,
            bg=self.colors["panel_alt_2"],
            fg=self.colors["muted_soft"],
            font=self.fonts["ui_caption"],
        ).pack(anchor="w")
        tk.Label(
            box,
            textvariable=value_var,
            bg=self.colors["panel_alt_2"],
            fg=self.colors["ink"],
            font=self.fonts["ui_bold"],
        ).pack(anchor="w", pady=(6, 0))

    def _build_log_panel(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        log_header = tk.Frame(parent, bg=self.colors["panel"], padx=14, pady=12)
        log_header.grid(row=0, column=0, sticky="ew")
        log_header.columnconfigure(0, weight=1)

        ttk.Label(log_header, text="Journal", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.clear_log_btn = ttk.Button(
            log_header,
            text="Vider",
            style="SmallGhost.TButton",
            command=self._clear_log,
        )
        self.clear_log_btn.grid(row=0, column=1, sticky="ne")

        log_wrap = tk.Frame(
            parent,
            bg=self.colors["panel_alt"],
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        log_wrap.grid(row=1, column=0, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_wrap,
            height=14,
            font=self.fonts["mono"],
            wrap="word",
            bg=self.colors["log_bg"],
            fg=self.colors["log_info"],
            insertbackground=self.colors["log_info"],
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            highlightthickness=0,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        scroll = ttk.Scrollbar(
            log_wrap,
            orient="vertical",
            command=self.log_text.yview,
            style="App.Vertical.TScrollbar",
        )
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        self.log_text.tag_configure("info", foreground=self.colors["log_info"])
        self.log_text.tag_configure("success", foreground=self.colors["log_success"])
        self.log_text.tag_configure("warn", foreground=self.colors["log_warn"])
        self.log_text.tag_configure("error", foreground=self.colors["log_error"])
        self.log_text.tag_configure("system", foreground=self.colors["log_system"])
        self.log_text.configure(state="disabled")

    def _build_history_tab(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        shell, card = self._create_card(parent, inner_padding=self.metrics["history_padding"])
        shell.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        top = tk.Frame(card, bg=self.colors["panel"])
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text="Mes videos", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        tk.Label(
            top,
            textvariable=self.history_count_var,
            bg=self.colors["accent_soft_2"],
            fg=self.colors["accent"],
            font=self.fonts["ui_bold_small"],
            padx=10,
            pady=5,
        ).grid(row=0, column=1, sticky="ne")

        actions = tk.Frame(card, bg=self.colors["panel"])
        actions.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        ttk.Button(
            actions,
            text="Rafraichir",
            style="Ghost.TButton",
            command=self._history_refresh,
        ).pack(side="left")
        self.history_open_btn = ttk.Button(
            actions,
            text="Visualiser",
            style="Secondary.TButton",
            command=self._history_open_selected,
        )
        self.history_open_btn.pack(side="left", padx=(8, 0))
        self.history_export_btn = ttk.Button(
            actions,
            text="Exporter",
            style="Secondary.TButton",
            command=self._history_export_selected,
        )
        self.history_export_btn.pack(side="left", padx=(8, 0))
        self.history_delete_btn = ttk.Button(
            actions,
            text="Supprimer",
            style="Danger.TButton",
            command=self._history_delete_selected,
        )
        self.history_delete_btn.pack(side="left", padx=(8, 0))

        table_wrap = tk.Frame(card, bg=self.colors["panel_alt"], padx=12, pady=12)
        table_wrap.grid(row=2, column=0, sticky="nsew")
        table_wrap.columnconfigure(0, weight=1)
        table_wrap.rowconfigure(0, weight=1)

        table_border = tk.Frame(
            table_wrap,
            bg=self.colors["panel"],
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        table_border.grid(row=0, column=0, sticky="nsew")
        table_border.columnconfigure(0, weight=1)
        table_border.rowconfigure(0, weight=1)

        columns = ("name", "date", "duration", "resolution", "model", "size")
        self.history_tree = ttk.Treeview(
            table_border,
            columns=columns,
            show="headings",
            style="History.Treeview",
            selectmode="browse",
        )
        self.history_tree.grid(row=0, column=0, sticky="nsew")

        self.history_tree.heading("name", text="Nom")
        self.history_tree.heading("date", text="Date")
        self.history_tree.heading("duration", text="Duree")
        self.history_tree.heading("resolution", text="Format")
        self.history_tree.heading("model", text="Modele")
        self.history_tree.heading("size", text="Taille")

        self.history_tree.column("name", width=240, minwidth=180, anchor="w")
        self.history_tree.column("date", width=145, minwidth=120, anchor="center")
        self.history_tree.column("duration", width=82, minwidth=70, anchor="center")
        self.history_tree.column("resolution", width=110, minwidth=90, anchor="center")
        self.history_tree.column("model", width=120, minwidth=100, anchor="center")
        self.history_tree.column("size", width=95, minwidth=80, anchor="e")

        history_scroll = ttk.Scrollbar(
            table_border,
            orient="vertical",
            command=self.history_tree.yview,
            style="App.Vertical.TScrollbar",
        )
        history_scroll.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=history_scroll.set)

        self.history_tree.bind("<<TreeviewSelect>>", self._on_history_select)
        self.history_tree.bind("<Double-1>", lambda _event: self._history_open_selected())

        details_shell, details_card = self._create_soft_panel(
            card, "panel_alt", inner_padding=(14, 12)
        )
        details_shell.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        tk.Label(
            details_card,
            text="Selection",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).pack(anchor="w")
        tk.Message(
            details_card,
            textvariable=self.history_details_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["ink"],
            font=self.fonts["ui_small"],
            width=760,
            justify="left",
        ).pack(fill="x", pady=(6, 0))

    def _build_social_tab(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        scroll_wrap = tk.Frame(parent, bg=self.colors["bg"])
        scroll_wrap.grid(row=0, column=0, sticky="nsew")
        scroll_wrap.columnconfigure(0, weight=1)
        scroll_wrap.rowconfigure(0, weight=1)

        self.social_scroll_canvas = tk.Canvas(
            scroll_wrap,
            bg=self.colors["bg"],
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.social_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        outer_scroll = ttk.Scrollbar(
            scroll_wrap,
            orient="vertical",
            command=self.social_scroll_canvas.yview,
            style="App.Vertical.TScrollbar",
        )
        outer_scroll.grid(row=0, column=1, sticky="ns")
        self.social_scroll_canvas.configure(yscrollcommand=outer_scroll.set)

        self.social_scroll_frame = tk.Frame(self.social_scroll_canvas, bg=self.colors["bg"])
        self.social_scroll_window_id = self.social_scroll_canvas.create_window(
            (0, 0), window=self.social_scroll_frame, anchor="nw"
        )
        self.social_scroll_frame.columnconfigure(0, weight=1)
        self.social_scroll_frame.bind("<Configure>", self._on_social_frame_configure)
        self.social_scroll_canvas.bind("<Configure>", self._on_social_canvas_configure)
        self.social_scroll_canvas.bind("<Enter>", self._bind_social_mousewheel)
        self.social_scroll_canvas.bind("<Leave>", self._unbind_social_mousewheel)

        shell, card = self._create_card(self.social_scroll_frame, inner_padding=(10, 8))
        shell.grid(row=0, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)

        top = tk.Frame(card, bg=self.colors["panel"])
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        title_wrap = tk.Frame(top, bg=self.colors["panel"])
        title_wrap.grid(row=0, column=0, sticky="w")
        ttk.Label(title_wrap, text="Reseaux sociaux", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            title_wrap,
            text="TikTok + Facebook Reels",
            style="SectionNote.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        action_wrap = tk.Frame(top, bg=self.colors["panel"])
        action_wrap.grid(row=0, column=1, rowspan=2, sticky="e")
        self.social_help_btn = ttk.Button(
            action_wrap,
            text="Aide",
            style="Secondary.TButton",
            command=self._show_social_help,
        )
        self.social_help_btn.pack(side="left")
        self.social_tiktok_portal_btn = ttk.Button(
            action_wrap,
            text="Portail TikTok",
            style="SmallGhost.TButton",
            command=lambda: self._open_url(TIKTOK_DEVELOPER_PORTAL_URL),
        )
        self.social_tiktok_portal_btn.pack(side="left", padx=(8, 0))
        self.social_facebook_portal_btn = ttk.Button(
            action_wrap,
            text="Portail Facebook",
            style="SmallGhost.TButton",
            command=lambda: self._open_url(FACEBOOK_DEVELOPER_PORTAL_URL),
        )
        self.social_facebook_portal_btn.pack(side="left", padx=(8, 0))

        status_shell, status_card = self._create_soft_panel(card, "panel_alt_2", inner_padding=(10, 8))
        status_shell.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        tk.Label(
            status_card,
            textvariable=self.social_status_var,
            bg=self.colors["panel_alt_2"],
            fg=self.colors["ink"],
            font=self.fonts["ui_small"],
            justify="left",
            anchor="w",
            wraplength=860,
        ).pack(fill="x")

        body = tk.Frame(card, bg=self.colors["panel"])
        body.grid(row=2, column=0, sticky="ew")
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)

        accounts = tk.Frame(body, bg=self.colors["panel"])
        accounts.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        accounts.columnconfigure(0, weight=1)

        tiktok_shell, tiktok_card = self._create_soft_panel(accounts, "panel_alt", inner_padding=(10, 10))
        tiktok_shell.grid(row=0, column=0, sticky="ew")
        tiktok_card.columnconfigure(0, weight=4)
        tiktok_card.columnconfigure(1, weight=2)
        tk.Label(
            tiktok_card,
            text="TikTok",
            bg=self.colors["panel_alt"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            tiktok_card,
            textvariable=self.tiktok_account_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        tk.Label(
            tiktok_card,
            text="Client key",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=2, column=0, sticky="w")
        tk.Label(
            tiktok_card,
            text="Redirect port",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=2, column=1, sticky="w", padx=(10, 0))
        self.tiktok_client_key_entry = ttk.Entry(tiktok_card, textvariable=self.tiktok_client_key_var)
        self.tiktok_client_key_entry.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.tiktok_redirect_port_entry = ttk.Entry(
            tiktok_card, textvariable=self.tiktok_redirect_port_var, width=10
        )
        self.tiktok_redirect_port_entry.grid(row=3, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        tk.Label(
            tiktok_card,
            text="Client secret",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.tiktok_client_secret_entry = ttk.Entry(
            tiktok_card,
            textvariable=self.tiktok_client_secret_var,
            show="*",
        )
        self.tiktok_client_secret_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        tk.Label(
            tiktok_card,
            text="OAuth via navigateur: enregistre les champs, puis clique sur Connecter.",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            justify="left",
            wraplength=340,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tiktok_actions = tk.Frame(tiktok_card, bg=self.colors["panel_alt"])
        tiktok_actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.tiktok_save_btn = ttk.Button(
            tiktok_actions,
            text="Enregistrer",
            style="Ghost.TButton",
            command=self._save_tiktok_settings,
        )
        self.tiktok_save_btn.pack(side="left")
        self.tiktok_connect_btn = ttk.Button(
            tiktok_actions,
            text="Connecter",
            style="Secondary.TButton",
            command=self._connect_tiktok,
        )
        self.tiktok_connect_btn.pack(side="left", padx=(8, 0))
        self.tiktok_disconnect_btn = ttk.Button(
            tiktok_actions,
            text="Deconnecter",
            style="Ghost.TButton",
            command=self._disconnect_tiktok,
        )
        self.tiktok_disconnect_btn.pack(side="left", padx=(8, 0))

        facebook_shell, facebook_card = self._create_soft_panel(
            accounts, "panel_alt", inner_padding=(10, 10)
        )
        facebook_shell.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        facebook_card.columnconfigure(0, weight=4)
        facebook_card.columnconfigure(1, weight=2)
        tk.Label(
            facebook_card,
            text="Facebook Page",
            bg=self.colors["panel_alt"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            facebook_card,
            textvariable=self.facebook_account_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_small"],
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        tk.Label(
            facebook_card,
            text="App ID",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=2, column=0, sticky="w")
        tk.Label(
            facebook_card,
            text="Redirect port",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=2, column=1, sticky="w", padx=(10, 0))
        self.facebook_app_id_entry = ttk.Entry(facebook_card, textvariable=self.facebook_app_id_var)
        self.facebook_app_id_entry.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.facebook_redirect_port_entry = ttk.Entry(
            facebook_card, textvariable=self.facebook_redirect_port_var, width=10
        )
        self.facebook_redirect_port_entry.grid(row=3, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        tk.Label(
            facebook_card,
            text="App secret",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=4, column=0, sticky="w", pady=(6, 0))
        tk.Label(
            facebook_card,
            text="Graph version",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=4, column=1, sticky="w", pady=(6, 0), padx=(10, 0))
        self.facebook_app_secret_entry = ttk.Entry(
            facebook_card,
            textvariable=self.facebook_app_secret_var,
            show="*",
        )
        self.facebook_app_secret_entry.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        self.facebook_graph_version_entry = ttk.Entry(
            facebook_card,
            textvariable=self.facebook_graph_version_var,
        )
        self.facebook_graph_version_entry.grid(row=5, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        tk.Label(
            facebook_card,
            text="Page active",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.facebook_page_combo = ttk.Combobox(
            facebook_card,
            textvariable=self.facebook_page_var,
            values=(),
            state="disabled",
            style="Readable.TCombobox",
        )
        self.facebook_page_combo.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.facebook_page_combo.bind("<<ComboboxSelected>>", self._on_facebook_page_change)
        self._bind_dropdown_open(self.facebook_page_combo)
        facebook_actions = tk.Frame(facebook_card, bg=self.colors["panel_alt"])
        facebook_actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.facebook_save_btn = ttk.Button(
            facebook_actions,
            text="Enregistrer",
            style="Ghost.TButton",
            command=self._save_facebook_settings,
        )
        self.facebook_save_btn.pack(side="left")
        self.facebook_connect_btn = ttk.Button(
            facebook_actions,
            text="Connecter",
            style="Secondary.TButton",
            command=self._connect_facebook,
        )
        self.facebook_connect_btn.pack(side="left", padx=(8, 0))
        self.facebook_disconnect_btn = ttk.Button(
            facebook_actions,
            text="Deconnecter",
            style="Ghost.TButton",
            command=self._disconnect_facebook,
        )
        self.facebook_disconnect_btn.pack(side="left", padx=(8, 0))

        publish_shell, publish_card = self._create_soft_panel(body, "panel_tint", inner_padding=(10, 10))
        publish_shell.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        publish_card.columnconfigure(0, weight=1)
        publish_card.columnconfigure(1, weight=1)
        tk.Label(
            publish_card,
            text="Publication",
            bg=self.colors["panel_tint"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        tk.Label(
            publish_card,
            text="Video source",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.social_video_combo = ttk.Combobox(
            publish_card,
            textvariable=self.social_video_var,
            values=(),
            state="readonly",
            style="Readable.TCombobox",
        )
        self.social_video_combo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.social_video_combo.bind("<<ComboboxSelected>>", self._on_social_video_change)
        self._bind_dropdown_open(self.social_video_combo)

        tk.Label(
            publish_card,
            text="Legende",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.social_caption_entry = ttk.Entry(publish_card, textvariable=self.social_caption_var)
        self.social_caption_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        tk.Label(
            publish_card,
            text="Cibles",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=5, column=0, sticky="w", pady=(6, 0))
        targets = tk.Frame(publish_card, bg=self.colors["panel_tint"])
        targets.grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.social_tiktok_check = self._build_social_target_check(targets, "TikTok", self.social_tiktok_var)
        self.social_tiktok_check.pack(side="left")
        self.social_facebook_check = self._build_social_target_check(
            targets, "Facebook Page", self.social_facebook_var
        )
        self.social_facebook_check.pack(side="left", padx=(12, 0))

        tk.Label(
            publish_card,
            text="Confidentialite TikTok",
            bg=self.colors["panel_tint"],
            fg=self.colors["muted"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=5, column=1, sticky="w", pady=(6, 0), padx=(10, 0))
        self.tiktok_privacy_combo = ttk.Combobox(
            publish_card,
            textvariable=self.tiktok_privacy_var,
            values=(),
            state="disabled",
            style="Readable.TCombobox",
        )
        self.tiktok_privacy_combo.grid(row=6, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        self._bind_dropdown_open(self.tiktok_privacy_combo)

        self.social_publish_btn = ttk.Button(
            publish_card,
            text="Publier la video",
            style="Primary.TButton",
            command=self._publish_selected_social,
        )
        self.social_publish_btn.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        posts_shell, posts_card = self._create_soft_panel(card, "panel_alt", inner_padding=(8, 8))
        posts_shell.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        posts_card.columnconfigure(0, weight=1)
        posts_card.rowconfigure(1, weight=1)
        tk.Label(
            posts_card,
            text="Historique de publication",
            bg=self.colors["panel_alt"],
            fg=self.colors["ink"],
            font=self.fonts["ui_bold_small"],
        ).grid(row=0, column=0, sticky="w")
        posts_border = tk.Frame(
            posts_card,
            bg=self.colors["panel"],
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        posts_border.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        posts_border.columnconfigure(0, weight=1)
        posts_border.rowconfigure(0, weight=1)
        columns = ("video", "platform", "target", "status", "date")
        self.social_posts_tree = ttk.Treeview(
            posts_border,
            columns=columns,
            show="headings",
            style="History.Treeview",
            selectmode="browse",
            height=3,
        )
        self.social_posts_tree.grid(row=0, column=0, sticky="nsew")
        self.social_posts_tree.heading("video", text="Video")
        self.social_posts_tree.heading("platform", text="Plateforme")
        self.social_posts_tree.heading("target", text="Cible")
        self.social_posts_tree.heading("status", text="Etat")
        self.social_posts_tree.heading("date", text="Date")
        self.social_posts_tree.column("video", width=220, minwidth=180, anchor="w")
        self.social_posts_tree.column("platform", width=110, minwidth=100, anchor="center")
        self.social_posts_tree.column("target", width=180, minwidth=140, anchor="w")
        self.social_posts_tree.column("status", width=110, minwidth=90, anchor="center")
        self.social_posts_tree.column("date", width=150, minwidth=130, anchor="center")
        posts_scroll = ttk.Scrollbar(
            posts_border,
            orient="vertical",
            command=self.social_posts_tree.yview,
            style="App.Vertical.TScrollbar",
        )
        posts_scroll.grid(row=0, column=1, sticky="ns")
        self.social_posts_tree.configure(yscrollcommand=posts_scroll.set)

    def _on_social_frame_configure(self, _event: Any = None) -> None:
        if self.social_scroll_canvas is None:
            return
        self.social_scroll_canvas.configure(scrollregion=self.social_scroll_canvas.bbox("all"))

    def _on_social_canvas_configure(self, event: Any) -> None:
        if self.social_scroll_canvas is None or self.social_scroll_window_id is None:
            return
        self.social_scroll_canvas.itemconfigure(self.social_scroll_window_id, width=event.width)

    def _bind_social_mousewheel(self, _event: Any = None) -> None:
        if self.social_scroll_binding_active:
            return
        self.social_scroll_binding_active = True
        self.bind_all("<MouseWheel>", self._on_social_mousewheel)

    def _unbind_social_mousewheel(self, _event: Any = None) -> None:
        if not self.social_scroll_binding_active:
            return
        self.social_scroll_binding_active = False
        self.unbind_all("<MouseWheel>")

    def _on_social_mousewheel(self, event: Any) -> None:
        if self.social_scroll_canvas is None:
            return
        delta = int(-1 * (event.delta / 120))
        self.social_scroll_canvas.yview_scroll(delta, "units")

    def _build_social_target_check(
        self, parent: tk.Frame, text: str, variable: tk.BooleanVar
    ) -> tk.Checkbutton:
        bg = str(parent.cget("bg"))
        check = tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=bg,
            fg=self.colors["ink"],
            selectcolor=self.colors["panel_alt_2"],
            activebackground=bg,
            activeforeground=self.colors["ink"],
            font=self.fonts["ui_bold_small"],
            highlightthickness=0,
            bd=0,
            command=self._update_social_publish_state,
        )
        return check

    def _build_social_video_label(self, record: dict[str, Any]) -> str:
        name = str(record.get("name") or os.path.basename(str(record.get("path") or "")) or "video.mp4")
        date_value = self._format_history_date(str(record.get("created_at") or ""))
        resolution = str(record.get("resolution") or "-")
        return f"{name} | {date_value} | {resolution}"

    def _preferred_social_record(self) -> Optional[dict[str, Any]]:
        current_label = self.social_video_var.get().strip()
        if current_label and current_label in self.social_video_labels:
            return self.social_video_labels[current_label]
        selected_history = self._get_selected_history_record()
        if selected_history:
            return selected_history
        if self.video_records:
            return self.video_records[0]
        return None

    def _refresh_social_video_options(self) -> None:
        preferred = self._preferred_social_record()
        preferred_id = str(preferred.get("id") or "") if preferred else ""
        current_label = self.social_video_var.get().strip()
        if current_label in self.social_video_labels:
            preferred_id = str(self.social_video_labels[current_label].get("id") or preferred_id)

        values: list[str] = []
        self.social_video_labels = {}
        for record in self.video_records:
            base_label = self._build_social_video_label(record)
            label = base_label
            suffix = 2
            while label in self.social_video_labels:
                label = f"{base_label} [{suffix}]"
                suffix += 1
            self.social_video_labels[label] = record
            values.append(label)

        if self.social_video_combo is not None:
            self.social_video_combo.configure(values=values)

        next_label = ""
        for label, record in self.social_video_labels.items():
            if str(record.get("id") or "") == preferred_id:
                next_label = label
                break
        if not next_label and values:
            next_label = values[0]

        selection_changed = self.social_video_var.get() != next_label
        if self.social_video_var.get() != next_label:
            self.social_video_var.set(next_label)
        if not next_label and self.social_caption_var.get():
            self.social_caption_var.set("")
        self._on_social_video_change(force=selection_changed or not self.social_caption_var.get().strip())

    def _get_selected_social_record(self) -> Optional[dict[str, Any]]:
        label = self.social_video_var.get().strip()
        if not label:
            return None
        return self.social_video_labels.get(label)

    def _on_social_video_change(self, _event: Any = None, force: bool = True) -> None:
        record = self._get_selected_social_record()
        if record and force:
            self.social_caption_var.set(self._record_caption_default(record))
        elif not record and force:
            self.social_caption_var.set("")
        self._update_social_publish_state()

    def _record_caption_default(self, record: dict[str, Any]) -> str:
        name = str(record.get("name") or os.path.basename(str(record.get("path") or "")) or "video")
        return os.path.splitext(name)[0]

    def _is_record_social_ready(self, record: dict[str, Any]) -> bool:
        if bool(record.get("social_ready")):
            return True
        return is_social_size(str(record.get("resolution") or ""))

    def _iter_social_posts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in self.video_records:
            for post in normalize_social_posts(record.get("social_posts")):
                rows.append(
                    {
                        "video_name": str(record.get("name") or "video.mp4"),
                        "platform": str(post.get("platform") or ""),
                        "target_name": str(post.get("target_name") or ""),
                        "status": str(post.get("status") or ""),
                        "published_at": str(post.get("published_at") or ""),
                    }
                )
        rows.sort(key=lambda item: item.get("published_at") or "", reverse=True)
        return rows

    def _refresh_social_posts_view(self) -> None:
        if self.social_posts_list_frame is None:
            return
        for child in self.social_posts_list_frame.winfo_children():
            child.destroy()

        posts = self._iter_social_posts()
        if not posts:
            tk.Label(
                self.social_posts_list_frame,
                textvariable=self.social_posts_empty_var,
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=self.fonts["ui_small"],
                justify="left",
                wraplength=760,
            ).pack(fill="x", padx=8, pady=8)
            return

        for post in posts[:24]:
            status = str(post.get("status") or "-")
            tone_bg = self.colors["panel_alt"] if status.lower() == "publie" else self.colors["warm_soft"]
            tone_fg = self.colors["ink"] if status.lower() == "publie" else self.colors["error_text"]
            card = tk.Frame(
                self.social_posts_list_frame,
                bg=tone_bg,
                padx=14,
                pady=12,
                highlightthickness=1,
                highlightbackground=self.colors["panel_border"],
            )
            card.pack(fill="x", padx=8, pady=(0, 8))
            top = tk.Frame(card, bg=tone_bg)
            top.pack(fill="x")
            tk.Label(top, text=str(post.get("platform") or "-"), bg=tone_bg, fg=tone_fg, font=self.fonts["ui_bold_small"]).pack(side="left")
            tk.Label(top, text=self._format_history_date(str(post.get("published_at") or "")), bg=tone_bg, fg=self.colors["muted"], font=self.fonts["ui_caption"]).pack(side="right")
            tk.Label(
                card,
                text=f"{post.get('video_name') or '-'} → {post.get('target_name') or '-'}",
                bg=tone_bg,
                fg=self.colors["ink"],
                font=self.fonts["ui_small"],
                justify="left",
                wraplength=760,
            ).pack(fill="x", pady=(6, 0))
            tk.Label(
                card,
                text=status,
                bg=tone_bg,
                fg=tone_fg,
                font=self.fonts["ui_caption"],
                justify="left",
            ).pack(anchor="w", pady=(6, 0))

    def _set_social_status(self, message: str) -> None:
        self.social_status_var.set(message)

    def _normalize_port_value(self, raw_value: str, default_value: str) -> str:
        candidate = str(raw_value or "").strip() or str(default_value)
        try:
            numeric = int(candidate)
        except ValueError:
            return str(default_value)
        if 1 <= numeric <= 65535:
            return str(numeric)
        return str(default_value)

    def _ensure_social_settings_shape(self, platform: str) -> dict[str, Any]:
        account = self.social_accounts.get(platform)
        if not isinstance(account, dict):
            account = {}
            self.social_accounts[platform] = account
        settings = account.get("settings")
        if not isinstance(settings, dict):
            settings = {}
            account["settings"] = settings
        return account

    def _load_social_app_secret_value(self, secret_name: str, field_name: str) -> str:
        try:
            payload = load_secret_json(secret_name)
        except SocialIntegrationError:
            return ""
        return str(payload.get(field_name) or "").strip()

    def _save_social_app_secret_value(self, secret_name: str, field_name: str, value: str) -> None:
        cleaned = str(value or "").strip()
        if not cleaned:
            try:
                delete_secret(secret_name)
            except SocialIntegrationError:
                pass
            return
        save_secret_json(secret_name, {field_name: cleaned})

    def _migrate_legacy_social_settings_secrets(self) -> None:
        needs_save = False
        for platform, field_name, secret_name in (
            ("tiktok", "client_secret", TIKTOK_CLIENT_SECRET_KEYRING_NAME),
            ("facebook", "app_secret", FACEBOOK_APP_SECRET_KEYRING_NAME),
        ):
            account = self._ensure_social_settings_shape(platform)
            settings = account.get("settings")
            if not isinstance(settings, dict) or field_name not in settings:
                continue
            legacy_value = str(settings.get(field_name) or "").strip()
            if legacy_value:
                try:
                    self._save_social_app_secret_value(secret_name, field_name, legacy_value)
                except SocialIntegrationError as exc:
                    self._append_log(
                        f"Migration du secret {platform} impossible: {exc}",
                        "warn",
                    )
                    continue
            settings.pop(field_name, None)
            needs_save = True
        if needs_save:
            self._save_social_accounts()

    def _social_accounts_storage_payload(self) -> dict[str, Any]:
        payload = copy.deepcopy(self.social_accounts)
        for platform, field_name in (("tiktok", "client_secret"), ("facebook", "app_secret")):
            account = payload.get(platform)
            if not isinstance(account, dict):
                continue
            settings = account.get("settings")
            if isinstance(settings, dict):
                settings.pop(field_name, None)
        return payload

    def _get_tiktok_settings(self, prefer_ui: bool = False) -> dict[str, str]:
        load_env(ENV_PATH)
        account = self.social_accounts.get("tiktok")
        settings = account.get("settings") if isinstance(account, dict) else {}
        if not isinstance(settings, dict):
            settings = {}
        client_key = self.tiktok_client_key_var.get().strip() if prefer_ui else ""
        client_secret = self.tiktok_client_secret_var.get().strip() if prefer_ui else ""
        redirect_port = self.tiktok_redirect_port_var.get().strip() if prefer_ui else ""
        stored_client_secret = self._load_social_app_secret_value(
            TIKTOK_CLIENT_SECRET_KEYRING_NAME,
            "client_secret",
        )
        return {
            "client_key": client_key or str(settings.get("client_key") or os.getenv("TIKTOK_CLIENT_KEY") or "").strip(),
            "client_secret": client_secret
            or stored_client_secret
            or str(os.getenv("TIKTOK_CLIENT_SECRET") or settings.get("client_secret") or "").strip(),
            "redirect_port": self._normalize_port_value(
                redirect_port or str(settings.get("redirect_port") or os.getenv("TIKTOK_REDIRECT_PORT") or "8765"),
                "8765",
            ),
        }

    def _get_facebook_settings(self, prefer_ui: bool = False) -> dict[str, str]:
        load_env(ENV_PATH)
        account = self.social_accounts.get("facebook")
        settings = account.get("settings") if isinstance(account, dict) else {}
        if not isinstance(settings, dict):
            settings = {}
        app_id = self.facebook_app_id_var.get().strip() if prefer_ui else ""
        app_secret = self.facebook_app_secret_var.get().strip() if prefer_ui else ""
        graph_version = self.facebook_graph_version_var.get().strip() if prefer_ui else ""
        redirect_port = self.facebook_redirect_port_var.get().strip() if prefer_ui else ""
        stored_app_secret = self._load_social_app_secret_value(
            FACEBOOK_APP_SECRET_KEYRING_NAME,
            "app_secret",
        )
        return {
            "app_id": app_id or str(settings.get("app_id") or os.getenv("FACEBOOK_APP_ID") or "").strip(),
            "app_secret": app_secret
            or stored_app_secret
            or str(os.getenv("FACEBOOK_APP_SECRET") or settings.get("app_secret") or "").strip(),
            "graph_version": graph_version
            or str(settings.get("graph_version") or os.getenv("FACEBOOK_GRAPH_VERSION") or DEFAULT_FACEBOOK_GRAPH_VERSION).strip(),
            "redirect_port": self._normalize_port_value(
                redirect_port or str(settings.get("redirect_port") or os.getenv("FACEBOOK_REDIRECT_PORT") or "8766"),
                "8766",
            ),
        }

    def _sync_social_settings_vars(self) -> None:
        tiktok = self._get_tiktok_settings(prefer_ui=False)
        facebook = self._get_facebook_settings(prefer_ui=False)
        self.tiktok_client_key_var.set(tiktok["client_key"])
        self.tiktok_client_secret_var.set(tiktok["client_secret"])
        self.tiktok_redirect_port_var.set(tiktok["redirect_port"])
        self.facebook_app_id_var.set(facebook["app_id"])
        self.facebook_app_secret_var.set(facebook["app_secret"])
        self.facebook_graph_version_var.set(facebook["graph_version"] or DEFAULT_FACEBOOK_GRAPH_VERSION)
        self.facebook_redirect_port_var.set(facebook["redirect_port"])

    def _format_tiktok_callback_url(self) -> str:
        port = self._normalize_port_value(self.tiktok_redirect_port_var.get().strip(), "8765")
        return f"http://127.0.0.1:{port}/tiktok/callback"

    def _format_facebook_callback_url(self) -> str:
        port = self._normalize_port_value(self.facebook_redirect_port_var.get().strip(), "8766")
        return f"http://127.0.0.1:{port}/facebook/callback"

    def _show_guided_config_error(self, platform: str, missing_label: str) -> None:
        if platform == "tiktok":
            message = (
                f"Renseigne d'abord {missing_label} dans la section Configuration TikTok ou clique sur Aide.\n\n"
                f"Redirect URI a enregistrer :\n{self._format_tiktok_callback_url()}"
            )
            title = "Config TikTok"
        else:
            message = (
                f"Renseigne d'abord {missing_label} dans la section Configuration Facebook ou clique sur Aide.\n\n"
                f"Redirect URI a enregistrer :\n{self._format_facebook_callback_url()}"
            )
            title = "Config Facebook"
        self._show_view("social")
        self._show_banner(f"{title}: {message}", "warn", auto_hide_ms=9000)

    def _save_tiktok_settings(self, silent: bool = False) -> bool:
        client_key = self.tiktok_client_key_var.get().strip()
        if not client_key:
            self._show_guided_config_error("tiktok", "le Client key TikTok")
            return False
        try:
            self._save_social_app_secret_value(
                TIKTOK_CLIENT_SECRET_KEYRING_NAME,
                "client_secret",
                self.tiktok_client_secret_var.get().strip(),
            )
        except SocialIntegrationError as exc:
            self._set_social_status("Configuration TikTok incomplete.")
            self._append_log(f"Impossible d'enregistrer le secret TikTok: {exc}", "error")
            self._show_banner(str(exc), "error", auto_hide_ms=9000)
            return False

        account = self._ensure_social_settings_shape("tiktok")
        account["settings"] = {
            "client_key": client_key,
            "redirect_port": self._normalize_port_value(self.tiktok_redirect_port_var.get().strip(), "8765"),
        }
        self._save_social_accounts()
        self._sync_social_settings_vars()
        self._refresh_social_state()
        if not silent:
            self._set_social_status("Configuration TikTok enregistree.")
            self._append_log("Configuration TikTok enregistree.", "system")
            self._show_toast("Configuration TikTok enregistrée.", "success")
        return True

    def _save_facebook_settings(self, silent: bool = False) -> bool:
        app_id = self.facebook_app_id_var.get().strip()
        app_secret = self.facebook_app_secret_var.get().strip()
        if not app_id:
            self._show_guided_config_error("facebook", "l'App ID Facebook")
            return False
        if not app_secret:
            self._show_guided_config_error("facebook", "l'App secret Facebook")
            return False
        try:
            self._save_social_app_secret_value(
                FACEBOOK_APP_SECRET_KEYRING_NAME,
                "app_secret",
                app_secret,
            )
        except SocialIntegrationError as exc:
            self._set_social_status("Configuration Facebook incomplete.")
            self._append_log(f"Impossible d'enregistrer le secret Facebook: {exc}", "error")
            self._show_banner(str(exc), "error", auto_hide_ms=9000)
            return False

        account = self._ensure_social_settings_shape("facebook")
        account["settings"] = {
            "app_id": app_id,
            "graph_version": self.facebook_graph_version_var.get().strip() or DEFAULT_FACEBOOK_GRAPH_VERSION,
            "redirect_port": self._normalize_port_value(self.facebook_redirect_port_var.get().strip(), "8766"),
        }
        self._save_social_accounts()
        self._sync_social_settings_vars()
        self._refresh_social_state()
        if not silent:
            self._set_social_status("Configuration Facebook enregistree.")
            self._append_log("Configuration Facebook enregistree.", "system")
            self._show_toast("Configuration Facebook enregistrée.", "success")
        return True

    def _open_url(self, url: str) -> None:
        try:
            webbrowser.open(url, new=1, autoraise=True)
        except Exception as exc:
            self._show_banner(f"Ouverture impossible: {exc}", "error")

    def _show_social_help(self) -> None:
        help_window = tk.Toplevel(self)
        help_window.title("Aide reseaux sociaux")
        help_window.geometry("780x620")
        help_window.minsize(680, 520)
        help_window.configure(bg=self.colors["bg"])

        root = tk.Frame(help_window, bg=self.colors["bg"], padx=16, pady=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = tk.Frame(root, bg=self.colors["bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Aide connexion TikTok et Facebook",
            bg=self.colors["bg"],
            fg=self.colors["ink"],
            font=self.fonts["section"],
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            header,
            text="Fermer",
            style="Ghost.TButton",
            command=help_window.destroy,
        ).grid(row=0, column=1, sticky="e")

        text_wrap = tk.Frame(
            root,
            bg=self.colors["panel_alt"],
            highlightthickness=1,
            highlightbackground=self.colors["panel_border"],
        )
        text_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        text_wrap.columnconfigure(0, weight=1)
        text_wrap.rowconfigure(0, weight=1)
        help_text = tk.Text(
            text_wrap,
            wrap="word",
            bg=self.colors["panel_alt"],
            fg=self.colors["ink"],
            insertbackground=self.colors["ink"],
            relief="flat",
            bd=0,
            padx=14,
            pady=14,
            font=self.fonts["ui_small"],
            highlightthickness=0,
        )
        help_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(
            text_wrap,
            orient="vertical",
            command=help_text.yview,
            style="App.Vertical.TScrollbar",
        )
        scroll.grid(row=0, column=1, sticky="ns")
        help_text.configure(yscrollcommand=scroll.set)
        help_text.insert(
            "1.0",
            (
                "TikTok\n"
                "1. Va sur le portail TikTok Developers puis cree une application.\n"
                "2. Dans l'app, recupere Client key et Client secret.\n"
                "3. Dans la configuration de ton app TikTok, ajoute cette Redirect URI :\n"
                f"   {self._format_tiktok_callback_url()}\n"
                "4. Renseigne Client key, Client secret et Redirect port dans l'application, puis clique sur Enregistrer.\n"
                "5. Clique sur Connecter : le navigateur s'ouvre, tu te connectes a TikTok, puis tu autorises l'application.\n"
                "6. TikTok revient automatiquement vers SoraStudio pour finaliser l'authentification.\n\n"
                "Facebook Page\n"
                "1. Va sur le portail Meta for Developers puis cree une application.\n"
                "2. Recupere App ID et App secret.\n"
                "3. Dans Facebook Login / Valid OAuth Redirect URIs, ajoute :\n"
                f"   {self._format_facebook_callback_url()}\n"
                "4. Renseigne App ID, App secret, Graph version et Redirect port dans l'application, puis clique sur Enregistrer.\n"
                "5. Clique sur Connecter : le navigateur s'ouvre, tu te connectes a Facebook puis tu selectionnes ta Page.\n\n"
                "Champs a remplir dans l'application\n"
                "- TikTok : Client key, Client secret, Redirect port\n"
                "- Facebook : App ID, App secret, Graph version, Redirect port\n\n"
                "Publication\n"
                "- Une fois connecte, coche la ou les cibles, choisis une video compatible et clique sur Publier la video.\n"
                "- Pour de meilleurs resultats, genere les videos avec la case Pour reseaux activee dans l'ecran Creer.\n"
            ),
        )
        help_text.configure(state="disabled")

        actions = tk.Frame(root, bg=self.colors["bg"])
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(
            actions,
            text="Portail TikTok",
            style="Secondary.TButton",
            command=lambda: self._open_url(TIKTOK_DEVELOPER_PORTAL_URL),
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Portail Facebook",
            style="Secondary.TButton",
            command=lambda: self._open_url(FACEBOOK_DEVELOPER_PORTAL_URL),
        ).pack(side="left", padx=(8, 0))

    def _update_social_publish_state(self) -> None:
        tiktok_connected = bool(self.social_accounts.get("tiktok", {}).get("connected"))
        facebook_connected = bool(self.social_accounts.get("facebook", {}).get("connected"))

        if self.social_tiktok_check is not None:
            self.social_tiktok_check.configure(
                state="normal" if tiktok_connected and not self.social_busy else "disabled"
            )
        if self.social_facebook_check is not None:
            self.social_facebook_check.configure(
                state="normal" if facebook_connected and not self.social_busy else "disabled"
            )
        if not tiktok_connected:
            self.social_tiktok_var.set(False)
        if not facebook_connected:
            self.social_facebook_var.set(False)

        record = self._get_selected_social_record()
        has_target = (
            tiktok_connected
            and self.social_tiktok_var.get()
            or facebook_connected
            and self.social_facebook_var.get()
        )
        can_publish = (
            not self.social_busy
            and record is not None
            and has_target
            and self.social_caption_var.get().strip()
        )
        if self.social_publish_btn is not None:
            if can_publish:
                self.social_publish_btn.state(["!disabled"])
            else:
                self.social_publish_btn.state(["disabled"])

    def _refresh_social_state(self) -> None:
        tiktok = self.social_accounts.get("tiktok", {})
        facebook = self.social_accounts.get("facebook", {})

        tiktok_connected = bool(tiktok.get("connected"))
        tiktok_label = "Non connecte"
        if tiktok_connected:
            display_name = str(
                tiktok.get("display_name") or tiktok.get("username") or tiktok.get("open_id") or "TikTok"
            )
            tiktok_label = f"Connecte: {display_name}"
        self.tiktok_account_var.set(tiktok_label)
        self.tiktok_privacy_options = [
            str(item) for item in (tiktok.get("privacy_level_options") or []) if str(item).strip()
        ]
        if self.tiktok_connect_btn is not None:
            self.tiktok_connect_btn.configure(text="Reconnecter" if tiktok_connected else "Connecter")
            if self.social_busy:
                self.tiktok_connect_btn.state(["disabled"])
            else:
                self.tiktok_connect_btn.state(["!disabled"])
        if self.tiktok_disconnect_btn is not None:
            if tiktok_connected and not self.social_busy:
                self.tiktok_disconnect_btn.state(["!disabled"])
            else:
                self.tiktok_disconnect_btn.state(["disabled"])
        if self.tiktok_privacy_combo is not None:
            self.tiktok_privacy_combo.configure(values=self.tiktok_privacy_options)
            if self.tiktok_privacy_var.get() not in self.tiktok_privacy_options:
                self.tiktok_privacy_var.set(self.tiktok_privacy_options[0] if self.tiktok_privacy_options else "")
            if tiktok_connected and self.tiktok_privacy_options and not self.social_busy:
                self.tiktok_privacy_combo.configure(state="readonly")
            else:
                self.tiktok_privacy_combo.configure(state="disabled")
        if self.tiktok_client_key_entry is not None:
            self.tiktok_client_key_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.tiktok_client_secret_entry is not None:
            self.tiktok_client_secret_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.tiktok_redirect_port_entry is not None:
            self.tiktok_redirect_port_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.tiktok_save_btn is not None:
            if self.social_busy:
                self.tiktok_save_btn.state(["disabled"])
            else:
                self.tiktok_save_btn.state(["!disabled"])

        facebook_connected = bool(facebook.get("connected"))
        facebook_label = "Non connecte"
        if facebook_connected:
            user_name = str(facebook.get("user_name") or facebook.get("selected_page_name") or "Facebook")
            facebook_label = f"Connecte: {user_name}"
        self.facebook_account_var.set(facebook_label)
        pages = facebook.get("pages") or []
        self.facebook_page_labels = {}
        values: list[str] = []
        selected_page_id = str(facebook.get("selected_page_id") or "")
        selected_label = ""
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_id = str(page.get("id") or "").strip()
            page_name = str(page.get("name") or page_id or "").strip()
            if not page_id:
                continue
            label = f"{page_name} ({page_id[-6:]})"
            self.facebook_page_labels[label] = {"id": page_id, "name": page_name}
            values.append(label)
            if page_id == selected_page_id:
                selected_label = label
        if values and not selected_label:
            selected_label = values[0]
        if self.facebook_page_var.get() != selected_label:
            self.facebook_page_var.set(selected_label)
        if self.facebook_page_combo is not None:
            self.facebook_page_combo.configure(values=values)
            if facebook_connected and values and not self.social_busy:
                self.facebook_page_combo.configure(state="readonly")
            else:
                self.facebook_page_combo.configure(state="disabled")
        if self.facebook_connect_btn is not None:
            self.facebook_connect_btn.configure(text="Reconnecter" if facebook_connected else "Connecter")
            if self.social_busy:
                self.facebook_connect_btn.state(["disabled"])
            else:
                self.facebook_connect_btn.state(["!disabled"])
        if self.facebook_disconnect_btn is not None:
            if facebook_connected and not self.social_busy:
                self.facebook_disconnect_btn.state(["!disabled"])
            else:
                self.facebook_disconnect_btn.state(["disabled"])
        if self.facebook_app_id_entry is not None:
            self.facebook_app_id_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.facebook_app_secret_entry is not None:
            self.facebook_app_secret_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.facebook_graph_version_entry is not None:
            self.facebook_graph_version_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.facebook_redirect_port_entry is not None:
            self.facebook_redirect_port_entry.configure(state="disabled" if self.social_busy else "normal")
        if self.facebook_save_btn is not None:
            if self.social_busy:
                self.facebook_save_btn.state(["disabled"])
            else:
                self.facebook_save_btn.state(["!disabled"])
        if self.social_help_btn is not None:
            if self.social_busy:
                self.social_help_btn.state(["disabled"])
            else:
                self.social_help_btn.state(["!disabled"])
        if self.social_tiktok_portal_btn is not None:
            if self.social_busy:
                self.social_tiktok_portal_btn.state(["disabled"])
            else:
                self.social_tiktok_portal_btn.state(["!disabled"])
        if self.social_facebook_portal_btn is not None:
            if self.social_busy:
                self.social_facebook_portal_btn.state(["disabled"])
            else:
                self.social_facebook_portal_btn.state(["!disabled"])

        if self.social_video_combo is not None:
            if self.social_busy or not self.social_video_labels:
                self.social_video_combo.configure(state="disabled")
            else:
                self.social_video_combo.configure(state="readonly")
        if self.social_caption_entry is not None:
            self.social_caption_entry.configure(state="disabled" if self.social_busy else "normal")

        self._update_social_publish_state()

    def _load_social_accounts(self) -> None:
        self.social_accounts = {"tiktok": {}, "facebook": {}}
        if not os.path.exists(self.social_accounts_file):
            self._sync_social_settings_vars()
            return

        try:
            with open(self.social_accounts_file, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception as exc:
            self._append_log(f"Impossible de lire les comptes reseaux: {exc}", "warn")
            self._sync_social_settings_vars()
            return

        if not isinstance(payload, dict):
            self._append_log("Comptes reseaux invalides: format inattendu.", "warn")
            self._sync_social_settings_vars()
            return

        for platform in ("tiktok", "facebook"):
            raw = payload.get(platform)
            if isinstance(raw, dict):
                self.social_accounts[platform] = raw
            self._ensure_social_settings_shape(platform)
        self._migrate_legacy_social_settings_secrets()

        tiktok_account = self.social_accounts.get("tiktok", {})
        if isinstance(tiktok_account, dict):
            tiktok_account["privacy_level_options"] = [
                str(item)
                for item in (tiktok_account.get("privacy_level_options") or [])
                if str(item).strip()
            ]

        facebook_account = self.social_accounts.get("facebook", {})
        if isinstance(facebook_account, dict):
            facebook_account["pages"] = [
                item
                for item in (facebook_account.get("pages") or [])
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]

        try:
            facebook_tokens = load_secret_json(FacebookAPI.secret_name)
            self.facebook_page_tokens = {
                str(key): str(value)
                for key, value in (facebook_tokens.get("page_tokens") or {}).items()
                if str(key).strip() and str(value).strip()
            }
        except SocialIntegrationError as exc:
            self.facebook_page_tokens = {}
            self._append_log(f"Coffre Facebook indisponible: {exc}", "warn")
        self._sync_social_settings_vars()

    def _save_social_accounts(self) -> None:
        try:
            self._ensure_social_settings_shape("tiktok")
            self._ensure_social_settings_shape("facebook")
            with open(self.social_accounts_file, "w", encoding="utf-8") as handle:
                json.dump(self._social_accounts_storage_payload(), handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._append_log(f"Impossible d'enregistrer les comptes reseaux: {exc}", "error")

    def _on_facebook_page_change(self, _event: Any = None) -> None:
        label = self.facebook_page_var.get().strip()
        selected_page = self.facebook_page_labels.get(label)
        if not selected_page:
            return
        facebook = self.social_accounts.setdefault("facebook", {})
        facebook["selected_page_id"] = str(selected_page.get("id") or "")
        facebook["selected_page_name"] = str(selected_page.get("name") or "")
        self._save_social_accounts()
        self._refresh_social_state()

    def _selected_facebook_page(self) -> Optional[dict[str, Any]]:
        label = self.facebook_page_var.get().strip()
        if label and label in self.facebook_page_labels:
            return self.facebook_page_labels[label]
        facebook = self.social_accounts.get("facebook", {})
        selected_page_id = str(facebook.get("selected_page_id") or "")
        for page in facebook.get("pages") or []:
            if not isinstance(page, dict):
                continue
            if str(page.get("id") or "") == selected_page_id:
                return page
        return None

    def _build_tiktok_api(self) -> TikTokAPI:
        settings = self._get_tiktok_settings(prefer_ui=True)
        return TikTokAPI(
            client_key=settings["client_key"],
            client_secret=settings["client_secret"],
            redirect_port=int(settings["redirect_port"]),
        )

    def _build_facebook_api(self) -> FacebookAPI:
        settings = self._get_facebook_settings(prefer_ui=True)
        return FacebookAPI(
            app_id=settings["app_id"],
            app_secret=settings["app_secret"],
            graph_version=settings["graph_version"],
            redirect_port=int(settings["redirect_port"]),
        )

    def _connect_tiktok(self) -> None:
        dependency_issue = dependencies_error()
        if dependency_issue:
            self._show_banner(dependency_issue, "error")
            return
        if not self._save_tiktok_settings(silent=True):
            return
        self._start_social_task("Connexion TikTok en cours...", self._worker_connect_tiktok)

    def _connect_facebook(self) -> None:
        dependency_issue = dependencies_error()
        if dependency_issue:
            self._show_banner(dependency_issue, "error")
            return
        if not self._save_facebook_settings(silent=True):
            return
        self._start_social_task("Connexion Facebook en cours...", self._worker_connect_facebook)

    def _disconnect_tiktok(self) -> None:
        if not self.social_accounts.get("tiktok", {}).get("connected"):
            return
        if not messagebox.askyesno("TikTok", "Deconnecter le compte TikTok ?"):
            return
        try:
            delete_secret(TikTokAPI.secret_name)
        except SocialIntegrationError as exc:
            messagebox.showerror("Erreur coffre", str(exc))
            return
        settings = dict((self.social_accounts.get("tiktok", {}) or {}).get("settings") or {})
        self.social_accounts["tiktok"] = {"settings": settings}
        self.social_tiktok_var.set(False)
        self._save_social_accounts()
        self._set_social_status("Compte TikTok deconnecte.")
        self._append_log("Compte TikTok deconnecte.", "warn")
        self._refresh_social_state()

    def _disconnect_facebook(self) -> None:
        if not self.social_accounts.get("facebook", {}).get("connected"):
            return
        if not messagebox.askyesno("Facebook", "Deconnecter la Page Facebook ?"):
            return
        try:
            delete_secret(FacebookAPI.secret_name)
        except SocialIntegrationError as exc:
            messagebox.showerror("Erreur coffre", str(exc))
            return
        settings = dict((self.social_accounts.get("facebook", {}) or {}).get("settings") or {})
        self.social_accounts["facebook"] = {"settings": settings}
        self.facebook_page_tokens = {}
        self.social_facebook_var.set(False)
        self._save_social_accounts()
        self._set_social_status("Compte Facebook deconnecte.")
        self._append_log("Compte Facebook deconnecte.", "warn")
        self._refresh_social_state()

    def _start_social_task(self, message: str, worker: Any, *args: Any) -> None:
        if self.social_busy:
            return
        self.social_busy = True
        self._set_social_status(message)
        self._refresh_social_state()
        self.social_worker = threading.Thread(target=worker, args=args, daemon=True)
        self.social_worker.start()
        self.after(120, self._drain_social_events)

    def _worker_connect_tiktok(self) -> None:
        try:
            self.social_events.put(("log", "Ouverture du navigateur pour TikTok.", "system"))
            api = self._build_tiktok_api()
            token_payload = api.connect()
            creator_info = api.query_creator_info(str(token_payload.get("access_token") or ""))
            metadata = {
                "connected": True,
                "display_name": str(creator_info.get("display_name") or creator_info.get("username") or "TikTok"),
                "username": str(creator_info.get("username") or ""),
                "open_id": str(
                    creator_info.get("open_id") or token_payload.get("open_id") or ""
                ),
                "privacy_level_options": creator_info.get("privacy_level_options") or ["SELF_ONLY"],
                "connected_at": str(token_payload.get("connected_at") or ""),
            }
            self.social_events.put(("tiktok_connected", metadata, token_payload))
        except Exception as exc:
            self.social_events.put(("error", "tiktok", str(exc)))

    def _worker_connect_facebook(self) -> None:
        try:
            self.social_events.put(("log", "Ouverture du navigateur pour Facebook.", "system"))
            api = self._build_facebook_api()
            result = api.connect()
            pages = result.get("pages") or []
            first_page = pages[0] if pages else {}
            metadata = {
                "connected": True,
                "user_name": str((result.get("profile") or {}).get("name") or "Facebook"),
                "user_id": str((result.get("profile") or {}).get("id") or ""),
                "pages": pages,
                "selected_page_id": str(first_page.get("id") or ""),
                "selected_page_name": str(first_page.get("name") or ""),
                "connected_at": str((result.get("token_payload") or {}).get("connected_at") or ""),
            }
            self.social_events.put(("facebook_connected", metadata, result.get("token_payload") or {}))
        except Exception as exc:
            self.social_events.put(("error", "facebook", str(exc)))

    def _publish_selected_social(self) -> None:
        dependency_issue = dependencies_error()
        if dependency_issue:
            self._show_banner(dependency_issue, "error")
            return

        record = self._get_selected_social_record()
        if not record:
            self._show_banner("Sélectionne une vidéo à publier.", "warn")
            return

        path = str(record.get("path") or "")
        if not os.path.exists(path):
            self._show_banner("Cette vidéo n'existe plus sur le disque.", "warn")
            return
        if not self._is_record_social_ready(record):
            self._show_banner(
                "Cette vidéo n'est pas marquée pour les réseaux. Régénère-la avec l'option 'Pour réseaux'.",
                "warn",
            )
            return

        caption = self.social_caption_var.get().strip()
        if not caption:
            self._show_banner("Renseigne une légende avant publication.", "warn")
            return

        targets: list[str] = []
        if self.social_tiktok_var.get():
            if not self.social_accounts.get("tiktok", {}).get("connected"):
                self._show_banner("Connecte d'abord le compte TikTok.", "warn")
                return
            if not self.tiktok_privacy_var.get().strip():
                self._show_banner("Sélectionne une confidentialité TikTok.", "warn")
                return
            targets.append("tiktok")
        if self.social_facebook_var.get():
            if not self.social_accounts.get("facebook", {}).get("connected"):
                self._show_banner("Connecte d'abord la Page Facebook.", "warn")
                return
            if not self._selected_facebook_page():
                self._show_banner("Sélectionne une Page Facebook active.", "warn")
                return
            targets.append("facebook")

        if not targets:
            self._show_banner("Coche au moins une plateforme.", "warn")
            return

        self._start_social_task(
            "Publication en cours...",
            self._worker_publish_social,
            str(record.get("id") or ""),
            path,
            caption,
            tuple(targets),
            self.tiktok_privacy_var.get().strip(),
        )

    def _worker_publish_social(
        self,
        record_id: str,
        path: str,
        caption: str,
        targets: tuple[str, ...],
        tiktok_privacy: str,
    ) -> None:
        entries: list[dict[str, Any]] = []
        token_updates: dict[str, dict[str, Any]] = {}

        if "tiktok" in targets:
            try:
                self.social_events.put(("log", "Publication TikTok en cours...", "info"))
                api = self._build_tiktok_api()
                token_payload = load_secret_json(TikTokAPI.secret_name)
                fresh_tokens = api.ensure_access_token(token_payload)
                creator_info = api.query_creator_info(str(fresh_tokens.get("access_token") or ""))
                options = [
                    str(item)
                    for item in (creator_info.get("privacy_level_options") or [])
                    if str(item).strip()
                ]
                privacy_level = tiktok_privacy if tiktok_privacy in options else (options[0] if options else tiktok_privacy)
                publish_result = api.publish_video(fresh_tokens, path, caption, privacy_level)
                token_updates["tiktok"] = publish_result.get("token_payload") or fresh_tokens
                entries.append(
                    {
                        "platform": "TikTok",
                        "target_id": str(
                            self.social_accounts.get("tiktok", {}).get("open_id") or creator_info.get("open_id") or ""
                        ),
                        "target_name": str(
                            self.social_accounts.get("tiktok", {}).get("display_name")
                            or creator_info.get("display_name")
                            or "TikTok"
                        ),
                        "caption": caption,
                        "published_at": datetime.now().isoformat(timespec="seconds"),
                        "status": "Publie",
                        "remote_id": str(publish_result.get("remote_id") or publish_result.get("publish_id") or ""),
                        "publish_id": str(publish_result.get("publish_id") or publish_result.get("remote_id") or ""),
                        "error": "",
                    }
                )
            except Exception as exc:
                entries.append(
                    {
                        "platform": "TikTok",
                        "target_id": "",
                        "target_name": str(
                            self.social_accounts.get("tiktok", {}).get("display_name") or "TikTok"
                        ),
                        "caption": caption,
                        "published_at": datetime.now().isoformat(timespec="seconds"),
                        "status": "Echec",
                        "remote_id": "",
                        "publish_id": "",
                        "error": str(exc),
                    }
                )

        if "facebook" in targets:
            try:
                self.social_events.put(("log", "Publication Facebook en cours...", "info"))
                api = self._build_facebook_api()
                token_payload = load_secret_json(FacebookAPI.secret_name)
                selected_page = self._selected_facebook_page() or {}
                page_id = str(selected_page.get("id") or "")
                page_name = str(selected_page.get("name") or "Facebook Page")
                page_tokens = token_payload.get("page_tokens") or {}
                page_token = str(page_tokens.get(page_id) or "")
                publish_result = api.publish_reel(page_id, page_token, caption, path)
                entries.append(
                    {
                        "platform": "Facebook",
                        "target_id": page_id,
                        "target_name": page_name,
                        "caption": caption,
                        "published_at": datetime.now().isoformat(timespec="seconds"),
                        "status": "Publie",
                        "remote_id": str(publish_result.get("remote_id") or ""),
                        "publish_id": "",
                        "error": "",
                    }
                )
            except Exception as exc:
                entries.append(
                    {
                        "platform": "Facebook",
                        "target_id": str(self.social_accounts.get("facebook", {}).get("selected_page_id") or ""),
                        "target_name": str(
                            self.social_accounts.get("facebook", {}).get("selected_page_name") or "Facebook Page"
                        ),
                        "caption": caption,
                        "published_at": datetime.now().isoformat(timespec="seconds"),
                        "status": "Echec",
                        "remote_id": "",
                        "publish_id": "",
                        "error": str(exc),
                    }
                )

        self.social_events.put(("publish_result", record_id, entries, token_updates))

    def _drain_social_events(self) -> None:
        try:
            while True:
                event = self.social_events.get_nowait()
                event_type = event[0]

                if event_type == "log":
                    self._append_log(str(event[1]), str(event[2] if len(event) > 2 else "info"))
                    continue

                if event_type == "tiktok_connected":
                    metadata = dict(event[1])
                    tokens = dict(event[2])
                    try:
                        save_secret_json(TikTokAPI.secret_name, tokens)
                    except SocialIntegrationError as exc:
                        self.social_busy = False
                        self._set_social_status(str(exc))
                        self._refresh_social_state()
                        messagebox.showerror("Coffre systeme", str(exc))
                        continue
                    settings = dict((self.social_accounts.get("tiktok", {}) or {}).get("settings") or {})
                    self.social_accounts["tiktok"] = {"settings": settings, **metadata}
                    self.social_tiktok_var.set(True)
                    self._save_social_accounts()
                    self.social_busy = False
                    self._set_social_status("Compte TikTok connecte.")
                    self._append_log("Compte TikTok connecte.", "success")
                    self._refresh_social_state()
                    self._show_toast("Compte TikTok connecté.", "success")
                    continue

                if event_type == "facebook_connected":
                    metadata = dict(event[1])
                    tokens = dict(event[2])
                    try:
                        save_secret_json(FacebookAPI.secret_name, tokens)
                    except SocialIntegrationError as exc:
                        self.social_busy = False
                        self._set_social_status(str(exc))
                        self._refresh_social_state()
                        messagebox.showerror("Coffre systeme", str(exc))
                        continue
                    self.facebook_page_tokens = {
                        str(key): str(value)
                        for key, value in (tokens.get("page_tokens") or {}).items()
                        if str(key).strip() and str(value).strip()
                    }
                    settings = dict((self.social_accounts.get("facebook", {}) or {}).get("settings") or {})
                    self.social_accounts["facebook"] = {"settings": settings, **metadata}
                    self.social_facebook_var.set(True)
                    self._save_social_accounts()
                    self.social_busy = False
                    self._set_social_status("Compte Facebook connecte.")
                    self._append_log("Compte Facebook connecte.", "success")
                    self._refresh_social_state()
                    self._show_toast("Page Facebook connectée.", "success")
                    continue

                if event_type == "publish_result":
                    record_id = str(event[1] or "")
                    entries = [item for item in event[2] if isinstance(item, dict)]
                    token_updates = dict(event[3])
                    if token_updates.get("tiktok"):
                        try:
                            save_secret_json(TikTokAPI.secret_name, dict(token_updates["tiktok"]))
                        except SocialIntegrationError as exc:
                            self._append_log(f"Impossible de rafraichir le token TikTok: {exc}", "warn")

                    record = self.video_records_by_id.get(record_id)
                    if record is None:
                        for item in self.video_records:
                            if str(item.get("id") or "") == record_id:
                                record = item
                                break
                    if record is not None:
                        record.setdefault("social_posts", [])
                        record["social_posts"] = normalize_social_posts(record.get("social_posts")) + normalize_social_posts(entries)
                        self._save_video_history()
                        self._refresh_history_view()
                        if self._get_selected_history_record() and str(self._get_selected_history_record().get("id") or "") == record_id:
                            self._on_history_select()

                    success_count = sum(1 for item in entries if str(item.get("status") or "").lower() == "publie")
                    error_entries = [item for item in entries if str(item.get("status") or "").lower() != "publie"]
                    self.social_busy = False
                    self._refresh_social_state()
                    if success_count and not error_entries:
                        self._set_social_status("Publication terminee.")
                        self._append_log("Publication reseaux terminee.", "success")
                        self._show_toast("Publication terminée avec succès.", "success")
                    elif success_count and error_entries:
                        self._set_social_status("Publication partielle.")
                        self._append_log("Publication partielle sur les reseaux.", "warn")
                        self._show_banner(
                            "\n".join(str(item.get("error") or item.get("platform") or "Erreur") for item in error_entries),
                            "warn",
                            auto_hide_ms=9000,
                        )
                    else:
                        self._set_social_status("Echec de publication.")
                        self._append_log("Publication reseaux en echec.", "error")
                        self._show_banner(
                            "\n".join(str(item.get("error") or item.get("platform") or "Erreur") for item in error_entries)
                            or "La publication a échoué.",
                            "error",
                            auto_hide_ms=9000,
                        )
                    continue

                if event_type == "error":
                    self.social_busy = False
                    context = str(event[1] or "reseaux")
                    message = str(event[2] or "Erreur inconnue.")
                    if "Configuration manquante: TIKTOK_CLIENT_KEY" in message:
                        self._set_social_status("Configuration TikTok incomplete.")
                        self._append_log("Configuration TikTok incomplete.", "warn")
                        self._refresh_social_state()
                        self._show_guided_config_error("tiktok", "le Client key TikTok")
                        continue
                    if "Configuration manquante: FACEBOOK_APP_ID" in message:
                        self._set_social_status("Configuration Facebook incomplete.")
                        self._append_log("Configuration Facebook incomplete.", "warn")
                        self._refresh_social_state()
                        self._show_guided_config_error("facebook", "l'App ID Facebook")
                        continue
                    if "Configuration manquante: FACEBOOK_APP_SECRET" in message:
                        self._set_social_status("Configuration Facebook incomplete.")
                        self._append_log("Configuration Facebook incomplete.", "warn")
                        self._refresh_social_state()
                        self._show_guided_config_error("facebook", "l'App secret Facebook")
                        continue
                    self._set_social_status(f"Erreur {context}: {message}")
                    self._append_log(f"Erreur {context}: {message}", "error")
                    self._refresh_social_state()
                    self._show_banner(message, "error", auto_hide_ms=9000)
                    continue
        except queue.Empty:
            pass

        if self.social_busy:
            self.after(150, self._drain_social_events)

    def _format_history_date(self, iso_string: str) -> str:
        if not iso_string:
            return "-"
        try:
            dt = datetime.fromisoformat(iso_string)
            return dt.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return iso_string

    def _format_file_size(self, value: Any) -> str:
        try:
            size = float(value)
        except (TypeError, ValueError):
            return "-"
        if size < 1024:
            return f"{int(size)} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def _load_video_history(self) -> None:
        self.video_records = []
        if not os.path.exists(self.history_file):
            return

        try:
            # utf-8-sig accepte les JSON avec ou sans BOM.
            with open(self.history_file, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception as exc:
            self._append_log(f"Impossible de lire l'historique: {exc}", "warn")
            return

        if not isinstance(payload, list):
            self._append_log("Historique invalide: format inattendu.", "warn")
            return

        seen_ids: set[str] = set()
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            normalized = normalize_history_record(raw, APP_DIR)
            if normalized is None:
                continue
            record_id = str(raw.get("id") or uuid.uuid4().hex)
            while record_id in seen_ids:
                record_id = uuid.uuid4().hex
            seen_ids.add(record_id)
            self.video_records.append({"id": record_id, **normalized})

        if self.video_records:
            self._append_log(
                f"{len(self.video_records)} video(s) chargee(s) dans Mes videos.",
                "system",
            )

    def _save_video_history(self) -> None:
        try:
            with open(self.history_file, "w", encoding="utf-8") as handle:
                json.dump(self.video_records, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._append_log(f"Impossible d'enregistrer l'historique: {exc}", "error")

    def _filtered_video_records(self) -> list[dict[str, Any]]:
        query = self.history_filter_var.get().strip().lower()
        if not query:
            return list(self.video_records)
        rows: list[dict[str, Any]] = []
        for record in self.video_records:
            haystacks = [
                str(record.get("name") or ""),
                str(record.get("prompt") or ""),
                str(record.get("prompt_preview") or ""),
                str(record.get("model") or ""),
                str(record.get("resolution") or ""),
            ]
            if any(query in value.lower() for value in haystacks):
                rows.append(record)
        return rows

    def _record_prompt_preview(self, record: dict[str, Any]) -> str:
        return build_prompt_preview(
            str(record.get("prompt") or record.get("prompt_preview") or ""),
            fallback=str(record.get("name") or "Rendu"),
        )

    def _bind_click_recursive(self, widget: tk.Widget, callback: Any) -> None:
        widget.bind("<Button-1>", lambda _event: callback(), add="+")
        for child in widget.winfo_children():
            self._bind_click_recursive(child, callback)

    def _render_recent_history_sidebar(self) -> None:
        if self.recent_history_list is None:
            return
        for child in self.recent_history_list.winfo_children():
            child.destroy()

        if not self.video_records:
            tk.Label(
                self.recent_history_list,
                textvariable=self.recent_history_empty_var,
                bg=self.colors["sidebar"],
                fg=self.colors["muted_soft"],
                font=self.fonts["ui_small"],
                justify="left",
                wraplength=230,
            ).pack(fill="x", padx=6, pady=6)
            return

        for record in self.video_records[:18]:
            record_id = str(record.get("id") or "")
            active = record_id == self.selected_record_id
            bg = self.colors["sidebar_item_active"] if active else self.colors["sidebar"]
            card = tk.Frame(
                self.recent_history_list,
                bg=bg,
                padx=10,
                pady=8,
                highlightthickness=1 if active else 0,
                highlightbackground=self.colors["panel_border"],
            )
            card.pack(fill="x", padx=4, pady=(0, 6))
            title = tk.Label(
                card,
                text=self._record_prompt_preview(record),
                bg=bg,
                fg=self.colors["ink"] if active else self.colors["muted"],
                font=self.fonts["ui_small"],
                justify="left",
                wraplength=220,
                anchor="w",
            )
            title.pack(fill="x")
            meta = tk.Label(
                card,
                text=self._format_history_date(str(record.get("created_at") or "")),
                bg=bg,
                fg=self.colors["muted_soft"],
                font=self.fonts["ui_caption"],
                anchor="w",
            )
            meta.pack(fill="x", pady=(4, 0))
            self._bind_click_recursive(card, lambda rid=record_id: self._open_record_session(rid))

    def _render_library_cards(self) -> None:
        if self.library_cards_frame is None:
            return
        for child in self.library_cards_frame.winfo_children():
            child.destroy()

        filtered = self._filtered_video_records()
        if not filtered:
            tk.Label(
                self.library_cards_frame,
                textvariable=self.library_empty_var,
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=self.fonts["ui_small"],
                wraplength=520,
                justify="left",
            ).pack(fill="x", padx=12, pady=12)
            return

        for record in filtered:
            record_id = str(record.get("id") or "")
            active = record_id == self.selected_record_id
            bg = self.colors["panel_alt_2"] if active else self.colors["panel_alt"]
            card = tk.Frame(
                self.library_cards_frame,
                bg=bg,
                padx=14,
                pady=12,
                highlightthickness=1,
                highlightbackground=self.colors["accent"] if active else self.colors["panel_border"],
            )
            card.pack(fill="x", padx=8, pady=(0, 10))
            tk.Label(
                card,
                text=self._record_prompt_preview(record),
                bg=bg,
                fg=self.colors["ink"],
                font=self.fonts["ui_bold"],
                justify="left",
                anchor="w",
                wraplength=520,
            ).pack(fill="x")
            tk.Label(
                card,
                text=(
                    f"{self._format_history_date(str(record.get('created_at') or ''))}  •  "
                    f"{record.get('model') or '-'}  •  {record.get('resolution') or '-'}  •  "
                    f"{self._format_file_size(record.get('bytes'))}"
                ),
                bg=bg,
                fg=self.colors["muted"],
                font=self.fonts["ui_caption"],
                justify="left",
                anchor="w",
            ).pack(fill="x", pady=(6, 0))
            self._bind_click_recursive(card, lambda rid=record_id: self._select_history_record(rid))

    def _refresh_history_view(self) -> None:
        self.video_records_by_id = {}

        changed = False
        for record in self.video_records:
            path = str(record.get("path") or "")
            exists = os.path.exists(path)
            if exists:
                try:
                    disk_size = os.path.getsize(path)
                    if record.get("bytes") != disk_size:
                        record["bytes"] = disk_size
                        changed = True
                except OSError:
                    pass

            rid = str(record["id"])
            self.video_records_by_id[rid] = record

        if changed:
            self._save_video_history()

        count = len(self.video_records)
        self.history_count_var.set(f"{count} vidéo{'s' if count != 1 else ''}")
        if self.selected_record_id and self.selected_record_id not in self.video_records_by_id:
            self.selected_record_id = ""
        if not self.selected_record_id and self.video_records:
            self.selected_record_id = str(self.video_records[0].get("id") or "")

        self._render_recent_history_sidebar()
        self._render_library_cards()
        self._on_history_select()
        self._refresh_social_video_options()
        self._refresh_social_posts_view()

    def _set_history_actions_state(self, has_selection: bool, file_exists: bool) -> None:
        if self.history_open_btn is not None:
            if has_selection and file_exists:
                self.history_open_btn.state(["!disabled"])
            else:
                self.history_open_btn.state(["disabled"])

        if self.history_export_btn is not None:
            if has_selection and file_exists:
                self.history_export_btn.state(["!disabled"])
            else:
                self.history_export_btn.state(["disabled"])

        if self.history_reuse_btn is not None:
            if has_selection:
                self.history_reuse_btn.state(["!disabled"])
            else:
                self.history_reuse_btn.state(["disabled"])

        if self.history_delete_btn is not None:
            if has_selection:
                self.history_delete_btn.state(["!disabled"])
            else:
                self.history_delete_btn.state(["disabled"])

    def _get_selected_history_record(self) -> Optional[dict[str, Any]]:
        if not self.selected_record_id:
            return None
        return self.video_records_by_id.get(self.selected_record_id)

    def _select_history_record(self, record_id: str) -> None:
        self.selected_record_id = record_id
        self._render_recent_history_sidebar()
        self._render_library_cards()
        self._on_history_select()

    def _open_record_session(self, record_id: str) -> None:
        self._select_history_record(record_id)
        record = self._get_selected_history_record()
        if record is not None:
            self._load_record_into_generate(record)
            self._show_view("generate")

    def _on_history_select(self, _event: Any = None) -> None:
        record = self._get_selected_history_record()
        if not record:
            self.history_title_var.set("Aucune vidéo sélectionnée")
            self.history_meta_var.set("Sélectionne un rendu pour voir ses détails.")
            self.history_prompt_var.set("Aucun prompt enregistré.")
            self.history_details_var.set(
                "Sélectionne une vidéo pour afficher son résumé, son état et son chemin complet."
            )
            self._set_history_actions_state(has_selection=False, file_exists=False)
            return

        path = str(record.get("path") or "")
        exists = os.path.exists(path)
        status_label = "Disponible" if exists else "Fichier introuvable"
        duration = record.get("duration_seconds")
        duration_label = f"{duration}s" if isinstance(duration, int) else "-"
        self.history_title_var.set(str(record.get("name") or os.path.basename(path) or "video.mp4"))
        self.history_meta_var.set(
            f"{self._format_history_date(str(record.get('created_at') or ''))} • "
            f"{record.get('model') or '-'} • {record.get('resolution') or '-'}"
        )
        self.history_prompt_var.set(
            str(record.get("prompt") or "Aucun prompt enregistré pour ce rendu.")
        )
        details = [
            f"Nom : {record.get('name') or os.path.basename(path) or 'video.mp4'}",
            f"Modele : {record.get('model') or '-'}",
            f"Duree : {duration_label}",
            f"Format : {record.get('resolution') or '-'}",
            f"Reseaux : {'Pret' if self._is_record_social_ready(record) else 'Classique'}",
            f"Publications : {len(record.get('social_posts') or [])}",
            f"Taille : {self._format_file_size(record.get('bytes'))}",
            f"Date : {self._format_history_date(str(record.get('created_at') or ''))}",
            f"Etat : {status_label}",
            f"Chemin : {path or '-'}",
        ]
        self.history_details_var.set("\n".join(details))
        self._set_history_actions_state(has_selection=True, file_exists=exists)

    def _history_refresh(self) -> None:
        self._load_video_history()
        self._refresh_history_view()
        self._append_log("Bibliothèque rafraîchie.", "system")
        self._show_toast("Bibliothèque rafraîchie.", "info")

    def _open_in_system(self, path: str) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return
        subprocess.Popen(["xdg-open", path])

    def _history_open_selected(self) -> None:
        record = self._get_selected_history_record()
        if not record:
            return
        path = str(record.get("path") or "")
        if not os.path.exists(path):
            self._show_banner("Cette vidéo n'existe plus sur le disque.", "warn")
            self._append_log(f"Video introuvable: {path}", "warn")
            self._on_history_select()
            return
        try:
            self._open_in_system(path)
            self._append_log(f"Ouverture video: {path}", "info")
        except Exception as exc:
            self._show_banner(f"Erreur ouverture: {exc}", "error")
            self._append_log(f"Erreur ouverture: {exc}", "error")

    def _history_export_selected(self) -> None:
        record = self._get_selected_history_record()
        if not record:
            return
        source = str(record.get("path") or "")
        if not os.path.exists(source):
            self._show_banner("Cette vidéo n'existe plus sur le disque.", "warn")
            self._append_log(f"Export impossible, fichier introuvable: {source}", "warn")
            self._on_history_select()
            return

        destination = filedialog.asksaveasfilename(
            title="Exporter la video",
            defaultextension=".mp4",
            filetypes=[("Video MP4", "*.mp4"), ("Tous les fichiers", "*.*")],
            initialfile=os.path.basename(source),
        )
        if not destination:
            return

        if os.path.abspath(destination) == os.path.abspath(source):
            self._show_banner("Le fichier source et destination sont identiques.", "warn")
            return

        try:
            shutil.copy2(source, destination)
            self._append_log(f"Video exportee vers: {destination}", "success")
            self._show_toast("Vidéo exportée.", "success")
        except Exception as exc:
            self._show_banner(f"Erreur export: {exc}", "error")
            self._append_log(f"Erreur export: {exc}", "error")

    def _history_reuse_selected(self) -> None:
        record = self._get_selected_history_record()
        if record is None:
            return
        self._load_record_into_generate(record)
        self._show_view("generate")

    def _history_delete_selected(self) -> None:
        record = self._get_selected_history_record()
        if not record:
            return

        path = str(record.get("path") or "")
        name = str(record.get("name") or os.path.basename(path) or "video")
        confirm = messagebox.askyesno(
            "Supprimer la video",
            f"Supprimer '{name}' de la liste et du disque ?",
        )
        if not confirm:
            return

        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as exc:
                self._show_banner(f"Erreur suppression: {exc}", "error")
                self._append_log(f"Erreur suppression du fichier: {exc}", "error")
                return

        self.video_records = [
            item for item in self.video_records if str(item.get("id")) != str(record.get("id"))
        ]
        if str(record.get("id") or "") == self.selected_record_id:
            self.selected_record_id = ""
        self._save_video_history()
        self._refresh_history_view()
        self._append_log(f"Video supprimee: {name}", "warn")
        self._show_toast("Vidéo supprimée.", "warn")

    def _create_video_record(
        self,
        output_path: str,
        seconds: int,
        resolution: str,
        model: str,
        video_id: str,
        prompt: str = "",
        social_ready: bool = False,
    ) -> dict[str, Any]:
        bytes_value: Optional[int] = None
        if os.path.exists(output_path):
            try:
                bytes_value = os.path.getsize(output_path)
            except OSError:
                bytes_value = None

        return {
            "id": uuid.uuid4().hex,
            "name": os.path.basename(output_path),
            "path": os.path.abspath(output_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": int(seconds),
            "resolution": resolution,
            "model": model,
            "bytes": bytes_value,
            "video_id": video_id,
            "prompt": prompt,
            "prompt_preview": build_prompt_preview(prompt, fallback=os.path.basename(output_path)),
            "social_ready": bool(social_ready or is_social_size(resolution)),
            "social_posts": [],
        }

    def _remember_video_record(self, record: dict[str, Any]) -> None:
        path = str(record.get("path") or "")
        if path:
            # Evite les doublons si on regenere vers le meme fichier.
            self.video_records = [
                item
                for item in self.video_records
                if os.path.abspath(str(item.get("path") or "")) != os.path.abspath(path)
            ]
        self.video_records.insert(0, record)
        self.selected_record_id = str(record.get("id") or "")
        self._save_video_history()
        self._refresh_history_view()
        self._load_record_into_generate(record, push_feed=False)

    def _load_record_into_generate(
        self,
        record: dict[str, Any],
        push_feed: bool = True,
    ) -> None:
        prompt = str(record.get("prompt") or "").strip()
        if self.prompt_text is not None:
            self.prompt_text.configure(state="normal")
            self.prompt_text.delete("1.0", "end")
            self.prompt_text.insert(
                "1.0",
                prompt or self._record_prompt_preview(record),
            )
        self.model_var.set(str(record.get("model") or DEFAULT_MODEL))
        duration = record.get("duration_seconds")
        self.seconds_var.set(str(duration) if isinstance(duration, int) and str(duration) in SECONDS_OPTIONS else DEFAULT_SECONDS)
        resolution = str(record.get("resolution") or DEFAULT_SIZE)
        self.size_var.set(resolution if resolution in SIZE_OPTIONS else DEFAULT_SIZE)
        self.video_name_var.set(os.path.splitext(str(record.get("name") or DEFAULT_OUTPUT_NAME))[0])
        self.output_var.set(str(record.get("path") or DEFAULT_OUTPUT_PATH))
        if push_feed:
            self.activity_feed = []
            if prompt:
                self._push_activity("prompt", prompt, title="Prompt réouvert")
            self._push_activity(
                "result",
                (
                    f"{record.get('name') or 'Rendu'}\n"
                    f"{record.get('resolution') or '-'} • {self._format_history_date(str(record.get('created_at') or ''))}"
                ),
                title="Rendu précédent",
            )

    def _set_status(self, text: str, tone: str) -> None:
        self.status_var.set(text)

        tones = {
            "info": (self.colors["info"], self.colors["info_text"]),
            "running": (self.colors["accent_soft"], self.colors["accent"]),
            "success": (self.colors["success"], self.colors["success_text"]),
            "error": (self.colors["error"], self.colors["error_text"]),
        }
        badge_bg, badge_fg = tones.get(tone, tones["info"])
        badge_texts = {
            "info": "PRET",
            "running": "EN COURS",
            "success": "TERMINE",
            "error": "ERREUR",
        }

        if self.status_chip is not None:
            self.status_chip.configure(
                text=badge_texts.get(tone, tone.upper()),
                bg=badge_bg,
                fg=badge_fg,
            )
        if tone == "running":
            self.status_detail_var.set("Le rendu est en cours. Les mises à jour arrivent automatiquement.")
        elif tone == "success":
            self.status_detail_var.set("Le fichier est prêt et disponible dans la bibliothèque.")
        elif tone == "error":
            self.status_detail_var.set("Le rendu a échoué. Consulte le fil d'activité pour le détail.")
        else:
            self.status_detail_var.set(
                "Prêt à générer. Entrée lance le rendu, Shift+Entrée ajoute une nouvelle ligne."
            )

    def _pick_output(self) -> None:
        current = self.output_var.get().strip() or DEFAULT_OUTPUT_PATH
        initial_dir = os.path.dirname(current) if os.path.dirname(current) else os.getcwd()

        path = filedialog.asksaveasfilename(
            title="Enregistrer la video",
            defaultextension=".mp4",
            filetypes=[("Video MP4", "*.mp4"), ("Tous les fichiers", "*.*")],
            initialdir=initial_dir,
            initialfile=os.path.basename(current),
        )
        if path:
            self.output_var.set(path)

    def _clear_log(self) -> None:
        if self.log_text is not None:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
        self.activity_feed = []
        self._render_activity_feed()

    def _append_log(self, message: str, level: str = "info") -> None:
        tag = level if level in {"info", "success", "warn", "error", "system"} else "info"
        title_map = {
            "system": "Système",
            "info": "Mise à jour",
            "success": "Succès",
            "warn": "Attention",
            "error": "Erreur",
        }
        if self.log_text is not None:
            stamp = time.strftime("%H:%M:%S")
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{stamp}] {message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self._push_activity(tag, message, title=title_map.get(tag, "Journal"))

    def _set_controls_state(self, enabled: bool) -> None:
        for widget in self.controls:
            if isinstance(widget, tk.Text):
                widget.configure(state="normal" if enabled else "disabled")
                continue

            if isinstance(widget, tk.Checkbutton):
                widget.configure(state="normal" if enabled else "disabled")
                continue

            if isinstance(widget, ttk.Combobox):
                if enabled:
                    if widget is self.size_combo and self.social_mode_var.get():
                        widget.configure(state="disabled")
                    else:
                        widget.configure(state="readonly")
                else:
                    widget.configure(state="disabled")
                continue

            try:
                if enabled:
                    widget.state(["!disabled"])
                else:
                    widget.state(["disabled"])
            except Exception:
                pass

    def _set_progress(self, progress: Any) -> None:
        value: Optional[float] = None
        if progress is not None:
            try:
                value = float(progress)
            except (TypeError, ValueError):
                value = None

        if value is None:
            if not self.indeterminate:
                if self.progress is not None:
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(10)
                self.indeterminate = True
            self.progress_text_var.set("...")
            return

        if self.indeterminate:
            if self.progress is not None:
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.indeterminate = False

        if value <= 1.0:
            value *= 100.0
        value = max(0.0, min(100.0, value))
        self.progress_var.set(value)
        self.progress_text_var.set(f"{int(round(value))}%")

    def _reset_form(self) -> None:
        if self.running:
            return

        self.model_var.set(DEFAULT_MODEL)
        self.seconds_var.set(DEFAULT_SECONDS)
        self.last_manual_size = DEFAULT_SIZE
        if self.social_mode_var.get():
            self.social_mode_var.set(False)
        self.size_var.set(DEFAULT_SIZE)
        self.video_name_var.set(DEFAULT_OUTPUT_NAME)
        self.output_var.set(DEFAULT_OUTPUT_PATH)
        self._sync_output_from_name()

        if self.prompt_text is not None:
            self.prompt_text.configure(state="normal")
            self.prompt_text.delete("1.0", "end")
            self.prompt_text.insert("1.0", DEFAULT_PROMPT)

        if self.progress is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.indeterminate = False
        self.progress_var.set(0)
        self.progress_text_var.set("0%")

        self.last_status_seen = None
        self._set_status("Ready", "info")
        self._append_log("Formulaire reinitialise.", "system")

    def _start_generation(self) -> None:
        if self.running:
            return

        if self.prompt_text is None:
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        model = self.model_var.get().strip() or DEFAULT_MODEL
        video_name = self.video_name_var.get().strip()

        if not prompt:
            self._show_banner("Le prompt ne peut pas être vide.", "error")
            return
        filename = self._build_output_filename(video_name)
        if not filename:
            self._show_banner("Renseigne un nom de vidéo.", "error")
            return
        output_dir = self._default_output_dir()
        output_path = os.path.abspath(os.path.join(output_dir, filename))
        self.output_var.set(output_path)

        seconds_raw = self.seconds_var.get().strip()
        if seconds_raw not in SECONDS_OPTIONS:
            supported_seconds = ", ".join(SECONDS_OPTIONS)
            self.seconds_var.set(DEFAULT_SECONDS)
            self._show_banner(
                (
                    f'Durée "{seconds_raw}" non supportée. '
                    f"Durees supportees: {supported_seconds} secondes."
                ),
                "error",
            )
            self._append_log(
                f'Duree invalide recue: "{seconds_raw}". Reset vers {DEFAULT_SECONDS}s.',
                "warn",
            )
            return
        seconds = int(seconds_raw)

        poll_seconds = float(DEFAULT_POLL_SECONDS)

        size = self.size_var.get().strip() or DEFAULT_SIZE
        if size not in SIZE_OPTIONS:
            supported = ", ".join(SIZE_OPTIONS)
            self.size_var.set(DEFAULT_SIZE)
            self._show_banner(
                f'Format "{size}" non supporté. Formats supportes: {supported}',
                "error",
            )
            self._append_log(
                f'Format invalide recu: "{size}". Reset vers {DEFAULT_SIZE}.',
                "warn",
            )
            return
        output_path = os.path.abspath(output_path)
        self.output_var.set(output_path)
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as exc:
                self._show_banner(f"Impossible de créer le dossier de sortie: {exc}", "error")
                return
        load_env(ENV_PATH)

        if not os.getenv("OPENAI_API_KEY"):
            self._show_banner(
                "Ajoute OPENAI_API_KEY dans les variables d'environnement ou .env.",
                "error",
            )
            return

        self.running = True
        self.last_status_seen = None

        if self.progress is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.indeterminate = False
        self.progress_var.set(0)
        self.progress_text_var.set("0%")

        self._set_controls_state(False)
        self._set_status("Job envoye au moteur video...", "running")
        self.activity_feed = []
        self._push_activity("prompt", prompt, title="Prompt envoyé")
        self._append_log("Demarrage de la generation video.", "system")

        args = (model, prompt, seconds, size, output_path, poll_seconds)
        self.worker = threading.Thread(target=self._worker_generate, args=args, daemon=True)
        self.worker.start()
        self.after(120, self._drain_events)

    def _worker_generate(
        self,
        model: str,
        prompt: str,
        seconds: int,
        size: str,
        output_path: str,
        poll_seconds: float,
    ) -> None:
        try:
            client = OpenAI()
            self.events.put(
                (
                    "log",
                    (
                        "Requete create() envoyee "
                        f"avec model={model}, size={size}, seconds={seconds}."
                    ),
                    "system",
                )
            )

            job = client.videos.create(
                model=model,
                prompt=prompt,
                seconds=str(seconds),
                size=size,
            )
            video_id = job.id
            self.events.put(("log", f"Job cree: {video_id}", "system"))

            while True:
                video = client.videos.retrieve(video_id)
                status = str(getattr(video, "status", "unknown"))
                progress = getattr(video, "progress", None)
                self.events.put(("status", status, progress))

                if status in {"completed", "failed"}:
                    break
                time.sleep(poll_seconds)

            if status != "completed":
                err = getattr(video, "error", None)
                raise RuntimeError(f"Echec generation: {err}")

            self.events.put(("log", "Telechargement de la video...", "info"))
            response = client.videos.download_content(video_id=video_id)
            content = response.read()

            with open(output_path, "wb") as handle:
                handle.write(content)

            record = self._create_video_record(
                output_path=output_path,
                seconds=seconds,
                resolution=size,
                model=model,
                video_id=video_id,
                prompt=prompt,
                social_ready=self.social_mode_var.get(),
            )
            self.events.put(("done", record))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                event_type = event[0]

                if event_type == "log":
                    level = event[2] if len(event) > 2 else "info"
                    self._append_log(event[1], level)
                    continue

                if event_type == "status":
                    status = str(event[1])
                    progress = event[2]

                    pretty_status = status.replace("_", " ")
                    tone = "running"
                    if status == "completed":
                        tone = "success"
                    elif status == "failed":
                        tone = "error"

                    self._set_status(f"API status: {pretty_status}", tone)
                    self._set_progress(progress)

                    if status != self.last_status_seen:
                        self._append_log(f"Changement de statut: {pretty_status}", "info")
                        self.last_status_seen = status
                    continue

                if event_type == "done":
                    if isinstance(event[1], dict):
                        record = event[1]
                    else:
                        fallback_path = str(event[1])
                        record = self._create_video_record(
                            output_path=fallback_path,
                            seconds=0,
                            resolution=self.size_var.get().strip() or "-",
                            model=self.model_var.get().strip() or "-",
                            video_id="",
                            prompt=self.prompt_text.get("1.0", "end").strip() if self.prompt_text is not None else "",
                            social_ready=self.social_mode_var.get(),
                        )
                    output = str(record.get("path") or "")
                    self.running = False
                    self.last_status_seen = None

                    if self.indeterminate:
                        if self.progress is not None:
                            self.progress.stop()
                            self.progress.configure(mode="determinate")
                        self.indeterminate = False

                    self.progress_var.set(100)
                    self.progress_text_var.set("100%")
                    self._set_status("Generation terminee", "success")
                    self._remember_video_record(record)
                    self._push_activity("result", f"Vidéo prête : {output}", title="Rendu terminé")
                    self._append_log(f"Video ecrite: {output}", "success")
                    self._set_controls_state(True)
                    self._show_toast("Vidéo générée avec succès.", "success")
                    continue

                if event_type == "error":
                    self.running = False
                    self.last_status_seen = None

                    if self.indeterminate:
                        if self.progress is not None:
                            self.progress.stop()
                            self.progress.configure(mode="determinate")
                        self.indeterminate = False

                    self._set_status("Erreur pendant la generation", "error")
                    self._append_log(f"Erreur: {event[1]}", "error")
                    self._set_controls_state(True)
                    self._show_banner(f"Erreur de génération: {event[1]}", "error")
        except queue.Empty:
            pass

        if self.running:
            self.after(150, self._drain_events)


def main() -> None:
    app = SoraVideoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
