"""DISPATCH v0.1 — hold F8, ask, release, listen."""
import copy
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from openai import AuthenticationError, RateLimitError, APIConnectionError
from PIL import ImageTk
import mss
import sounddevice as sd

from core import SYSTEM_PROMPT, load_state, save_state, build_input, append_turn
from devices import enable_dpi_awareness, capture, record
from plus_test import authenticate
from plan_connection import PlanConnection
from local_voice import LocalVoice, speak

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "local" / "state.json"



class Dispatch:
    def __init__(self, root, connection):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.key_down = False
        self.key_lock = threading.Lock()
        self.record_stop = threading.Event()
        self.play_stop = threading.Event()
        self.cancel = threading.Event()
        self.hotkey_stop = threading.Event()
        self.hotkey_thread = None
        self.photo = None
        self.preview_window = None
        self.hotkeys_enabled = threading.Event()
        self.state = load_state(STATE_PATH)
        self.client = connection
        self.voice = LocalVoice()
        self._ui()
        self._hotkeys()
        self._start(lambda options, state: self.voice.prepare(), False)
        self.status.set("PREPARING LOCAL VOICE · first launch downloads the speech model")
        self.root.after(40, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _ui(self):
        self.root.title("DISPATCH · Resident Evil Companion")
        self.root.geometry("780x850")
        self.root.minsize(650, 680)
        self.root.configure(bg="#101820")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#101820")
        style.configure("TLabel", background="#101820", foreground="#dfe8ee")
        style.configure("TCheckbutton", background="#101820", foreground="#dfe8ee")
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="📡 DISPATCH", font=("Segoe UI", 24, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Hold F8 → wait for LISTENING → ask → release F8", font=("Segoe UI", 11)).pack(anchor="w", pady=(2, 12))
        self.status = tk.StringVar(value="READY" if self.client else "SETUP · Add OPENAI_API_KEY to .env, then restart")
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI", 12, "bold"), wraplength=720).pack(anchor="w", pady=6)
        ttk.Label(frame, text="Plus allowance · Local microphone transcription and Windows voice · No paid API fallback.", wraplength=720).pack(anchor="w")

        settings = ttk.Frame(frame)
        settings.pack(fill="x", pady=12)
        with mss.mss() as screen:
            captures = ["Game window"] + [f"Monitor {i}" for i in range(1, len(screen.monitors))]
        self.capture_mode = tk.StringVar(value="Game window")
        self.title_fragment = tk.StringVar(value="RESIDENT EVIL")
        self._row(settings, "Capture", ttk.Combobox(settings, textvariable=self.capture_mode, values=captures, state="readonly"), 0)
        self._row(settings, "Window title contains", ttk.Entry(settings, textvariable=self.title_fragment), 1)
        inputs = {"System default": None}
        outputs = {"System default": None}
        for index, device in enumerate(sd.query_devices()):
            label = f"{index}: {device['name']}"
            if device["max_input_channels"]:
                inputs[label] = index
            if device["max_output_channels"]:
                outputs[label] = index
        self.input_devices, self.output_devices = inputs, outputs
        self.input_choice = tk.StringVar(value="System default")
        self.output_choice = tk.StringVar(value="System default")
        self._row(settings, "Microphone", ttk.Combobox(settings, textvariable=self.input_choice, values=list(inputs), state="readonly"), 2)
        self._row(settings, "Headphones / output", ttk.Combobox(settings, textvariable=self.output_choice, values=list(outputs), state="readonly"), 3)
        settings.columnconfigure(1, weight=1)

        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.capture_button = ttk.Button(bar, text="Test capture (no API)", command=self.test_capture)
        self.capture_button.pack(side="left")
        self.talk_button = ttk.Button(bar, text="Start mic", command=self.toggle_mic)
        self.talk_button.pack(side="left", padx=8)
        ttk.Button(bar, text="Cancel / stop voice · F9", command=self.stop).pack(side="left")

        self.armed = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Enable F8 hotkey (after checking the capture)", variable=self.armed,
                        command=self.arm).pack(anchor="w", pady=(8, 4))
        ttk.Label(frame, text="Game capture reads the visible window area; keep RE2 unobstructed and use borderless mode.", wraplength=720).pack(anchor="w")

        notebook = ttk.Notebook(frame)
        notebook.pack(fill="both", expand=True, pady=12)
        conversation = ttk.Frame(notebook, padding=10)
        notes = ttk.Frame(notebook, padding=10)
        notebook.add(conversation, text="Radio log")
        notebook.add(notes, text="Confirmed game notes")
        profile = ttk.Frame(notebook, padding=10)
        notebook.add(profile, text="About Cam")
        ttk.Label(profile, text="Editable context sent with questions. This is separate from your ChatGPT account memory.", wraplength=690).pack(anchor="w", pady=8)
        self.profile = ScrolledText(profile, wrap="word", bg="#17232e", fg="#e4eef5", insertbackground="white")
        self.profile.insert("1.0", self.state.get("player_profile", ""))
        self.profile.pack(fill="both", expand=True)
        ttk.Button(profile, text="Save profile", command=self.save_notes).pack(anchor="w", pady=8)
        self.log = ScrolledText(conversation, wrap="word", bg="#17232e", fg="#e4eef5", font=("Segoe UI", 11), state="disabled")
        self.log.pack(fill="both", expand=True)
        entry_bar = ttk.Frame(conversation)
        entry_bar.pack(fill="x", pady=(10, 0))
        self.question = tk.StringVar()
        entry = ttk.Entry(entry_bar, textvariable=self.question)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _: self.ask_text())
        self.send_button = ttk.Button(entry_bar, text="Ask + capture", command=self.ask_text)
        self.send_button.pack(side="left", padx=(8, 0))

        note_form = ttk.Frame(notes)
        note_form.pack(fill="x")
        self.fields = {}
        for row, (key, label) in enumerate((("game", "Game"), ("scenario", "Scenario / difficulty"), ("current_objective", "Current objective"))):
            variable = tk.StringVar(value=self.state[key])
            self.fields[key] = variable
            self._row(note_form, label, ttk.Entry(note_form, textvariable=variable), row)
        note_form.columnconfigure(1, weight=1)
        ttk.Label(notes, text="Only save facts you confirmed: location, inventory, completed objectives, rooms cleared.", wraplength=690).pack(anchor="w", pady=8)
        self.notes = ScrolledText(notes, height=8, wrap="word", bg="#17232e", fg="#e4eef5", insertbackground="white")
        self.notes.insert("1.0", self.state["confirmed_notes"])
        self.notes.pack(fill="both", expand=True)
        note_bar = ttk.Frame(notes)
        note_bar.pack(fill="x", pady=(8, 0))
        ttk.Button(note_bar, text="Save confirmed notes", command=self.save_notes).pack(side="left")
        self.clear_button = ttk.Button(note_bar, text="Clear radio history", command=self.clear_history)
        self.clear_button.pack(side="left", padx=8)
        ttk.Label(frame, text="v0.2 · ChatGPT plan · One frame per question · F9 cancels · Max mic recording: 30 seconds").pack(anchor="w")
        for item in self.state["history"]:
            self.write_log("YOU" if item["role"] == "user" else "DISPATCH", item["content"])

    @staticmethod
    def _row(parent, label, widget, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        widget.grid(row=row, column=1, sticky="ew", pady=3)

    def _hotkeys(self):
        # Poll Windows directly. Some games consume keyboard events before a
        # pynput hook sees them, while GetAsyncKeyState still reflects the
        # physical key even when the game owns focus.
        def watch():
            user32 = __import__("ctypes").windll.user32
            f8_was_down = False
            f9_was_down = False
            while not self.hotkey_stop.wait(0.015):
                f8_down = bool(user32.GetAsyncKeyState(0x77) & 0x8000)
                f9_down = bool(user32.GetAsyncKeyState(0x78) & 0x8000)
                if f9_down and not f9_was_down:
                    self.cancel.set()
                    self.record_stop.set()
                    self.play_stop.set()
                    self.events.put(("stop", None))
                if self.hotkeys_enabled.is_set():
                    if f8_down and not f8_was_down:
                        with self.key_lock:
                            self.key_down = True
                            self.record_stop.clear()
                        self.events.put(("begin", None))
                    elif not f8_down and f8_was_down:
                        with self.key_lock:
                            self.key_down = False
                        self.record_stop.set()
                elif self.key_down:
                    with self.key_lock:
                        self.key_down = False
                    self.record_stop.set()
                f8_was_down, f9_was_down = f8_down, f9_down
        try:
            self.hotkey_thread = threading.Thread(target=watch, daemon=True)
            self.hotkey_thread.start()
        except Exception as error:
            self.write_log("SYSTEM", f"Hotkey unavailable: {error}. Use Start mic / Stop mic buttons.")

    def arm(self):
        if self.armed.get():
            self.hotkeys_enabled.set()
        else:
            self.hotkeys_enabled.clear()
            self.record_stop.set()

    def write_log(self, speaker, message):
        self.log.configure(state="normal")
        self.log.insert("end", f"{speaker}  {time.strftime('%H:%M:%S')}\n{message}\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def save_notes(self, announce=True):
        for key, variable in self.fields.items():
            self.state[key] = variable.get().strip()
        self.state["confirmed_notes"] = self.notes.get("1.0", "end").strip()
        self.state["player_profile"] = self.profile.get("1.0", "end").strip()
        save_state(STATE_PATH, self.state)
        if announce:
            self.write_log("SYSTEM", "Confirmed notes saved locally.")

    def clear_history(self):
        if self.busy:
            return
        self.state["history"] = []
        save_state(STATE_PATH, self.state)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def options(self):
        fragment = self.title_fragment.get().strip()
        if self.capture_mode.get() == "Game window" and not fragment:
            raise ValueError("Enter part of the game window's title.")
        return (self.capture_mode.get(), fragment, self.input_devices[self.input_choice.get()],
                self.output_devices[self.output_choice.get()])

    def _start(self, target, needs_api=True):
        if self.busy:
            return
        if needs_api and not self.client:
            self.write_log("SYSTEM", "Add OPENAI_API_KEY in .env and restart. Capture testing needs no key.")
            return
        try:
            self.save_notes(False)
            options, snapshot = self.options(), copy.deepcopy(self.state)
        except Exception as error:
            self.write_log("SYSTEM", str(error))
            return
        self.busy = True
        self.cancel.clear()
        self.play_stop.clear()
        for button in (self.capture_button, self.send_button, self.clear_button):
            button.configure(state="disabled")
        self.status.set("CAPTURING")
        threading.Thread(target=self._guard, args=(target, options, snapshot), daemon=True).start()

    def _guard(self, target, options, state):
        try:
            target(options, state)
        except AuthenticationError:
            self.events.put(("error", "ChatGPT session rejected. Restart Dispatch to reconnect."))
        except RateLimitError:
            self.events.put(("error", "ChatGPT allowance/rate limit reached. Check ChatGPT Settings → Usage."))
        except APIConnectionError:
            self.events.put(("error", "Could not reach OpenAI. Check your internet connection."))
        except Exception as error:
            # Avoid printing API request bodies, keys, screenshots or raw server errors.
            from openai import APIStatusError
            detail = f"OpenAI returned HTTP {error.status_code}. Check ChatGPT model access and plan allowance." if isinstance(error, APIStatusError) else str(error)
            if not self.cancel.is_set():
                self.events.put(("error", detail))
        finally:
            self.events.put(("done", None))

    def test_capture(self):
        def work(options, state):
            image, _, source = capture(options[0], options[1])
            self.events.put(("preview", (image, source)))
        self._start(work, False)

    def begin_voice(self):
        def work(options, state):
            image, url, source = capture(options[0], options[1])
            if self.cancel.is_set():
                return
            audio = record(self.record_stop, options[2], lambda: self.events.put(("status", "LISTENING · release F8 / click Stop mic to send")))
            if self.cancel.is_set():
                return
            self.events.put(("status", "TRANSCRIBING"))
            question = self.voice.transcribe(audio)
            if not question:
                raise RuntimeError("No speech recognized. Try again with your headset mic.")
            self.respond(question, url, source, options[3], state)
        self._start(work)
        if self.busy:
            self.talk_button.configure(text="Stop mic")

    def toggle_mic(self):
        if self.busy:
            self.record_stop.set()
        else:
            self.record_stop.clear()
            self.begin_voice()

    def ask_text(self):
        question = self.question.get().strip()
        if not question or self.busy:
            return
        def work(options, state):
            _, url, source = capture(options[0], options[1])
            self.respond(question, url, source, options[3], state)
        self._start(work)
        if self.busy:
            self.question.set("")

    def respond(self, question, url, source, output_device, state):
        if self.cancel.is_set():
            return
        self.events.put(("question", question))
        self.events.put(("status", "ANALYZING"))
        profile = state.get("player_profile", "")
        answer = self.client.answer(SYSTEM_PROMPT + "\nPlayer profile (not game progress):\n" + profile,
                                    build_input(state, question, url, source), self.cancel)
        if self.cancel.is_set():
            return
        if not answer:
            raise RuntimeError("Model returned no answer. Try again or check the configured vision model.")
        self.events.put(("answer", (question, answer)))
        self.events.put(("status", "GENERATING VOICE"))
        if self.cancel.is_set():
            return
        self.events.put(("status", "RESPONDING · Windows voice"))
        speak(answer, output_device, self.play_stop)

    def stop(self):
        self.cancel.set()
        self.record_stop.set()
        self.play_stop.set()
        if self.busy:
            self.status.set("CANCELLING · waiting for current request to finish")

    def show_preview(self, image, source):
        if self.preview_window and self.preview_window.winfo_exists():
            self.preview_window.destroy()
        self.preview_window = tk.Toplevel(self.root)
        self.preview_window.title(f"Capture test · {source}")
        preview = image.copy()
        preview.thumbnail((960, 600))
        self.photo = ImageTk.PhotoImage(preview)
        ttk.Label(self.preview_window, image=self.photo).pack()
        ttk.Label(self.preview_window, text="Check that this is RE2 and the map text is readable. No API call was made.").pack(padx=12, pady=12)
        self.write_log("SYSTEM", f"Capture preview: {source}. Close this preview before asking Dispatch.")

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "begin":
                    if not self.busy:
                        self.begin_voice()
                elif kind == "stop":
                    self.stop()
                elif kind == "status":
                    if not self.cancel.is_set():
                        self.status.set(value)
                elif kind == "question":
                    self.write_log("YOU", value)
                elif kind == "answer":
                    question, answer = value
                    self.write_log("DISPATCH", answer)
                    append_turn(self.state, question, answer)
                    try:
                        save_state(STATE_PATH, self.state)
                    except OSError as error:
                        self.write_log("SYSTEM", f"Reply received, but local history could not save: {error}")
                elif kind == "error":
                    self.write_log("SYSTEM", value)
                elif kind == "preview":
                    self.show_preview(*value)
                elif kind == "done":
                    self.busy = False
                    self.talk_button.configure(text="Start mic")
                    for button in (self.capture_button, self.send_button, self.clear_button):
                        button.configure(state="normal")
                    self.status.set("READY" if self.client else "SETUP · API key needed for questions")
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def close(self):
        self.closed = True
        self.stop()
        self.hotkeys_enabled.clear()
        self.hotkey_stop.set()
        try:
            self.save_notes(False)
        except OSError:
            pass
        self.root.destroy()


def main():
    if sys.platform != "win32":
        raise SystemExit("Dispatch's desktop app currently supports Windows only.")
    enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    try:
        connection = PlanConnection(*authenticate())
        Dispatch(root, connection)
    except Exception as error:
        messagebox.showerror("Dispatch could not start", f"{type(error).__name__}: {error}\n\nIf state.json is damaged, rename local/state.json and relaunch.")
        root.destroy()
        raise SystemExit(1)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
