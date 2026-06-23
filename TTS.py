import tkinter as tk
from tkinter import ttk, messagebox
import win32com.client as wincl


# SAPI speech flags
SVS_FLAGS_ASYNC = 1
SVS_PURGE_BEFORE_SPEAK = 2


class TextToSpeechApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Advanced Text to Speech")
        self.geometry("620x470")
        self.minsize(520, 400)
        self.configure(padx=18, pady=18)

        try:
            self.speaker = wincl.Dispatch("SAPI.SpVoice")
            self.voices = list(self.speaker.GetVoices())
        except Exception as error:
            messagebox.showerror(
                "Speech engine error",
                f"Could not start Windows Speech API.\n\n{error}"
            )
            self.destroy()
            return

        self.voice_var = tk.StringVar()
        self.rate_var = tk.IntVar(value=0)
        self.volume_var = tk.IntVar(value=100)
        self.status_var = tk.StringVar(value="Ready")
        self.count_var = tk.StringVar(value="0 characters")

        self.create_widgets()
        self.bind_shortcuts()

    def create_widgets(self):
        title = ttk.Label(
            self,
            text="Text to Speech",
            font=("Segoe UI", 18, "bold")
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            self,
            text="Type or paste text, then choose how you want it spoken."
        )
        subtitle.pack(anchor="w", pady=(0, 14))

        text_frame = ttk.LabelFrame(self, text="Text to speak", padding=10)
        text_frame.pack(fill="both", expand=True)

        self.text_box = tk.Text(
            text_frame,
            wrap="word",
            height=10,
            font=("Segoe UI", 11),
            undo=True
        )
        self.text_box.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=self.text_box.yview
        )
        scrollbar.pack(side="right", fill="y")
        self.text_box.config(yscrollcommand=scrollbar.set)

        self.text_box.bind("<KeyRelease>", self.update_character_count)

        info_frame = ttk.Frame(self)
        info_frame.pack(fill="x", pady=(5, 10))

        ttk.Label(info_frame, textvariable=self.count_var).pack(side="left")
        ttk.Label(
            info_frame,
            text="Shortcut: Ctrl + Enter to speak"
        ).pack(side="right")

        settings = ttk.LabelFrame(self, text="Voice settings", padding=10)
        settings.pack(fill="x", pady=(0, 12))

        ttk.Label(settings, text="Voice:").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=5
        )

        voice_names = [voice.GetDescription() for voice in self.voices]

        self.voice_menu = ttk.Combobox(
            settings,
            textvariable=self.voice_var,
            values=voice_names,
            state="readonly"
        )
        self.voice_menu.grid(row=0, column=1, sticky="ew", pady=5)

        if voice_names:
            self.voice_menu.current(0)

        ttk.Label(settings, text="Speed:").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=5
        )

        rate_slider = ttk.Scale(
            settings,
            from_=-10,
            to=10,
            orient="horizontal",
            variable=self.rate_var
        )
        rate_slider.grid(row=1, column=1, sticky="ew", pady=5)

        ttk.Label(settings, text="Volume:").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=5
        )

        volume_slider = ttk.Scale(
            settings,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.volume_var
        )
        volume_slider.grid(row=2, column=1, sticky="ew", pady=5)

        settings.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x")

        ttk.Button(
            buttons,
            text="▶ Speak",
            command=self.speak_text
        ).pack(side="left")

        ttk.Button(
            buttons,
            text="■ Stop",
            command=self.stop_speaking
        ).pack(side="left", padx=8)

        ttk.Button(
            buttons,
            text="Clear",
            command=self.clear_text
        ).pack(side="left")

        ttk.Label(
            self,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=6
        ).pack(fill="x", pady=(14, 0))

    def bind_shortcuts(self):
        self.bind("<Control-Return>", lambda event: self.speak_text())
        self.bind("<Escape>", lambda event: self.stop_speaking())
        self.bind("<Control-l>", lambda event: self.clear_text())

    def update_character_count(self, event=None):
        text = self.text_box.get("1.0", "end-1c")
        self.count_var.set(f"{len(text)} characters")

    def speak_text(self):
        text = self.text_box.get("1.0", "end-1c").strip()

        if not text:
            messagebox.showwarning(
                "No text entered",
                "Please type something for the app to speak."
            )
            return

        try:
            selected_voice = self.voice_menu.current()

            if selected_voice >= 0:
                self.speaker.Voice = self.voices[selected_voice]

            self.speaker.Rate = int(self.rate_var.get())
            self.speaker.Volume = int(self.volume_var.get())

            # Stop any current speech, then begin the new text asynchronously.
            self.speaker.Speak("", SVS_FLAGS_ASYNC | SVS_PURGE_BEFORE_SPEAK)
            self.speaker.Speak(text, SVS_FLAGS_ASYNC)

            self.status_var.set("Speaking...")
        except Exception as error:
            self.status_var.set("Error")
            messagebox.showerror("Speech error", str(error))

    def stop_speaking(self):
        try:
            self.speaker.Speak("", SVS_FLAGS_ASYNC | SVS_PURGE_BEFORE_SPEAK)
            self.status_var.set("Speech stopped")
        except Exception as error:
            messagebox.showerror("Stop error", str(error))

    def clear_text(self):
        self.stop_speaking()
        self.text_box.delete("1.0", "end")
        self.update_character_count()
        self.status_var.set("Text cleared")
        self.text_box.focus_set()


if __name__ == "__main__":
    app = TextToSpeechApp()
    app.mainloop()
