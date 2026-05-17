import os
import json
import sys
import shutil
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import yt_dlp

CONFIG_FILE = "config.json"


def find_ffmpeg():
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        return os.path.dirname(ffmpeg_exe)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(script_dir, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if os.path.exists(local):
        return script_dir

    if sys.platform == "win32":
        candidates = [
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            r"C:\Users\Administrator\Downloads\ffmpeg-2026-05-13-git-a327bc0561-full_build\ffmpeg-2026-05-13-git-a327bc0561-full_build\bin",
        ]
        for c in candidates:
            if os.path.exists(os.path.join(c, "ffmpeg.exe")):
                return c

    return None


def check_cookies_valid(cookie_path):
    """
    Returns (valid: bool, message: str).
    Parses the cookies file and checks if the critical YouTube auth cookies
    are present and not expired.
    """
    if not cookie_path or not os.path.exists(cookie_path):
        return False, "cookies.txt not found"

    now = time.time()
    required = {"SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID"}
    found = {}

    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                name = parts[5]
                expires = parts[4]
                if name in required:
                    try:
                        exp = int(expires)
                        if exp == 0:
                            found[name] = True  # session cookie, treat as valid
                        elif exp < now:
                            return False, f"cookie '{name}' has expired — please re-export cookies.txt"
                        else:
                            found[name] = True
                    except ValueError:
                        found[name] = True
    except Exception as e:
        return False, f"could not read cookies.txt: {e}"

    missing = required - set(found.keys())
    if missing:
        return False, f"cookies.txt is missing auth cookies: {', '.join(missing)} — are you logged in?"

    return True, "cookies valid"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("yt downloader - @s43q")
        self.root.geometry("900x800")
        self.root.configure(bg="#0f0f0f")

        self.url = tk.StringVar()
        self.url_limit = tk.StringVar(value="5")   # per-channel limit input
        self.path = tk.StringVar()
        self.mode = tk.StringVar()
        self.quality = tk.StringVar()
        self.cookie_path = tk.StringVar()
        self.progress = tk.DoubleVar()

        # queue: list of {"url": str, "limit": str}
        self.queue = []
        self.is_running = False

        self.load_config()
        self.ui()

        for var in (self.mode, self.path, self.quality, self.cookie_path):
            var.trace_add("write", lambda *_: self.save_config())

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # ---------------- config ----------------
    def load_config(self):
        default = os.path.join(os.getcwd(), "downloads")
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}

        self.path.set(data.get("path", default))
        self.mode.set(data.get("mode", "both"))
        self.quality.set(data.get("quality", "best"))
        self.cookie_path.set(data.get("cookie_path", ""))

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "path": self.path.get(),
                "mode": self.mode.get(),
                "quality": self.quality.get(),
                "cookie_path": self.cookie_path.get(),
            }, f)

    # ---------------- UI ----------------
    def ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0f0f0f")
        style.configure("TLabel", background="#0f0f0f", foreground="white")

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        ttk.Label(main, text="yt downloader - @s43q",
                  font=("Segoe UI", 22, "bold")).pack(pady=10)

        # ---- settings card ----
        card = tk.Frame(main, bg="#1a1a1a")
        card.pack(fill="x", pady=(0, 8))

        tk.Label(card, text="download folder", bg="#1a1a1a", fg="white").pack(anchor="w", padx=10, pady=(10, 0))
        row = tk.Frame(card, bg="#1a1a1a")
        row.pack(fill="x", padx=10, pady=5)
        tk.Entry(row, textvariable=self.path, bg="#111", fg="white", insertbackground="white").pack(
            side="left", fill="x", expand=True)
        tk.Button(row, text="browse", command=self.browse).pack(side="right", padx=5)

        # cookies row
        tk.Label(card, text="cookies.txt", bg="#1a1a1a", fg="#aaa").pack(anchor="w", padx=10)
        crow = tk.Frame(card, bg="#1a1a1a")
        crow.pack(fill="x", padx=10, pady=(0, 4))
        tk.Entry(crow, textvariable=self.cookie_path, bg="#111", fg="white",
                 insertbackground="white").pack(side="left", fill="x", expand=True)
        tk.Button(crow, text="browse", command=self.browse_cookies).pack(side="left", padx=5)
        tk.Button(crow, text="ℹ", command=self.show_cookie_info, relief="flat",
                  bg="#1a1a1a", fg="#aaa", font=("Segoe UI", 12), cursor="hand2").pack(side="left")
        tk.Button(crow, text="check cookies", command=self.check_cookies_ui).pack(side="left", padx=(8, 0))

        self.cookie_status = tk.Label(card, text="", bg="#1a1a1a", fg="#aaa", font=("Segoe UI", 8))
        self.cookie_status.pack(anchor="w", padx=10, pady=(0, 6))

        opt = tk.Frame(card, bg="#1a1a1a")
        opt.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(opt, text="mode", bg="#1a1a1a", fg="white").pack(side="left")
        ttk.OptionMenu(opt, self.mode, self.mode.get(), "videos", "shorts", "both").pack(side="left", padx=5)
        tk.Label(opt, text="quality", bg="#1a1a1a", fg="white").pack(side="left", padx=10)
        ttk.OptionMenu(opt, self.quality, self.quality.get(),
                       "best", "1080p", "720p", "480p", "360p", "audio only").pack(side="left")

        # ---- queue + quality checker side by side ----
        bottom_row = tk.Frame(main, bg="#0f0f0f")
        bottom_row.pack(fill="x", pady=(0, 8))

        # queue card (left)
        qcard = tk.Frame(bottom_row, bg="#1a1a1a")
        qcard.pack(side="left", fill="both", expand=True, padx=(0, 6))

        tk.Label(qcard, text="channel queue", bg="#1a1a1a", fg="white").pack(anchor="w", padx=10, pady=(10, 0))

        add_row = tk.Frame(qcard, bg="#1a1a1a")
        add_row.pack(fill="x", padx=10, pady=5)
        tk.Entry(add_row, textvariable=self.url, bg="#111", fg="white", insertbackground="white").pack(
            side="left", fill="x", expand=True)
        tk.Label(add_row, text="limit", bg="#1a1a1a", fg="#aaa", font=("Segoe UI", 8)).pack(side="left", padx=(6, 2))
        tk.Entry(add_row, textvariable=self.url_limit, width=4, bg="#111", fg="white",
                 insertbackground="white").pack(side="left")
        tk.Button(add_row, text="add", command=self.add_to_queue).pack(side="left", padx=5)

        list_frame = tk.Frame(qcard, bg="#1a1a1a")
        list_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.queue_listbox = tk.Listbox(
            list_frame, bg="#111", fg="white", selectbackground="#333",
            height=4, font=("Segoe UI", 9))
        self.queue_listbox.pack(side="left", fill="x", expand=True)
        scrollbar = tk.Scrollbar(list_frame, command=self.queue_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.queue_listbox.config(yscrollcommand=scrollbar.set)

        qbtns = tk.Frame(qcard, bg="#1a1a1a")
        qbtns.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(qbtns, text="remove selected", command=self.remove_selected).pack(side="left")
        tk.Button(qbtns, text="clear", command=self.clear_queue).pack(side="left", padx=5)
        self.start_btn = tk.Button(qbtns, text="▶  start queue", command=self.start_queue,
                                   bg="#1db954", fg="white", font=("Segoe UI", 9, "bold"))
        self.start_btn.pack(side="right")

        # quality checker card (right)
        chkcard = tk.Frame(bottom_row, bg="#1a1a1a")
        chkcard.pack(side="left", fill="both", expand=True)

        tk.Label(chkcard, text="check video quality", bg="#1a1a1a", fg="white").pack(anchor="w", padx=10, pady=(10, 0))

        chk_row = tk.Frame(chkcard, bg="#1a1a1a")
        chk_row.pack(fill="x", padx=10, pady=5)
        self.check_path_var = tk.StringVar()
        tk.Entry(chk_row, textvariable=self.check_path_var, bg="#111", fg="white",
                 insertbackground="white").pack(side="left", fill="x", expand=True)
        tk.Button(chk_row, text="browse", command=self.browse_video).pack(side="left", padx=5)
        tk.Button(chk_row, text="check", command=self.check_quality).pack(side="left")

        self.quality_result = tk.Label(chkcard, text="select a video file to check",
                                       bg="#1a1a1a", fg="#aaa", font=("Segoe UI", 10))
        self.quality_result.pack(anchor="w", padx=10, pady=(8, 0))

        # ---- progress ----
        prog_frame = tk.Frame(main, bg="#0f0f0f")
        prog_frame.pack(fill="x", pady=(0, 4))

        self.channel_label = tk.Label(prog_frame, text="", bg="#0f0f0f", fg="#aaa", font=("Segoe UI", 9))
        self.channel_label.pack(anchor="w")
        self.video_label = tk.Label(prog_frame, text="", bg="#0f0f0f", fg="white", font=("Segoe UI", 9, "bold"))
        self.video_label.pack(anchor="w")
        self.bar = ttk.Progressbar(prog_frame, variable=self.progress, maximum=100)
        self.bar.pack(fill="x", pady=(4, 0))

        # ---- debug ----
        ttk.Label(main, text="debug").pack(anchor="w")
        self.log = tk.Text(main, height=10, bg="#000", fg="#00ff88")
        self.log.pack(fill="both", expand=True)

        btns = tk.Frame(main, bg="#0f0f0f")
        btns.pack(fill="x")
        tk.Button(btns, text="copy debug", command=self.copy).pack(side="left", padx=5, pady=5)
        tk.Button(btns, text="clear", command=self.clear).pack(side="left")

    # ---------------- cookie check ----------------
    def check_cookies_ui(self):
        valid, msg = check_cookies_valid(self.cookie_path.get().strip())
        if valid:
            self.cookie_status.config(text=f"✓ {msg}", fg="#1db954")
        else:
            self.cookie_status.config(text=f"✗ {msg}", fg="#ff4444")

    # ---------------- queue management ----------------
    def add_to_queue(self):
        url = self.url.get().strip()
        limit = self.url_limit.get().strip() or "0"
        if not url:
            messagebox.showwarning("missing url", "please enter a channel or video url")
            return
        if not url.startswith("http"):
            messagebox.showwarning("invalid url", "url must start with https://")
            return
        if any(e["url"] == url for e in self.queue):
            messagebox.showwarning("duplicate", "that url is already in the queue")
            return
        self.queue.append({"url": url, "limit": limit})
        label = f"{url}  [limit: {limit}]" if limit != "0" else f"{url}  [no limit]"
        self.queue_listbox.insert(tk.END, label)
        self.url.set("")

    def remove_selected(self):
        sel = self.queue_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.queue_listbox.delete(idx)
        self.queue.pop(idx)

    def clear_queue(self):
        self.queue.clear()
        self.queue_listbox.delete(0, tk.END)

    def start_queue(self):
        if self.is_running:
            messagebox.showwarning("busy", "a download is already running")
            return
        if not self.queue:
            messagebox.showwarning("empty queue", "add at least one channel to the queue")
            return

        # check cookies before starting
        valid, msg = check_cookies_valid(self.cookie_path.get().strip())
        if not valid:
            self.cookie_status.config(text=f"✗ {msg}", fg="#ff4444")
            messagebox.showerror("cookies expired",
                f"{msg}\n\nPlease re-export your cookies.txt before downloading.")
            return

        self.cookie_status.config(text=f"✓ cookies valid", fg="#1db954")
        self.is_running = True
        self.start_btn.config(state="disabled")
        threading.Thread(target=self.run_queue, daemon=True).start()

    # ---------------- queue runner ----------------
    def run_queue(self):
        items = list(self.queue)
        total_channels = len(items)

        for ch_idx, entry in enumerate(items):
            url = entry["url"]
            limit = entry["limit"]
            self.root.after(0, self.channel_label.config,
                            {"text": f"channel {ch_idx + 1}/{total_channels}  —  {url}"})
            self.root.after(0, self.video_label.config, {"text": ""})
            self.progress.set(0)
            self.log_write(f"\n▶ [{ch_idx + 1}/{total_channels}] {url}  (limit: {limit})")
            self.download_one(url, limit)

        self.root.after(0, self._queue_done)

    def _queue_done(self):
        self.is_running = False
        self.start_btn.config(state="normal")
        self.channel_label.config(text="all done")
        self.video_label.config(text="")
        self.progress.set(100)
        messagebox.showinfo("done", "all channels finished")

    # ---------------- download ----------------
    def download_one(self, url, limit):
        out = self.path.get().strip()
        os.makedirs(out, exist_ok=True)
        mode = self.mode.get()
        ffmpeg_dir = find_ffmpeg()

        video_count = [0]
        total_videos = [0]

        def hook(d):
            if d["status"] == "downloading":
                try:
                    p = d.get("_percent_str", "0%").replace("%", "").strip()
                    self.progress.set(float(p))
                except Exception:
                    pass
            elif d["status"] == "finished":
                self.progress.set(100)

        def postprocess_hook(d):
            if d["status"] == "started":
                video_count[0] += 1
                title = d.get("info_dict", {}).get("title", "")[:55]
                cnt = video_count[0]
                tot = total_videos[0]
                label = f"video {cnt}/{tot}  —  {title}" if tot else f"video {cnt}  —  {title}"
                self.root.after(0, self.video_label.config, {"text": label})

        cookie_path = self.cookie_path.get().strip()
        ydl_opts = {
            "outtmpl": os.path.join(out, "%(channel)s", "%(title)s.%(ext)s"),
            "ignoreerrors": True,
            "progress_hooks": [hook],
            "postprocessor_hooks": [postprocess_hook],
            "merge_output_format": "mp4",
            "format_sort": ["res", "ext:mp4:m4a"],
        }

        if cookie_path and os.path.exists(cookie_path):
            ydl_opts["cookiefile"] = cookie_path
            self.log_write(f"cookies: {cookie_path}")
        else:
            self.log_write("WARNING: no cookies.txt — may get 360p")

        if ffmpeg_dir:
            ydl_opts["ffmpeg_location"] = ffmpeg_dir

        q = self.quality.get()
        if q == "best":
            ydl_opts["format"] = "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best"
        elif q == "1080p":
            ydl_opts["format"] = "bestvideo[height<=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]"
        elif q == "720p":
            ydl_opts["format"] = "bestvideo[height<=720][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]"
        elif q == "480p":
            ydl_opts["format"] = "bestvideo[height<=480][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]"
        elif q == "360p":
            ydl_opts["format"] = "bestvideo[height<=360][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]"
        elif q == "audio only":
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio"
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
            ydl_opts.pop("merge_output_format", None)
        else:
            ydl_opts["format"] = "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best"

        if mode == "videos":
            ydl_opts["match_filter"] = yt_dlp.utils.match_filter_func("duration > 60")
        elif mode == "shorts":
            ydl_opts["match_filter"] = yt_dlp.utils.match_filter_func("duration <= 60")

        if limit.isdigit() and int(limit) > 0:
            ydl_opts["playlist_items"] = f"1-{limit}"
            total_videos[0] = int(limit)

        self.log_write(f"quality: {q}  |  ffmpeg: {ffmpeg_dir or 'NOT FOUND'}")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self.log_write(f"✓ done: {url}")
        except Exception as e:
            self.log_write(f"✗ error: {e}")

    # ---------------- debug ----------------
    def log_write(self, msg):
        self.root.after(0, self._log_write_main, msg)

    def _log_write_main(self, msg):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get("1.0", tk.END))

    def clear(self):
        self.log.delete("1.0", tk.END)

    # ---------------- misc ----------------
    def show_cookie_info(self):
        messagebox.showinfo("cookies.txt setup",
            "A cookies.txt file lets yt-dlp authenticate with YouTube and\n"
            "get full 1080p adaptive streams instead of the 360p fallback.\n\n"
            "How to export:\n"
            "1. Open Firefox and go to youtube.com\n"
            "2. Make sure you're logged in\n"
            "3. Install 'Get cookies.txt LOCALLY' extension\n"
            "4. Click the extension icon and export for youtube.com\n"
            "5. Browse to the file in the cookies.txt field above\n\n"
            "If downloads drop back to 360p, just re-export — cookies expire.")

    def browse_cookies(self):
        p = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if p:
            self.cookie_path.set(p)

    def browse(self):
        p = filedialog.askdirectory()
        if p:
            self.path.set(p)

    def browse_video(self):
        p = filedialog.askopenfilename(filetypes=[
            ("Video files", "*.mp4 *.mkv *.webm *.avi *.mov *.m4v"),
            ("All files", "*.*")
        ])
        if p:
            self.check_path_var.set(p)

    def check_quality(self):
        path = self.check_path_var.get().strip()
        if not path or not os.path.exists(path):
            self.quality_result.config(text="no file selected", fg="#ff4444")
            return

        ffmpeg_dir = find_ffmpeg()
        if not ffmpeg_dir:
            self.quality_result.config(text="ffmpeg not found — cannot check quality", fg="#ff4444")
            return

        import subprocess
        ffprobe = os.path.join(ffmpeg_dir, "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if not os.path.exists(ffprobe):
            self.quality_result.config(text="ffprobe not found in ffmpeg folder", fg="#ff4444")
            return

        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,codec_name,r_frame_rate",
                 "-of", "json", path],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if not streams:
                self.quality_result.config(text="no video stream found — audio only?", fg="#ffaa00")
                return

            s = streams[0]
            width = s.get("width", "?")
            height = s.get("height", "?")
            codec = s.get("codec_name", "?")

            fps_raw = s.get("r_frame_rate", "0/1")
            try:
                num, den = fps_raw.split("/")
                fps = round(int(num) / int(den), 2)
            except Exception:
                fps = fps_raw

            if height == "?":
                res_label = "unknown"
            elif int(height) >= 2160:
                res_label = "4K (2160p)"
            elif int(height) >= 1440:
                res_label = "1440p"
            elif int(height) >= 1080:
                res_label = "1080p ✓"
            elif int(height) >= 720:
                res_label = "720p"
            elif int(height) >= 480:
                res_label = "480p"
            elif int(height) >= 360:
                res_label = "360p"
            else:
                res_label = f"{height}p"

            color = "#1db954" if int(height) >= 1080 else "#ffaa00" if int(height) >= 720 else "#ff4444"
            self.quality_result.config(
                text=f"{res_label}  |  {width}×{height}  |  {codec}  |  {fps}fps",
                fg=color
            )
        except Exception as e:
            self.quality_result.config(text=f"error: {e}", fg="#ff4444")

    def close(self):
        self.save_config()
        self.root.destroy()
        sys.exit(0)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
