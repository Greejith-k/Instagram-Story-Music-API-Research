"""
Beat Music Player (Enhanced)
-----------------------------
A polished desktop GUI application (Tkinter) that lets a user search for
songs and displays results (cover art + title + artist) in a scrollable
list, with a full-featured playback bar: queue, shuffle, repeat,
next/previous, seek, volume, and keyboard shortcuts.

NOTE: The audio-source lookup (get_instagram_audio_url) is left exactly
as provided — this update focuses on the GUI and the local playback
experience (queue, shuffle/repeat, transport controls, progress/volume,
visual polish) rather than the network/fetch layer.

Dependencies:
    pip install requests pillow pygame

Run:
    python music_player.py
"""

import base64
import io
import json
import random
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import os

import requests
from PIL import Image, ImageTk, ImageDraw, ImageOps, ImageFilter

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not installed. Audio playback will be disabled.")
    print("Install with: pip install pygame")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
API_URL = "https://api.inssist.com/api/v1/mscr/tracks"
INSTAGRAM_API_URL = "https://www.instagram.com/api/v1/clips/music/"
REQUEST_TIMEOUT = 15  # seconds

BG_COLOR = "#0b0d13"
BG_GRADIENT_TOP = "#141826"
CARD_COLOR = "#171a23"
CARD_HOVER = "#20242f"
CARD_SELECTED = "#262c3d"
ACCENT_COLOR = "#7c5cff"
ACCENT_HOVER = "#9376ff"
ACCENT_SOFT = "#2a2340"
TEXT_PRIMARY = "#f2f2f7"
TEXT_SECONDARY = "#9a9ab0"
TEXT_MUTED = "#5f6178"
BORDER_COLOR = "#262a38"
SUCCESS_COLOR = "#4cd97b"
DANGER_COLOR = "#e74c3c"

THUMB_SIZE = 56
NOW_PLAYING_ART_SIZE = 64

# Instagram session cookie - you need to provide your own
INSTAGRAM_SESSION_ID = ""
INSTAGRAM_FB_DTSG = ""


