import sys
import time
import webbrowser
import tkinter as tk
from tkinter import Menu, messagebox

# Catch ModuleNotFoundError for critical external dependencies
missing_modules = []
try:
    import pyautogui
except ModuleNotFoundError:
    missing_modules.append("pyautogui")

try:
    import keyboard
except ModuleNotFoundError:
    missing_modules.append("keyboard")

if missing_modules:
    # Show user-friendly GUI warning and exit safely
    root = tk.Tk()
    root.withdraw()
    modules_str = ", ".join(missing_modules)
    messagebox.showerror(
        "Missing Dependencies",
        f"Required libraries are missing: {modules_str}\n\n"
        f"Please install them via terminal:\npip install {' '.join(missing_modules)}"
    )
    sys.exit(1)

import threading


class Coordinates:
    replayBtn = (100, 350)


class YourGUI(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.is_clicking = False
        self.clicking_thread = None

        # Grid config
        self.configure(background="#ebdbff")

        # Enter X field and label (aligned correctly)
        tk.Label(self, text="ENTER X:", background="#ebdbff").grid(row=0, column=0, padx=5, pady=5)
        self.inputX = tk.Entry(self)
        self.inputX.grid(row=0, column=1, padx=5, pady=5)

        # Enter Y field and label (aligned correctly)
        tk.Label(self, text="ENTER Y:", background="#ebdbff").grid(row=0, column=2, padx=5, pady=5)
        self.inputY = tk.Entry(self)
        self.inputY.grid(row=0, column=3, padx=5, pady=5)

        # Keyboard hotkey stopping controls
        tk.Label(self, text="Keyboard key to stop clicking:", background="#ebdbff").grid(row=1, column=2, padx=5, pady=5)
        self.inputhotkey = tk.Entry(self)
        self.inputhotkey.grid(row=1, column=3, padx=5, pady=5)
        self.inputhotkey.insert(0, "q")  # Default stop key

        # Start/Stop Button
        self.start_btn = tk.Button(self, text="start", fg='green', font=('Arial', 10, 'bold'), command=self.toggle_clicking)
        self.start_btn.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        # Set Hotkey Button
        tk.Button(self, text="   SET   ", fg='#cc8400', font=('Arial', 9, 'bold'), command=self.do_hotkey).grid(row=3, column=3, padx=5, pady=5, sticky="ew")

        # Exit button
        tk.Button(self, text="exit!", fg='red', font=('Arial', 10, 'bold'), command=self.EXITME).grid(row=4, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        # About button
        tk.Button(self, text="ABOUT", command=self.open_about_web).grid(row=4, column=2, columnspan=2, padx=5, pady=5, sticky="ew")

        # Menu Bar Setup
        menu = Menu(self)
        new_item = Menu(menu, tearoff=0)
        new_item.add_command(label='ABOUT', command=self.open_about_web)
        new_item.add_command(label='GITHUB PAGE', command=self.open_github_web)
        new_item.add_command(label='CONTACT', command=self.show_contact)
        new_item.add_separator()
        new_item.add_command(label='START/STOP', command=self.toggle_clicking)
        new_item.add_command(label='EXIT', command=self.EXITME)
        menu.add_cascade(label='Menu', menu=new_item)

        new_item2 = Menu(menu, tearoff=0)
        new_item2.add_command(label='Tutorial', command=self.open_tutorial_web)
        menu.add_cascade(label='Help', menu=new_item2)
        
        self.config(menu=menu)

    def open_about_web(self):
        webbrowser.open_new(r"https://kai9987kai.github.io/AutoClicker.html")

    def open_github_web(self):
        webbrowser.open_new(r"https://github.com/kai9987kai/AutoClicker")

    def open_tutorial_web(self):
        webbrowser.open_new(r"https://autoclicker.webstarts.com/index.html?r=20181122215206")

    def show_contact(self):
        messagebox.showinfo('CONTACT', 'Email: kai9987kai@gmail.com')

    def EXITME(self):
        self.is_clicking = False
        self.destroy()
        sys.exit(0)

    def toggle_clicking(self):
        if self.is_clicking:
            self.is_clicking = False
            self.start_btn.config(text="start", fg="green")
        else:
            y = self.inputY.get()
            x = self.inputX.get()
            try:
                x_val = int(x)
                y_val = int(y)
            except ValueError:
                messagebox.showerror('Invalid point', 'Coordinates must be valid integers.')
                return

            self.is_clicking = True
            self.start_btn.config(text="STOP", fg="red")

            # Spawn a background thread to prevent UI freezing
            self.clicking_thread = threading.Thread(
                target=self.click_loop, args=(x_val, y_val), daemon=True
            )
            self.clicking_thread.start()

    def click_loop(self, x, y):
        stop_key = self.inputhotkey.get().strip()
        while self.is_clicking:
            pyautogui.click(x, y)
            time.sleep(0.05)  # Add micro-sleep to prevent 100% CPU lock

            # Check if stop key pressed
            if stop_key and keyboard.is_pressed(stop_key):
                break

        # Safely reset the GUI state from the main thread
        self.is_clicking = False
        self.after(0, self.reset_gui_state)

    def reset_gui_state(self):
        self.start_btn.config(text="start", fg="green")

    def do_hotkey(self):
        hotkey = self.inputhotkey.get().strip()
        if hotkey:
            messagebox.showinfo("Hotkey Set", f"Stop hotkey has been successfully set to: '{hotkey}'")
        else:
            messagebox.showwarning("Empty Hotkey", "Please enter a key code (e.g. 'q') to set the hotkey.")


if __name__ == '__main__':
    your_gui = YourGUI()
    your_gui.title('AutoClicker')
    try:
        your_gui.iconbitmap('favicon.ico')
    except Exception:
        pass  # Ignore missing icon issues
    your_gui.resizable(False, False)
    your_gui.mainloop()
