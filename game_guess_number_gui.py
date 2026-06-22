#!/usr/bin/env python3
"""
Script Name     : game_guess_number_gui.py
Description     : A beautiful, desktop-styled GUI version of the classic
                  "Guess the Number" game using Tkinter. Includes high/low
                  cues, color-coded temperature feedback (hot/cold), guess
                  history tracking, and custom score calculations.
"""

import random
import tkinter as tk
from tkinter import messagebox, ttk


class GuessingGameGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("Guess the Number - Premium Edition")
        self.geometry("520x600")
        self.resizable(False, False)
        
        # Color Palette
        self.bg_color = "#1e1e2e"       # Sleek dark blue/grey
        self.card_color = "#252538"     # Lighter card container
        self.fg_color = "#cdd6f4"       # Off-white
        self.accent_color = "#cba6f7"   # Pastel purple
        self.green_color = "#a6e3a1"    # Mint green
        self.yellow_color = "#f9e2af"   # Warm yellow
        self.red_color = "#f38ba8"      # Warm red
        self.blue_color = "#89b4fa"     # Cool blue
        
        self.configure(background=self.bg_color)
        
        # Game State Variables
        self.secret_number = 0
        self.attempts = 0
        self.score = 100
        self.guess_history = []
        
        # Build UI layout
        self.create_widgets()
        
        # Start a new game session
        self.reset_game()

    def create_widgets(self):
        # Header / Title Block
        header_frame = tk.Frame(self, bg=self.bg_color, pady=15)
        header_frame.pack(fill="x")
        
        title_label = tk.Label(
            header_frame, 
            text="GUESS THE NUMBER", 
            font=("Arial", 20, "bold"), 
            bg=self.bg_color, 
            fg=self.accent_color
        )
        title_label.pack()
        
        subtitle_label = tk.Label(
            header_frame, 
            text="I'm thinking of a number between 1 and 100.", 
            font=("Arial", 10, "italic"), 
            bg=self.bg_color, 
            fg=self.fg_color
        )
        subtitle_label.pack()

        # Main Interface Card Container
        self.main_card = tk.Frame(self, bg=self.card_color, bd=0, padx=20, pady=20)
        self.main_card.pack(padx=20, pady=10, fill="both", expand=True)

        # Left Column: Input and Actions
        input_frame = tk.Frame(self.main_card, bg=self.card_color)
        input_frame.pack(fill="x", pady=10)
        
        entry_label = tk.Label(
            input_frame, 
            text="Enter your guess:", 
            font=("Arial", 12, "bold"), 
            bg=self.card_color, 
            fg=self.fg_color
        )
        entry_label.pack(anchor="w", pady=5)
        
        # Stylized Entry widget
        self.guess_entry = tk.Entry(
            input_frame, 
            font=("Arial", 16, "bold"), 
            bg=self.bg_color, 
            fg=self.fg_color, 
            insertbackground=self.fg_color, 
            bd=2, 
            relief="flat", 
            justify="center"
        )
        self.guess_entry.pack(fill="x", ipady=6, pady=5)
        self.guess_entry.bind("<Return>", lambda event: self.submit_guess())
        self.guess_entry.focus()
        
        # Submit Button
        self.submit_btn = tk.Button(
            input_frame, 
            text="Submit Guess", 
            font=("Arial", 12, "bold"), 
            bg=self.accent_color, 
            fg=self.bg_color, 
            activebackground=self.fg_color, 
            activeforeground=self.bg_color, 
            relief="flat", 
            cursor="hand2", 
            command=self.submit_guess
        )
        self.submit_btn.pack(fill="x", pady=10)

        # Middle Section: Live Feedback Display Card
        self.feedback_card = tk.Frame(self.main_card, bg=self.bg_color, pady=12, padx=10)
        self.feedback_card.pack(fill="x", pady=10)
        
        self.feedback_title = tk.Label(
            self.feedback_card, 
            text="Waiting for your first guess...", 
            font=("Arial", 11, "bold"), 
            bg=self.bg_color, 
            fg=self.fg_color,
            wraplength=400
        )
        self.feedback_title.pack()
        
        self.temp_badge = tk.Label(
            self.feedback_card, 
            text="-", 
            font=("Arial", 10, "bold"), 
            bg=self.card_color, 
            fg=self.fg_color, 
            padx=10, 
            pady=3
        )
        self.temp_badge.pack(pady=5)

        # Stats Row (Score & Attempts)
        stats_frame = tk.Frame(self.main_card, bg=self.card_color)
        stats_frame.pack(fill="x", pady=5)
        
        self.score_label = tk.Label(
            stats_frame, 
            text="Score: 100", 
            font=("Arial", 11, "bold"), 
            bg=self.card_color, 
            fg=self.green_color
        )
        self.score_label.pack(side="left", padx=5)
        
        self.attempts_label = tk.Label(
            stats_frame, 
            text="Attempts: 0", 
            font=("Arial", 11, "bold"), 
            bg=self.card_color, 
            fg=self.fg_color
        )
        self.attempts_label.pack(side="right", padx=5)

        # Bottom Section: History list
        history_title = tk.Label(
            self.main_card, 
            text="Guess History:", 
            font=("Arial", 10, "bold"), 
            bg=self.card_color, 
            fg=self.fg_color
        )
        history_title.pack(anchor="w", pady=(10, 2))
        
        # Scrollable listbox frame
        list_frame = tk.Frame(self.main_card, bg=self.bg_color)
        list_frame.pack(fill="both", expand=True, pady=5)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.history_listbox = tk.Listbox(
            list_frame, 
            font=("Consolas", 10), 
            bg=self.bg_color, 
            fg=self.fg_color, 
            selectbackground=self.accent_color,
            selectforeground=self.bg_color, 
            bd=0, 
            highlightthickness=0, 
            yscrollcommand=scrollbar.set
        )
        self.history_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.history_listbox.yview)

        # Footer Actions
        footer_frame = tk.Frame(self, bg=self.bg_color, pady=15)
        footer_frame.pack(fill="x")
        
        new_game_btn = tk.Button(
            footer_frame, 
            text="↻ Restart Game", 
            font=("Arial", 11, "bold"), 
            bg="#313244", 
            fg=self.fg_color, 
            activebackground=self.accent_color, 
            activeforeground=self.bg_color, 
            relief="flat", 
            cursor="hand2", 
            command=self.reset_game
        )
        new_game_btn.pack(side="left", padx=20)
        
        exit_btn = tk.Button(
            footer_frame, 
            text="✕ Exit", 
            font=("Arial", 11, "bold"), 
            bg="#313244", 
            fg=self.red_color, 
            activebackground=self.red_color, 
            activeforeground=self.bg_color, 
            relief="flat", 
            cursor="hand2", 
            command=self.destroy
        )
        exit_btn.pack(side="right", padx=20)

    def reset_game(self):
        """Resets the game state and UI widgets."""
        self.secret_number = random.randint(1, 100)
        self.attempts = 0
        self.score = 100
        self.guess_history.clear()
        
        self.guess_entry.delete(0, tk.END)
        self.guess_entry.config(state="normal")
        self.submit_btn.config(state="normal", bg=self.accent_color)
        
        self.score_label.config(text="Score: 100", fg=self.green_color)
        self.attempts_label.config(text="Attempts: 0", fg=self.fg_color)
        
        self.feedback_title.config(text="I've selected a new number. Enter your first guess!", fg=self.fg_color)
        self.temp_badge.config(text="NEW GAME", bg="#313244", fg=self.fg_color)
        
        self.history_listbox.delete(0, tk.END)
        self.guess_entry.focus()

    def submit_guess(self):
        """Processes the user's guess and updates UI."""
        guess_str = self.guess_entry.get().strip()
        self.guess_entry.delete(0, tk.END)
        
        if not guess_str:
            return
            
        try:
            guess = int(guess_str)
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid integer between 1 and 100.")
            return
            
        if guess < 1 or guess > 100:
            messagebox.showerror("Out of Bounds", "Your guess must be between 1 and 100.")
            return

        self.attempts += 1
        
        # Calculate temperature (difference)
        diff = abs(self.secret_number - guess)
        
        # Determine hint
        if guess < self.secret_number:
            direction = "Too Low"
        elif guess > self.secret_number:
            direction = "Too High"
        else:
            direction = "Correct!"

        # Determine temperature description and colors
        if diff == 0:
            temp_desc = "Boiling Hot! (Correct)"
            badge_color = self.green_color
            fg_badge = self.bg_color
            status_text = f"Congratulations! The number was indeed {self.secret_number}."
        elif diff <= 3:
            temp_desc = "Boiling Hot"
            badge_color = self.red_color
            fg_badge = self.bg_color
            status_text = f"{direction}! You are extremely close!"
        elif diff <= 7:
            temp_desc = "Very Warm"
            badge_color = self.yellow_color
            fg_badge = self.bg_color
            status_text = f"{direction}! You're getting hot!"
        elif diff <= 15:
            temp_desc = "Mildly Warm"
            badge_color = "#fab387"  # Peach orange
            fg_badge = self.bg_color
            status_text = f"{direction}! Warmish, but not there yet."
        elif diff <= 25:
            temp_desc = "Chilly"
            badge_color = self.blue_color
            fg_badge = self.bg_color
            status_text = f"{direction}! Cool temperature."
        else:
            temp_desc = "Freezing Cold"
            badge_color = "#74c7ec"  # Ice blue
            fg_badge = self.bg_color
            status_text = f"{direction}! You are far away."

        # Update scoring
        if diff > 0:
            # Deduct points proportional to distance and attempts
            deduction = max(2, min(10, diff // 2))
            self.score = max(0, self.score - deduction)
        
        # Update UI labels
        self.attempts_label.config(text=f"Attempts: {self.attempts}")
        
        if self.score > 70:
            score_fg = self.green_color
        elif self.score > 40:
            score_fg = self.yellow_color
        else:
            score_fg = self.red_color
            
        self.score_label.config(text=f"Score: {self.score}", fg=score_fg)
        self.feedback_title.config(text=status_text, fg=badge_color if diff > 0 else self.green_color)
        self.temp_badge.config(text=temp_desc.upper(), bg=badge_color, fg=fg_badge)
        
        # Add to history listbox
        history_item = f"#{self.attempts:02d} | Guess: {guess:3d} | {direction:<8} | {temp_desc}"
        self.history_listbox.insert(0, history_item)
        
        # If correct, end game flow
        if diff == 0:
            self.guess_entry.config(state="disabled")
            self.submit_btn.config(state="disabled", bg="#313244")
            messagebox.showinfo(
                "Victory!", 
                f"You guessed the number in {self.attempts} attempts!\nFinal Score: {self.score}"
            )


if __name__ == "__main__":
    app = GuessingGameGUI()
    app.mainloop()