# --------------------------------------------------------------------------- #
# Image helpers
# --------------------------------------------------------------------------- #
def make_rounded_thumbnail(pil_image: Image.Image, size: int = THUMB_SIZE, radius: int = 14) -> ImageTk.PhotoImage:
    img = ImageOps.fit(pil_image.convert("RGBA"), (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    rounded = Image.new("RGBA", (size, size))
    rounded.paste(img, (0, 0), mask=mask)
    return ImageTk.PhotoImage(rounded)


def make_placeholder_thumbnail(size: int = THUMB_SIZE) -> ImageTk.PhotoImage:
    img = Image.new("RGBA", (size, size), CARD_HOVER)
    draw = ImageDraw.Draw(img)
    draw.ellipse((size * 0.30, size * 0.55, size * 0.30 + size * 0.22, size * 0.55 + size * 0.22),
                 fill=TEXT_SECONDARY)
    draw.rectangle((size * 0.50, size * 0.18, size * 0.55, size * 0.65), fill=TEXT_SECONDARY)
    return make_rounded_thumbnail(img, size)


def make_glow_photo(pil_image: Image.Image, size: int = NOW_PLAYING_ART_SIZE) -> ImageTk.PhotoImage:
    """Slightly blurred/darkened backdrop art for the now-playing bar."""
    img = ImageOps.fit(pil_image.convert("RGBA"), (size, size), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(0))
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=16, fill=255)
    rounded = Image.new("RGBA", (size, size))
    rounded.paste(img, (0, 0), mask=mask)
    return ImageTk.PhotoImage(rounded)


# --------------------------------------------------------------------------- #
# Main Application
# --------------------------------------------------------------------------- #
class BeatMusicPlayer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Beat Music Player")
        self.geometry("560x760")
        self.minsize(440, 560)
        self.configure(bg=BG_COLOR)

        self._placeholder_thumb = None
        self._now_playing_art = None
        self._thumb_cache = []
        self._search_seq = 0

        # Playback / queue state
        self.is_playing = False
        self.current_track = None
        self.audio_available = False
        self._audio_loaded = False
        self._track_length = 0.0
        self.current_volume = 0.5
        self._prev_volume = 0.5
        self._muted = False
        self._progress_update_id = None
        self._suppress_seek = False
        self._search_after_id = None
        self._loading_dots = 0

        self.shuffle_on = False
        self.repeat_mode = "off"  # off -> all -> one -> off
        self.play_queue = []       # order of indices into track_items currently queued
        self.queue_pos = -1

        self._init_audio()

        self.track_items = []
        self.selected_index = -1

        self._build_style()
        self._build_layout()

        self.after(50, self._init_placeholder)
        self._bind_keyboard_shortcuts()

    # ------------------------------------------------------------ Audio init
    def _init_audio(self):
        if not PYGAME_AVAILABLE:
            self.audio_available = False
            return
        try:
            audio_drivers = ['pulseaudio', 'alsa', 'oss', 'sdl']
            os.environ['SDL_AUDIODRIVER'] = 'pulseaudio'
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
                self.audio_available = True
            except pygame.error:
                for driver in audio_drivers:
                    try:
                        os.environ['SDL_AUDIODRIVER'] = driver
                        pygame.mixer.init()
                        self.audio_available = True
                        break
                    except pygame.error:
                        continue
        except Exception as e:
            print(f"Unexpected error initializing audio: {e}")
            self.audio_available = False

    # ------------------------------------------------------------ Style
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG_COLOR)
        style.configure("Card.TFrame", background=CARD_COLOR)

        style.configure(
            "Search.TEntry",
            fieldbackground=CARD_COLOR, background=CARD_COLOR, foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR, lightcolor=BORDER_COLOR, darkcolor=BORDER_COLOR,
            insertcolor=TEXT_PRIMARY, padding=10,
        )

        def _button_style(name, bg, hover, fg="#ffffff", pad=(16, 10)):
            style.configure(name, background=bg, foreground=fg, borderwidth=0,
                             focusthickness=0, padding=pad, font=("Segoe UI", 10, "bold"))
            style.map(name, background=[("active", hover), ("disabled", "#3a3d4a")],
                      foreground=[("disabled", TEXT_MUTED)])

        _button_style("Accent.TButton", ACCENT_COLOR, ACCENT_HOVER)
        _button_style("Play.TButton", ACCENT_COLOR, ACCENT_HOVER, pad=(20, 10))
        _button_style("Stop.TButton", DANGER_COLOR, "#c0392b", pad=(20, 10))
        _button_style("Transport.TButton", CARD_COLOR, CARD_HOVER, fg=TEXT_PRIMARY, pad=(10, 8))
        _button_style("TransportOn.TButton", ACCENT_SOFT, ACCENT_SOFT, fg=ACCENT_HOVER, pad=(10, 8))

        style.configure("Horizontal.TScale", background=CARD_COLOR, troughcolor=CARD_HOVER,
                         bordercolor=CARD_COLOR, lightcolor=ACCENT_COLOR, darkcolor=ACCENT_COLOR)
        style.configure("Vertical.TScrollbar", background=CARD_COLOR, troughcolor=BG_COLOR,
                         bordercolor=BG_COLOR, arrowcolor=TEXT_SECONDARY)

    # ------------------------------------------------------------ Layout
    def _build_layout(self):
        # ---- Header -----------------------------------------------------
        header = tk.Frame(self, bg=BG_COLOR)
        header.pack(fill="x", padx=24, pady=(22, 10))

        title_row = tk.Frame(header, bg=BG_COLOR)
        title_row.pack(fill="x")
        tk.Label(title_row, text="🎧  Beat Music Player", bg=BG_COLOR, fg=TEXT_PRIMARY,
                 font=("Segoe UI", 19, "bold")).pack(side="left")

        self.audio_badge = tk.Label(
            title_row, text="● Audio Ready" if self.audio_available else "● Audio Unavailable",
            bg=BG_COLOR, fg=SUCCESS_COLOR if self.audio_available else DANGER_COLOR,
            font=("Segoe UI", 9, "bold"),
        )
        self.audio_badge.pack(side="right", pady=(6, 0))

        tk.Label(header, text="Search millions of tracks", bg=BG_COLOR, fg=TEXT_SECONDARY,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        # ---- Search bar ---------------------------------------------------
        search_bar = tk.Frame(self, bg=BG_COLOR)
        search_bar.pack(fill="x", padx=24, pady=(14, 6))

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_bar, textvariable=self.search_var,
                                       style="Search.TEntry", font=("Segoe UI", 11))
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.search_entry.bind("<Return>", lambda _e: self.start_search())
        self.search_entry.bind("<KeyRelease>", self._on_search_typing)
        self.search_entry.focus_set()

        self.clear_btn = tk.Button(
            search_bar, text="✕", bg=CARD_COLOR, fg=TEXT_SECONDARY, bd=0,
            font=("Segoe UI", 10), cursor="hand2", command=self._clear_search,
            activebackground=CARD_HOVER, activeforeground=TEXT_PRIMARY,
        )
        self.clear_btn.pack(side="left", padx=(6, 0), ipady=4, ipadx=6)

        self.search_btn = ttk.Button(search_bar, text="Search", style="Accent.TButton",
                                      command=self.start_search)
        self.search_btn.pack(side="left", padx=(10, 0))

        # ---- Status line ---------------------------------------------------
        self.status_var = tk.StringVar(value="Type a song, artist, or album and hit Search.")
        self.status_label = tk.Label(self, textvariable=self.status_var, bg=BG_COLOR,
                                      fg=TEXT_SECONDARY, font=("Segoe UI", 9), anchor="w", justify="left")
        self.status_label.pack(fill="x", padx=26, pady=(0, 8))

        # ---- Now Playing bar ----------------------------------------------
        self._build_now_playing_bar()

        # ---- Scrollable results area ---------------------------------------
        results_container = tk.Frame(self, bg=BG_COLOR)
        results_container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.canvas = tk.Canvas(results_container, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(results_container, orient="vertical",
                                   command=self.canvas.yview, style="Vertical.TScrollbar")
        self.results_frame = tk.Frame(self.canvas, bg=BG_COLOR)

        self.results_frame.bind("<Configure>",
                                 lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.results_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._bind_mousewheel(self.canvas)

        self._empty_state_label = tk.Label(
            self.results_frame, text="🔍  Search for a song to get started",
            bg=BG_COLOR, fg=TEXT_MUTED, font=("Segoe UI", 11),
        )

    def _build_now_playing_bar(self):
        now_playing_frame = tk.Frame(self, bg=CARD_COLOR)
        now_playing_frame.pack(fill="x", padx=16, pady=(0, 8))

        top_row = tk.Frame(now_playing_frame, bg=CARD_COLOR)
        top_row.pack(fill="x", padx=12, pady=(10, 2))

        self.now_playing_art_label = tk.Label(top_row, bg=CARD_COLOR, bd=0)
        self.now_playing_art_label.pack(side="left")

        text_col = tk.Frame(top_row, bg=CARD_COLOR)
        text_col.pack(side="left", fill="x", expand=True, padx=(10, 0))

        self.now_playing_title = tk.Label(
            text_col, text="Audio Unavailable" if not self.audio_available else "No track selected",
            bg=CARD_COLOR, fg=TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), anchor="w",
        )
        self.now_playing_title.pack(fill="x", anchor="w")

        self.now_playing_artist = tk.Label(
            text_col, text="Select a song below to start listening" if self.audio_available else "Install pygame to enable playback",
            bg=CARD_COLOR, fg=TEXT_SECONDARY, font=("Segoe UI", 9), anchor="w",
        )
        self.now_playing_artist.pack(fill="x", anchor="w", pady=(2, 0))

        # Transport controls
        controls_row = tk.Frame(now_playing_frame, bg=CARD_COLOR)
        controls_row.pack(pady=(4, 2))

        state = "disabled" if not self.audio_available else "normal"

        self.shuffle_btn = ttk.Button(controls_row, text="🔀", style="Transport.TButton",
                                       command=self.toggle_shuffle, state=state)
        self.shuffle_btn.grid(row=0, column=0, padx=3)

        self.prev_btn = ttk.Button(controls_row, text="⏮", style="Transport.TButton",
                                    command=self.play_previous, state=state)
        self.prev_btn.grid(row=0, column=1, padx=3)

        self.play_btn = ttk.Button(controls_row, text="▶ Play", style="Play.TButton",
                                    command=self.toggle_playback, state=state)
        self.play_btn.grid(row=0, column=2, padx=6)

        self.next_btn = ttk.Button(controls_row, text="⏭", style="Transport.TButton",
                                    command=self.play_next, state=state)
        self.next_btn.grid(row=0, column=3, padx=3)

        self.repeat_btn = ttk.Button(controls_row, text="🔁", style="Transport.TButton",
                                      command=self.cycle_repeat, state=state)
        self.repeat_btn.grid(row=0, column=4, padx=3)

        self.stop_btn = ttk.Button(controls_row, text="⏹", style="Stop.TButton",
                                    command=self.stop_playback, state=state)
        self.stop_btn.grid(row=0, column=5, padx=(10, 0))

        # Progress row
        progress_row = tk.Frame(now_playing_frame, bg=CARD_COLOR)
        progress_row.pack(fill="x", padx=12, pady=(2, 6))

        self.time_current_label = tk.Label(progress_row, text="0:00", bg=CARD_COLOR,
                                            fg=TEXT_SECONDARY, font=("Segoe UI", 8), width=5)
        self.time_current_label.pack(side="left")

        self.progress_slider = ttk.Scale(progress_row, from_=0, to=100, value=0,
                                          orient="horizontal", command=self._on_seek)
        self.progress_slider.pack(side="left", fill="x", expand=True, padx=6)
        self.progress_slider.state(["disabled"] if not self.audio_available else [])

        self.time_total_label = tk.Label(progress_row, text="0:00", bg=CARD_COLOR,
                                          fg=TEXT_SECONDARY, font=("Segoe UI", 8), width=5)
        self.time_total_label.pack(side="left")

        # Volume row
        volume_row = tk.Frame(now_playing_frame, bg=CARD_COLOR)
        volume_row.pack(fill="x", padx=12, pady=(0, 10))

        self.mute_btn = tk.Button(
            volume_row, text="🔊", bg=CARD_COLOR, fg=TEXT_SECONDARY, bd=0,
            font=("Segoe UI", 10), cursor="hand2", command=self.toggle_mute,
            activebackground=CARD_COLOR, activeforeground=TEXT_PRIMARY,
        )
        self.mute_btn.pack(side="left")

        self.volume_slider = ttk.Scale(volume_row, from_=0, to=1, value=self.current_volume,
                                        orient="horizontal", command=self._on_volume_change)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=6)
        self.volume_slider.state(["disabled"] if not self.audio_available else [])

        self.queue_label = tk.Label(volume_row, text="", bg=CARD_COLOR, fg=TEXT_MUTED,
                                     font=("Segoe UI", 8))
        self.queue_label.pack(side="right")

    # ------------------------------------------------------------ Canvas helpers
    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _bind_mousewheel(self, widget):
        widget.bind_all("<MouseWheel>", self._on_mousewheel)
        widget.bind_all("<Button-4>", self._on_mousewheel)
        widget.bind_all("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _init_placeholder(self):
        self._placeholder_thumb = make_placeholder_thumbnail()
        self._now_playing_art = make_glow_photo(Image.new("RGBA", (10, 10), CARD_HOVER))
        self.now_playing_art_label.configure(image=self._now_playing_art)

    def _bind_keyboard_shortcuts(self):
        self.bind("<space>", self._on_space)
        self.bind("<Escape>", lambda e: self.stop_playback())
        self.bind("<Control-a>", lambda e: self.start_search())
        self.bind("<Control-q>", lambda e: self.on_closing())
        self.bind("<Control-Right>", lambda e: self.play_next())
        self.bind("<Control-Left>", lambda e: self.play_previous())
        self.bind("<Control-m>", lambda e: self.toggle_mute())
        self.bind("<Control-s>", lambda e: self.toggle_shuffle())
        self.bind("<Control-r>", lambda e: self.cycle_repeat())

    def _on_space(self, event):
        # Don't hijack spacebar while typing in the search box
        if self.focus_get() is self.search_entry:
            return
        self.toggle_playback()

    # ------------------------------------------------------------ Search
    def _on_search_typing(self, _event=None):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        query = self.search_var.get().strip()
        if not query:
            return
        self._search_after_id = self.after(500, self.start_search)

    def _clear_search(self):
        self.search_var.set("")
        self._clear_results()
        self.status_var.set("Type a song, artist, or album and hit Search.")
        self._show_empty_state()
        self.search_entry.focus_set()

    def start_search(self):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
            self._search_after_id = None

        query = self.search_var.get().strip()
        if not query:
            self.status_var.set("Please type something to search for.")
            return

        self._search_seq += 1
        this_seq = self._search_seq

        self._clear_results()
        self._loading_dots = 0
        self._animate_loading(query, this_seq)
        self.search_btn.state(["disabled"])

        thread = threading.Thread(target=self._fetch_tracks, args=(query, this_seq), daemon=True)
        thread.start()

    def _animate_loading(self, query, seq):
        if seq != self._search_seq:
            return
        dots = "." * (self._loading_dots % 4)
        self.status_var.set(f'Searching for "{query}"{dots}')
        self._loading_dots += 1
        if self.search_btn.instate(["disabled"]):
            self.after(350, lambda: self._animate_loading(query, seq))

    def _fetch_tracks(self, query, seq):
        try:
            response = requests.get(API_URL, params={"q": query}, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            tracks = data.get("tracks", [])
        except requests.exceptions.RequestException as exc:
            self.after(0, self._on_search_error, seq, f"Network error: {exc}")
            return
        except ValueError:
            self.after(0, self._on_search_error, seq, "Received an invalid response from the server.")
            return
        self.after(0, self._on_search_success, seq, tracks, query)

    def _on_search_error(self, seq, message):
        if seq != self._search_seq:
            return
        self.search_btn.state(["!disabled"])
        self.status_var.set(message)
        self._show_empty_state()
        messagebox.showerror("Search failed", message)

    def _on_search_success(self, seq, tracks, query):
        if seq != self._search_seq:
            return
        self.search_btn.state(["!disabled"])

        if not tracks:
            self.status_var.set(f'No results found for "{query}".')
            self._show_empty_state("😕  No results — try a different search")
            return

        self.status_var.set(f'Found {len(tracks)} result(s) for "{query}".')
        self._populate_results(tracks)
        self.track_items = tracks
        self.play_queue = list(range(len(tracks)))
        self.queue_pos = -1
        self._update_queue_label()

    # ------------------------------------------------------------ Results
    def _clear_results(self):
        for child in self.results_frame.winfo_children():
            child.destroy()
        self._thumb_cache.clear()
        self.track_items = []
        self.selected_index = -1

    def _show_empty_state(self, text="🔍  Search for a song to get started"):
        for child in self.results_frame.winfo_children():
            child.destroy()
        self._empty_state_label = tk.Label(
            self.results_frame, text=text, bg=BG_COLOR, fg=TEXT_MUTED, font=("Segoe UI", 11),
        )
        self._empty_state_label.pack(pady=60)

    def _populate_results(self, tracks):
        for idx, track in enumerate(tracks):
            self._add_result_row(track, idx)

    def _add_result_row(self, track: dict, index: int):
        name = track.get("name") or "Unknown title"
        artist = track.get("artist") or "Unknown artist"
        cover_data_uri = track.get("cover")

        row = tk.Frame(self.results_frame, bg=CARD_COLOR)
        row.pack(fill="x", padx=8, pady=5)

        inner = tk.Frame(row, bg=CARD_COLOR)
        inner.pack(fill="x", padx=12, pady=10)

        thumb_photo = self._decode_cover(cover_data_uri)
        self._thumb_cache.append(thumb_photo)

        thumb_label = tk.Label(inner, image=thumb_photo, bg=CARD_COLOR, bd=0)
        thumb_label.pack(side="left")

        text_frame = tk.Frame(inner, bg=CARD_COLOR)
        text_frame.pack(side="left", fill="x", expand=True, padx=(12, 0))

        title_label = tk.Label(text_frame, text=name, bg=CARD_COLOR, fg=TEXT_PRIMARY,
                                font=("Segoe UI", 11, "bold"), anchor="w", justify="left", wraplength=300)
        title_label.pack(fill="x", anchor="w")

        artist_label = tk.Label(text_frame, text=artist, bg=CARD_COLOR, fg=TEXT_SECONDARY,
                                 font=("Segoe UI", 9), anchor="w", justify="left", wraplength=300)
        artist_label.pack(fill="x", anchor="w", pady=(2, 0))

        play_btn = None
        if self.audio_available:
            play_btn = tk.Button(
                inner, text="▶", bg=CARD_COLOR, fg=ACCENT_COLOR, bd=0, font=("Segoe UI", 13),
                cursor="hand2", activebackground=CARD_HOVER, activeforeground=ACCENT_HOVER,
            )
            play_btn.pack(side="right", padx=(0, 5))

        def on_click(e, i=index):
            self.select_track(i)

        def on_play_click(e, i=index):
            if self.audio_available:
                self.select_track(i)
                self.play_selected_track()

        widgets_for_hover = [row, inner, text_frame, title_label, artist_label, thumb_label]
        if play_btn is not None:
            widgets_for_hover.append(play_btn)

        def on_enter(_e, i=index):
            if i != self.selected_index:
                self._set_row_bg(row, CARD_HOVER)

        def on_leave(_e, i=index):
            if i != self.selected_index:
                self._set_row_bg(row, CARD_COLOR)

        for widget in widgets_for_hover:
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Double-Button-1>", on_play_click)

        if play_btn is not None:
            play_btn.bind("<Button-1>", on_play_click)

    def _set_row_bg(self, row, color):
        row.configure(bg=color)
        for child in row.winfo_children():
            child.configure(bg=color)
            for sub in child.winfo_children():
                try:
                    sub.configure(bg=color)
                except tk.TclError:
                    pass

    def _decode_cover(self, data_uri: str) -> ImageTk.PhotoImage:
        if not data_uri:
            return self._placeholder_thumb or make_placeholder_thumbnail()
        try:
            header, b64data = data_uri.split(",", 1) if "," in data_uri else ("", data_uri)
            raw = base64.b64decode(b64data)
            image = Image.open(io.BytesIO(raw))
            return make_rounded_thumbnail(image)
        except Exception:
            return self._placeholder_thumb or make_placeholder_thumbnail()

    # ------------------------------------------------------------ Track selection
    def select_track(self, index):
        if 0 <= index < len(self.track_items):
            self.selected_index = index
            track = self.track_items[index]
            self.status_var.set(f"Selected: {track.get('name')} by {track.get('artist')}")
            self._highlight_track(index)
            if self.audio_available:
                self.play_btn.state(["!disabled"])
                self.stop_btn.state(["!disabled"])
            # keep queue position in sync with manual selection
            if index in self.play_queue:
                self.queue_pos = self.play_queue.index(index)

    def _highlight_track(self, index):
        for i, child in enumerate(self.results_frame.winfo_children()):
            self._set_row_bg(child, CARD_SELECTED if i == index else CARD_COLOR)

    def _update_queue_label(self):
        if not self.play_queue:
            self.queue_label.config(text="")
            return
        pos = self.queue_pos + 1 if self.queue_pos >= 0 else 0
        self.queue_label.config(text=f"{pos}/{len(self.play_queue)}")

    # ------------------------------------------------------------ Shuffle / repeat
    def toggle_shuffle(self):
        if not self.audio_available:
            return
        self.shuffle_on = not self.shuffle_on
        self.shuffle_btn.configure(style="TransportOn.TButton" if self.shuffle_on else "Transport.TButton")
        self._rebuild_queue(keep_current=True)
        self.status_var.set("Shuffle on" if self.shuffle_on else "Shuffle off")

    def _rebuild_queue(self, keep_current=True):
        n = len(self.track_items)
        if n == 0:
            self.play_queue = []
            self.queue_pos = -1
            return
        current = self.selected_index if keep_current and self.selected_index >= 0 else None
        indices = list(range(n))
        if self.shuffle_on:
            random.shuffle(indices)
            if current is not None and current in indices:
                indices.remove(current)
                indices.insert(0, current)
        self.play_queue = indices
        self.queue_pos = self.play_queue.index(current) if current is not None and current in self.play_queue else -1
        self._update_queue_label()

    def cycle_repeat(self):
        if not self.audio_available:
            return
        order = ["off", "all", "one"]
        self.repeat_mode = order[(order.index(self.repeat_mode) + 1) % len(order)]
        icons = {"off": "🔁", "all": "🔁", "one": "🔂"}
        self.repeat_btn.configure(
            text=icons[self.repeat_mode],
            style="TransportOn.TButton" if self.repeat_mode != "off" else "Transport.TButton",
        )
        labels = {"off": "Repeat off", "all": "Repeat all", "one": "Repeat one"}
        self.status_var.set(labels[self.repeat_mode])

    def play_next(self):
        if not self.audio_available or not self.play_queue:
            return
        if self.queue_pos + 1 < len(self.play_queue):
            self.queue_pos += 1
        elif self.repeat_mode == "all":
            self.queue_pos = 0
        else:
            self.status_var.set("End of queue")
            return
        self._update_queue_label()
        index = self.play_queue[self.queue_pos]
        self.select_track(index)
        self.play_selected_track()

    def play_previous(self):
        if not self.audio_available or not self.play_queue:
            return
        if self.queue_pos > 0:
            self.queue_pos -= 1
        elif self.repeat_mode == "all":
            self.queue_pos = len(self.play_queue) - 1
        else:
            self.status_var.set("Start of queue")
            return
        self._update_queue_label()
        index = self.play_queue[self.queue_pos]
        self.select_track(index)
        self.play_selected_track()

    # ------------------------------------------------------------ Instagram API (unchanged)
    def get_instagram_audio_url(self, track_id):
        """Make API call to Instagram to get audio URL"""
        try:
            headers = {
                "Host": "www.instagram.com",
                "Cookie": f"sessionid={INSTAGRAM_SESSION_ID}",
                "Sec-Ch-Ua-Full-Version-List": '"Chromium";v="148.0.7778.215", "Google Chrome";v="148.0.7778.215", "Not/A)Brand";v="99.0.0.0"',
                "Sec-Ch-Ua-Platform": '"Linux"',
                "Viewport-Width": "1920",
                "Sec-Ch-Ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
                "Sec-Ch-Ua-Model": '""',
                "Sec-Ch-Ua-Mobile": "?0",
                "Dpr": "1",
                "Sec-Ch-Prefers-Color-Scheme": "dark",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
                "Dnt": "1",
                "Content-Type": "application/x-www-form-urlencoded",
                "Sec-Ch-Ua-Platform-Version": '""',
                "Accept": "*/*",
                "Origin": "https://www.instagram.com",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Referer": "https://www.instagram.com/",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Priority": "u=1, i"
            }
            data = {
                "__a": "1",
                "fb_dtsg": INSTAGRAM_FB_DTSG,
                "original_sound_audio_asset_id": str(track_id)
            }
            response = requests.post(INSTAGRAM_API_URL, headers=headers, data=data, timeout=REQUEST_TIMEOUT)

            if response.status_code == 200:
                response_text = response.text
                if response_text.startswith("for (;;);"):
                    response_text = response_text[9:]
                try:
                    json_data = json.loads(response_text)
                    if json_data.get("error"):
                        err_msg = f"Instagram API error {json_data['error']}: {json_data.get('errorSummary', '')}"
                        self.after(0, lambda: messagebox.showerror("Instagram Error",
                            f"{err_msg}\n\nYour Instagram session is likely expired.\n"
                            "Update INSTAGRAM_SESSION_ID and INSTAGRAM_FB_DTSG at the top of music2.py."))
                        return None

                    audio_url = None
                    payload = json_data.get("payload")
                    asset_info = None
                    if payload is not None:
                        items = payload.get("items")
                        if isinstance(items, list) and len(items) > 0:
                            for item in items:
                                media = item.get("media")
                                if media is None:
                                    continue
                                clips_metadata = media.get("clips_metadata")
                                if clips_metadata is None:
                                    continue
                                music_info = clips_metadata.get("music_info")
                                if music_info is None:
                                    continue
                                asset_info = music_info.get("music_asset_info")
                                if asset_info is None:
                                    continue
                                audio_url = (asset_info.get("fast_start_progressive_download_url")
                                             or asset_info.get("progressive_download_url"))
                                if audio_url:
                                    break
                        if not audio_url:
                            metadata = payload.get("metadata")
                            if isinstance(metadata, dict):
                                music_info = metadata.get("music_info")
                                if isinstance(music_info, dict):
                                    asset_info = music_info.get("music_asset_info")
                                    if isinstance(asset_info, dict):
                                        audio_url = (asset_info.get("fast_start_progressive_download_url")
                                                     or asset_info.get("progressive_download_url"))

                    if audio_url:
                        audio_url = audio_url.replace("\\/", "/")
                        if audio_url.startswith("//"):
                            audio_url = "https:" + audio_url
                        duration_ms = asset_info.get("duration_in_ms", 0) if asset_info else 0
                        return (audio_url, duration_ms)
                    return None
                except json.JSONDecodeError:
                    return None
            return None
        except requests.exceptions.RequestException as e:
            print(f"Request error getting audio URL: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error getting audio URL: {e}")
            return None

    # ------------------------------------------------------------ Playback
    def play_selected_track(self):
        if not self.audio_available:
            messagebox.showwarning("Audio Unavailable", "Audio playback is not available. Please check your audio system.")
            return
        if self.selected_index < 0 or self.selected_index >= len(self.track_items):
            messagebox.showinfo("No Selection", "Please select a track first by clicking on it.")
            return

        track = self.track_items[self.selected_index]
        track_id = track.get("id")
        if not track_id:
            self.status_var.set("Error: Track has no ID")
            messagebox.showerror("Error", "Selected track does not have an ID.")
            return

        self.status_var.set(f"Loading audio for {track.get('name')}...")
        self.now_playing_title.config(text=track.get("name", "Loading…"))
        self.now_playing_artist.config(text=track.get("artist", ""))
        self._update_now_playing_art(track.get("cover"))
        self.play_btn.state(["disabled"])

        thread = threading.Thread(target=self._fetch_and_play_audio, args=(track_id,), daemon=True)
        thread.start()

    def _update_now_playing_art(self, cover_data_uri):
        try:
            if cover_data_uri:
                header, b64data = cover_data_uri.split(",", 1) if "," in cover_data_uri else ("", cover_data_uri)
                raw = base64.b64decode(b64data)
                image = Image.open(io.BytesIO(raw))
                self._now_playing_art = make_glow_photo(image)
            else:
                self._now_playing_art = make_glow_photo(Image.new("RGBA", (10, 10), CARD_HOVER))
        except Exception:
            self._now_playing_art = make_glow_photo(Image.new("RGBA", (10, 10), CARD_HOVER))
        self.now_playing_art_label.configure(image=self._now_playing_art)

    def _fetch_and_play_audio(self, track_id):
        result = self.get_instagram_audio_url(track_id)
        if not result:
            self.after(0, lambda: self._on_audio_loaded(None, 0))
            return
        audio_url, duration_ms = result
        import io as _io, subprocess, tempfile
        tmp_mp4 = None
        try:
            resp = requests.get(audio_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            tmp_mp4 = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp_mp4.write(resp.content)
            tmp_mp4.close()
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_mp4.name, "-vn", "-acodec", "libmp3lame",
                 "-ab", "128k", "-ar", "44100", "-ac", "2", "-f", "mp3", "pipe:1"],
                capture_output=True, timeout=30
            )
            os.unlink(tmp_mp4.name)
            proc.check_returncode()
            mp3_buf = _io.BytesIO(proc.stdout)
            self.after(0, lambda: self._on_audio_loaded(mp3_buf, duration_ms))
        except Exception as e:
            print(f"Failed to process audio: {e}")
            if tmp_mp4 and os.path.exists(tmp_mp4.name):
                os.unlink(tmp_mp4.name)
            self.after(0, lambda: self._on_audio_loaded(None, 0))

    def _on_audio_loaded(self, audio_source, duration_ms):
        self.play_btn.state(["!disabled"])
        if not audio_source:
            self.status_var.set("Failed to load audio. Check your Instagram session.")
            messagebox.showerror("Playback Error",
                "Could not load audio.\n\n"
                "Make sure your Instagram session ID is valid and not expired.\n"
                "You may need to log in to Instagram in your browser and update the session ID.")
            return

        self._audio_loaded = True
        self._track_length = duration_ms / 1000.0
        self.time_total_label.config(text=self._format_time(self._track_length))
        self.progress_slider.set(0)
        self.time_current_label.config(text="0:00")

        if self.selected_index >= 0 and self.selected_index < len(self.track_items):
            track = self.track_items[self.selected_index]
            self.current_track = track
            self.now_playing_title.config(text=track.get("name", "Unknown title"))
            self.now_playing_artist.config(text=track.get("artist", "Unknown artist"))

        self._play_audio(audio_source)

    def _play_audio(self, audio_source):
        if not self.audio_available:
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(audio_source)
            pygame.mixer.music.set_volume(0.0 if self._muted else self.current_volume)
            pygame.mixer.music.play()

            self.is_playing = True
            self._audio_loaded = True
            self.play_btn.config(text="⏸ Pause")
            self.status_var.set("Now playing")
            self._start_progress_updates()
        except pygame.error as e:
            self.status_var.set(f"Playback error: {e}")
            messagebox.showerror("Playback Error", f"Could not play audio:\n\n{e}")
        except Exception as e:
            self.status_var.set(f"Unexpected error: {e}")
            messagebox.showerror("Playback Error", f"Unexpected error:\n\n{e}")

    # ------------------------------------------------------------ Progress & controls
    @staticmethod
    def _format_time(seconds: float) -> str:
        m, s = divmod(int(max(0, seconds)), 60)
        return f"{m}:{s:02d}"

    def _start_progress_updates(self):
        self._stop_progress_updates()
        self._update_progress()

    def _stop_progress_updates(self):
        if self._progress_update_id:
            self.after_cancel(self._progress_update_id)
            self._progress_update_id = None

    def _update_progress(self):
        if not self.audio_available:
            return
        try:
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms >= 0:
                pos_sec = pos_ms / 1000.0
                self.time_current_label.config(text=self._format_time(pos_sec))
                if self._track_length > 0:
                    pct = min(pos_sec / self._track_length * 100, 100)
                    self._suppress_seek = True
                    self.progress_slider.set(pct)
                    self._suppress_seek = False
            else:
                self._on_track_end()
                return
            self._progress_update_id = self.after(200, self._update_progress)
        except Exception:
            pass

    def _on_track_end(self):
        self.is_playing = False
        self._audio_loaded = False
        self.play_btn.config(text="▶ Play")
        self.time_current_label.config(text="0:00")
        self.progress_slider.set(0)
        self._stop_progress_updates()

        if self.repeat_mode == "one":
            self.status_var.set("Repeating track")
            self.play_selected_track()
            return

        if self.repeat_mode == "all" or (self.queue_pos + 1) < len(self.play_queue):
            self.status_var.set("Track ended — playing next")
            self.play_next()
        else:
            self.status_var.set("Track ended")

    def _on_seek(self, value_str):
        if self._suppress_seek or not self._audio_loaded or self._track_length <= 0:
            return
        try:
            pct = float(value_str) / 100.0
            target = pct * self._track_length
            pygame.mixer.music.set_pos(target)
        except pygame.error:
            pass

    def _on_volume_change(self, value_str):
        try:
            vol = float(value_str)
            self.current_volume = vol
            if vol > 0 and self._muted:
                self._muted = False
                self.mute_btn.config(text="🔊")
            if not self._muted:
                pygame.mixer.music.set_volume(vol)
            self._update_volume_icon(vol)
        except Exception:
            pass

    def _update_volume_icon(self, vol):
        if self._muted or vol == 0:
            self.mute_btn.config(text="🔇")
        elif vol < 0.5:
            self.mute_btn.config(text="🔉")
        else:
            self.mute_btn.config(text="🔊")

    def toggle_mute(self):
        if not self.audio_available:
            return
        self._muted = not self._muted
        if self._muted:
            self._prev_volume = self.current_volume
            pygame.mixer.music.set_volume(0.0)
        else:
            pygame.mixer.music.set_volume(self.current_volume)
        self._update_volume_icon(self.current_volume)

    def toggle_playback(self):
        if not self.audio_available:
            return
        if not self._audio_loaded:
            if self.selected_index >= 0:
                self.play_selected_track()
            return
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                self.is_playing = False
                self.play_btn.config(text="▶ Play")
                self.status_var.set("Paused")
                self._stop_progress_updates()
            else:
                pygame.mixer.music.unpause()
                self.is_playing = True
                self.play_btn.config(text="⏸ Pause")
                self.status_var.set("Now playing")
                self._start_progress_updates()
        except pygame.error:
            if self.selected_index >= 0:
                self.play_selected_track()

    def stop_playback(self):
        if not self.audio_available:
            return
        try:
            pygame.mixer.music.stop()
            self.is_playing = False
            self._audio_loaded = False
            self.progress_slider.config(value=0)
            self.time_current_label.config(text="0:00")
            self.play_btn.config(text="▶ Play")
            self.status_var.set("Stopped")
            self.now_playing_title.config(text="No track selected")
            self.now_playing_artist.config(text="Select a song below to start listening")
            self._stop_progress_updates()
        except pygame.error as e:
            print(f"Error stopping playback: {e}")

    def on_closing(self):
        self._stop_progress_updates()
        if self.audio_available:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except Exception:
                pass
        self.destroy()


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    app = BeatMusicPlayer()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
