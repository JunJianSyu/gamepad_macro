"""
Gamepad Macro Tool for Windows
Reads physical Xbox gamepad via pygame, creates a virtual Xbox 360 controller
via vgamepad, forwards all input. Configurable macro bindings: each binding
maps a trigger (any button OR the LT/RT triggers) to a custom button sequence.

Requirements:
    - ViGEmBus driver (https://github.com/nefarius/ViGEmBus/releases)
    - Python: pygame, vgamepad
"""

from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Optional, Dict

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

def _check_vgamepad():
    try:
        import vgamepad as vg
        _test = vg.VX360Gamepad()
        del _test
        return vg
    except ImportError:
        raise SystemExit("[ERROR] vgamepad not installed.\nRun: pip install vgamepad")
    except Exception as e:
        raise SystemExit(
            f"[ERROR] ViGEmBus driver not found.\n"
            f"Detail: {e}\n"
            f"Download: https://github.com/nefarius/ViGEmBus/releases\n"
            f"Install and reboot, then retry."
        )


def _check_pygame():
    try:
        import pygame
    except ImportError:
        raise SystemExit("[ERROR] pygame not installed.\nRun: pip install pygame")
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        raise SystemExit("[ERROR] No gamepad detected.\nConnect an Xbox controller.")
    return pygame


# ---------------------------------------------------------------------------
# Button name constants
# ---------------------------------------------------------------------------

# pygame SDL button index -> name (Xbox standard layout)
PYGAME_BTN_NAMES: Dict[int, str] = {
    0: "A", 1: "B", 2: "X", 3: "Y",
    4: "LB", 5: "RB", 6: "BACK", 7: "START",
    8: "LS", 9: "RS", 10: "GUIDE",
}
# Reverse map: name -> pygame button index
BTN_NAME_TO_INDEX: Dict[str, int] = {v: k for k, v in PYGAME_BTN_NAMES.items()}

# Axis indices (Xbox via pygame/SDL on Windows)
AXIS_LT = 4   # Left trigger  (-1 = released, +1 = pressed)
AXIS_RT = 5   # Right trigger
# Trigger name -> axis index. LT/RT are analog axes, not digital buttons.
AXIS_TRIGGERS: Dict[str, int] = {"LT": AXIS_LT, "RT": AXIS_RT}
# Threshold on normalized [0,1] axis value above which the trigger counts as pressed.
AXIS_PRESS_THRESHOLD = 0.5

# All valid button names for macro sequences
VALID_SEQUENCE_BUTTONS = [
    "A", "B", "X", "Y",
    "LB", "RB", "BACK", "START",
    "LS", "RS",
    "RT", "LT",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
]

# Map readable name -> vgamepad XUSB_BUTTON attribute name
# RT and LT are triggers (handled as axis values, not buttons)
_VG_BTN_ATTR: Dict[str, str] = {
    "A":          "XUSB_GAMEPAD_A",
    "B":          "XUSB_GAMEPAD_B",
    "X":          "XUSB_GAMEPAD_X",
    "Y":          "XUSB_GAMEPAD_Y",
    "LB":         "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RB":         "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "BACK":       "XUSB_GAMEPAD_BACK",
    "START":      "XUSB_GAMEPAD_START",
    "LS":         "XUSB_GAMEPAD_LEFT_THUMB",
    "RS":         "XUSB_GAMEPAD_RIGHT_THUMB",
    "DPAD_UP":    "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN":  "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT":  "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
    "GUIDE":      "XUSB_GAMEPAD_GUIDE",
}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.json"

_DEFAULT_BINDING = {
    "name": "Default Macro",
    "trigger": None,              # button/trigger NAME (e.g. "LT", "RB", "A"); None = unset
    "sequence": ["X", "A", "RB", "LB", "RT", "LT"],
    "interval_ms": 70,            # delay between buttons in sequence
    "press_duration_ms": 40,      # how long each button is held
    "cooldown_ms": 350,           # min gap between two triggers of same macro
}

DEFAULT_CONFIG = {
    "bindings": [dict(_DEFAULT_BINDING)],
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        # Ensure bindings is a list
        if "bindings" not in saved or not isinstance(saved["bindings"], list):
            saved["bindings"] = [dict(_DEFAULT_BINDING)]
        for b in saved["bindings"]:
            # Backward compat: migrate old integer "trigger_button" to name "trigger"
            if "trigger" not in b and "trigger_button" in b:
                idx = b.pop("trigger_button")
                b["trigger"] = PYGAME_BTN_NAMES.get(idx) if idx is not None else None
            # Merge defaults for missing keys
            for k, v in _DEFAULT_BINDING.items():
                b.setdefault(k, v)
            # Validate sequence: warn about unknown button names
            if not isinstance(b["sequence"], list):
                print(f"[WARN] Binding '{b['name']}' has non-list sequence, resetting to default.")
                b["sequence"] = list(_DEFAULT_BINDING["sequence"])
            else:
                invalid = [x for x in b["sequence"] if x not in VALID_SEQUENCE_BUTTONS]
                if invalid:
                    print(
                        f"[WARN] Binding '{b['name']}' has unknown button names in sequence "
                        f"(will be skipped): {invalid}. "
                        f"Valid names: {VALID_SEQUENCE_BUTTONS}"
                    )
        return saved
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# MacroPad
# ---------------------------------------------------------------------------

class MacroPad:

    def __init__(self):
        self.vg = _check_vgamepad()
        self.pg = _check_pygame()

        self.config = load_config()

        self.joy = self.pg.joystick.Joystick(0)
        self.joy.init()

        self.vpad = self.vg.VX360Gamepad()

        self._running = True
        self._selecting_index: Optional[int] = None   # which binding is being configured
        # Per-binding runtime state
        self._bstate: Dict[int, dict] = {}
        for i in range(len(self.config["bindings"])):
            self._bstate[i] = {
                "pressed_prev": False,
                "last_time": 0.0,
                "executing": False,
                "just_finished_time": 0.0,
            }

        self._build_gui()
        self._render_bindings()

        self._t = threading.Thread(target=self._input_loop, daemon=True)
        self._t.start()
        self._tick()

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------

    def _build_gui(self):
        self.root = tk.Tk()
        self.root.title("Gamepad Macro Tool")
        self.root.geometry("520x640")
        self.root.resizable(False, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        BG = "#1e1e2e"; FG = "#cdd6f4"; ACCENT = "#89b4fa"
        self.root.configure(bg=BG)
        self._BG = BG; self._FG = FG; self._ACCENT = ACCENT

        tk.Label(
            self.root, text="Gamepad Macro Tool",
            font=("Segoe UI", 16, "bold"), bg=BG, fg=ACCENT
        ).pack(pady=(12, 2))

        tk.Label(
            self.root, text=f"Controller: {self.joy.get_name()}",
            font=("Segoe UI", 9), bg=BG, fg="#a6adc8"
        ).pack()

        self._status = tk.Label(
            self.root, text="Ready", font=("Segoe UI", 9), bg=BG, fg="#a6e3a1"
        )
        self._status.pack(pady=(4, 8))

        # Scrollable bindings area
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=10, pady=4)

        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0, height=360)
        self._scrollbar = tk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._bframe = tk.Frame(self._canvas, bg=BG)
        self._bframe_window = self._canvas.create_window((0, 0), window=self._bframe, anchor="nw")
        self._bframe.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._bframe_window, width=e.width))

        tk.Button(
            self.root, text="+ Add Binding",
            font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
            command=self._add_binding, width=20
        ).pack(pady=(6, 4))

        tk.Label(
            self.root,
            text=f"Config: {CONFIG_PATH.name}  (edit sequences in file, restart to reload)",
            font=("Segoe UI", 8), bg=BG, fg="#6c7086"
        ).pack(pady=(0, 8))

    def _set_status(self, text: str, color: str = "#a6e3a1"):
        self._status.config(text=text, fg=color)

    def _render_bindings(self):
        """Rebuild the bindings UI from current config."""
        for w in self._bframe.winfo_children():
            w.destroy()

        BG = self._BG; FG = self._FG

        for idx, binding in enumerate(self.config["bindings"]):
            card = tk.Frame(self._bframe, bg="#313244", bd=1, relief="solid")
            card.pack(fill="x", padx=4, pady=4)

            header = tk.Frame(card, bg="#313244")
            header.pack(fill="x", padx=8, pady=(6, 0))

            tk.Label(
                header, text=binding["name"],
                font=("Segoe UI", 10, "bold"), bg="#313244", fg=FG
            ).pack(side="left")

            tk.Button(
                header, text="Delete", font=("Segoe UI", 8),
                bg="#f38ba8", fg="#1e1e2e",
                command=lambda i=idx: self._delete_binding(i)
            ).pack(side="right")

            trig_row = tk.Frame(card, bg="#313244")
            trig_row.pack(fill="x", padx=8, pady=(4, 0))

            trigger_name = binding["trigger"] if binding["trigger"] is not None else "Not Set"
            tk.Label(
                trig_row, text=f"Trigger:  {trigger_name}",
                font=("Segoe UI", 10), bg="#313244", fg="#f9e2af"
            ).pack(side="left")

            tk.Button(
                trig_row, text="Set Trigger", font=("Segoe UI", 8),
                bg="#89b4fa", fg="#1e1e2e",
                command=lambda i=idx: self._start_set_trigger(i)
            ).pack(side="right")

            seq_text = " -> ".join(binding["sequence"])
            tk.Label(
                card, text=seq_text,
                font=("Consolas", 9), bg="#313244", fg="#a6adc8",
                wraplength=460, justify="left"
            ).pack(fill="x", padx=8, pady=(2, 0))

            timing = tk.Frame(card, bg="#313244")
            timing.pack(fill="x", padx=8, pady=(4, 6))

            interval_lbl = tk.Label(
                timing, text=f"Interval: {binding['interval_ms']}ms",
                font=("Segoe UI", 8), bg="#313244", fg="#a6adc8"
            )
            interval_lbl.grid(row=0, column=0, sticky="w")
            ivar = tk.IntVar(value=binding["interval_ms"])
            tk.Scale(
                timing, from_=10, to=200, orient="horizontal",
                variable=ivar, bg="#313244", fg=FG, troughcolor="#45475a",
                highlightthickness=0, length=160, showvalue=False,
                command=lambda v, i=idx, lbl=interval_lbl: self._on_interval_change(i, v, lbl)
            ).grid(row=0, column=1, padx=(4, 12))

            press_lbl = tk.Label(
                timing, text=f"Hold: {binding['press_duration_ms']}ms",
                font=("Segoe UI", 8), bg="#313244", fg="#a6adc8"
            )
            press_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))
            pvar = tk.IntVar(value=binding["press_duration_ms"])
            tk.Scale(
                timing, from_=10, to=150, orient="horizontal",
                variable=pvar, bg="#313244", fg=FG, troughcolor="#45475a",
                highlightthickness=0, length=160, showvalue=False,
                command=lambda v, i=idx, lbl=press_lbl: self._on_press_dur_change(i, v, lbl)
            ).grid(row=1, column=1, padx=(4, 12), pady=(2, 0))

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        # Warn about duplicate triggers (隐患 1)
        trigger_counts: Dict[str, int] = {}
        for b in self.config["bindings"]:
            t = b["trigger"]
            if t is not None:
                trigger_counts[t] = trigger_counts.get(t, 0) + 1
        duplicates = [t for t, c in trigger_counts.items() if c > 1]
        if duplicates:
            dup_text = ", ".join(duplicates)
            print(f"[WARN] Multiple bindings share trigger(s): {dup_text}. All will fire simultaneously.")
            tk.Label(
                self._bframe,
                text=f"Warning: trigger(s) shared by multiple bindings: {dup_text}",
                font=("Segoe UI", 8, "bold"), bg="#313244", fg="#f38ba8",
                wraplength=460, justify="left"
            ).pack(fill="x", padx=4, pady=(4, 2))

    def _on_interval_change(self, idx: int, val, lbl):
        ms = int(float(val))
        self.config["bindings"][idx]["interval_ms"] = ms
        lbl.config(text=f"Interval: {ms}ms")

    def _on_press_dur_change(self, idx: int, val, lbl):
        ms = int(float(val))
        self.config["bindings"][idx]["press_duration_ms"] = ms
        lbl.config(text=f"Hold: {ms}ms")

    def _start_set_trigger(self, idx: int):
        self._selecting_index = idx
        name = self.config["bindings"][idx]["name"]
        self._set_status(f"Press a button or trigger for '{name}'...", "#f9e2af")

    def _finish_set_trigger(self, trigger_name: str):
        idx = self._selecting_index
        if idx is None:
            return
        self._selecting_index = None
        self.config["bindings"][idx]["trigger"] = trigger_name
        save_config(self.config)
        self._set_status(f"Trigger set: {trigger_name}", "#a6e3a1")
        self._render_bindings()

    def _add_binding(self):
        new_b = dict(_DEFAULT_BINDING)
        new_b["name"] = f"Macro {len(self.config['bindings']) + 1}"
        new_b["trigger"] = None
        self.config["bindings"].append(new_b)
        idx = len(self.config["bindings"]) - 1
        self._bstate[idx] = {
            "pressed_prev": False,
            "last_time": 0.0,
            "executing": False,
            "just_finished_time": 0.0,
        }
        save_config(self.config)
        self._render_bindings()

    def _delete_binding(self, idx: int):
        if len(self.config["bindings"]) <= 1:
            self._set_status("At least one binding is required.", "#f38ba8")
            return
        del self.config["bindings"][idx]
        self._bstate = {}
        for i in range(len(self.config["bindings"])):
            self._bstate[i] = {
                "pressed_prev": False,
                "last_time": 0.0,
                "executing": False,
                "just_finished_time": 0.0,
            }
        save_config(self.config)
        self._render_bindings()

    # ------------------------------------------------------------------
    # Trigger helpers
    # ------------------------------------------------------------------

    def _trigger_active(self, trigger_name: str) -> bool:
        """Return True if the given trigger (button name or LT/RT axis) is pressed."""
        if trigger_name in AXIS_TRIGGERS:
            ax = AXIS_TRIGGERS[trigger_name]
            if self.joy.get_numaxes() <= ax:
                return False
            val = (self.joy.get_axis(ax) + 1) / 2  # normalize [-1,1] -> [0,1]
            return val > AXIS_PRESS_THRESHOLD
        idx = BTN_NAME_TO_INDEX.get(trigger_name)
        if idx is None or idx >= self.joy.get_numbuttons():
            return False
        return bool(self.joy.get_button(idx))

    # ------------------------------------------------------------------
    # Input loop
    # ------------------------------------------------------------------

    def _input_loop(self):
        clock = self.pg.time.Clock()

        while self._running:
            # Flag: set True if any event in this frame was captured as a trigger selection.
            # When True, we must NOT forward inputs this frame — the captured press would
            # otherwise leak to the virtual gamepad (Bug 1 fix).
            trigger_selected = False

            for event in self.pg.event.get():
                if self._selecting_index is None:
                    continue
                # Capture a button press as the trigger
                if event.type == self.pg.JOYBUTTONDOWN:
                    name = PYGAME_BTN_NAMES.get(event.button, str(event.button))
                    self.root.after(0, lambda n=name: self._finish_set_trigger(n))
                    trigger_selected = True
                # Capture an LT/RT trigger pull as the trigger
                elif event.type == self.pg.JOYAXISMOTION and event.axis in AXIS_TRIGGERS.values():
                    norm = (event.value + 1) / 2
                    if norm > 0.7:  # require a firm pull to avoid noise
                        name = "LT" if event.axis == AXIS_LT else "RT"
                        self.root.after(0, lambda n=name: self._finish_set_trigger(n))
                        trigger_selected = True

            if trigger_selected:
                clock.tick(120)
                continue

            # Bug 2 fix: skip forwarding not only while a macro is executing,
            # but also for a short grace period (~15ms) after it finishes.
            # This closes the race window where the input loop could override
            # the macro's last button release before it observes executing=False.
            now = time.time()
            skip_forwarding = False
            for s in self._bstate.values():
                if s["executing"]:
                    skip_forwarding = True
                    break
                if s["just_finished_time"] > 0 and now - s["just_finished_time"] < 0.015:
                    skip_forwarding = True
                    break
            if skip_forwarding:
                clock.tick(120)
                continue

            if self.pg.joystick.get_count() == 0:
                self.root.after(0, lambda: self._set_status("Gamepad disconnected!", "#f38ba8"))
                time.sleep(0.5)
                continue

            self._forward_inputs()
            clock.tick(120)

    def _forward_inputs(self):
        vg = self.vg; vpad = self.vpad
        num_buttons = self.joy.get_numbuttons()

        # Resolve triggers, detect rising edges, fire macros, and collect
        # which physical inputs to suppress (so triggers don't leak to the game).
        suppressed_buttons = set()
        suppressed_axes = set()
        for bi, b in enumerate(self.config["bindings"]):
            trig = b["trigger"]
            if trig is None:
                continue
            state = self._bstate[bi]
            active = self._trigger_active(trig)
            if active and not state["pressed_prev"]:
                now = time.time()
                cooldown_s = b["cooldown_ms"] / 1000.0
                if now - state["last_time"] > cooldown_s:
                    state["last_time"] = now
                    threading.Thread(
                        target=self._execute_macro, args=(bi,), daemon=True
                    ).start()
            state["pressed_prev"] = active
            if trig in AXIS_TRIGGERS:
                suppressed_axes.add(AXIS_TRIGGERS[trig])
            elif trig in BTN_NAME_TO_INDEX:
                suppressed_buttons.add(BTN_NAME_TO_INDEX[trig])

        # -- Buttons --
        for btn_id in range(num_buttons):
            if btn_id in suppressed_buttons:
                continue  # this button is a macro trigger, don't forward it
            pressed = bool(self.joy.get_button(btn_id))
            btn_name = PYGAME_BTN_NAMES.get(btn_id)
            if btn_name and btn_name in _VG_BTN_ATTR:
                vg_btn = getattr(vg.XUSB_BUTTON, _VG_BTN_ATTR[btn_name])
                if pressed:
                    vpad.press_button(button=vg_btn)
                else:
                    vpad.release_button(button=vg_btn)

        # -- Trigger axes (suppress the one used as a macro trigger) --
        if self.joy.get_numaxes() > AXIS_RT:
            if AXIS_LT in suppressed_axes:
                vpad.left_trigger_float(value_float=0.0)
            else:
                lt = max(0.0, (self.joy.get_axis(AXIS_LT) + 1) / 2)
                vpad.left_trigger_float(value_float=lt)
            if AXIS_RT in suppressed_axes:
                vpad.right_trigger_float(value_float=0.0)
            else:
                rt = max(0.0, (self.joy.get_axis(AXIS_RT) + 1) / 2)
                vpad.right_trigger_float(value_float=rt)

        # -- Sticks --
        if self.joy.get_numaxes() >= 4:
            vpad.left_joystick_float(
                x_value_float=self.joy.get_axis(0),
                y_value_float=self.joy.get_axis(1),
            )
            vpad.right_joystick_float(
                x_value_float=self.joy.get_axis(2),
                y_value_float=self.joy.get_axis(3),
            )

        # -- D-Pad --
        if self.joy.get_numhats() > 0:
            hx, hy = self.joy.get_hat(0)
            if hy > 0:
                vpad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP)
            elif hy < 0:
                vpad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN)
            else:
                vpad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP)
                vpad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN)
            if hx > 0:
                vpad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT)
            elif hx < 0:
                vpad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT)
            else:
                vpad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT)
                vpad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT)

        vpad.update()

    # ------------------------------------------------------------------
    # Macro execution
    # ------------------------------------------------------------------

    def _execute_macro(self, binding_idx: int):
        state = self._bstate[binding_idx]
        if state["executing"]:
            return
        state["executing"] = True

        binding = self.config["bindings"][binding_idx]
        sequence = binding["sequence"]
        interval = binding["interval_ms"] / 1000.0
        duration = binding["press_duration_ms"] / 1000.0

        self.root.after(0, lambda: self._flash_macro(binding["name"]))

        vg = self.vg; vpad = self.vpad
        try:
            for btn_name in sequence:
                if not self._running:
                    break

                if btn_name == "RT":
                    vpad.right_trigger_float(value_float=1.0)
                    vpad.update()
                    time.sleep(duration)
                    vpad.right_trigger_float(value_float=0.0)
                    vpad.update()
                elif btn_name == "LT":
                    vpad.left_trigger_float(value_float=1.0)
                    vpad.update()
                    time.sleep(duration)
                    vpad.left_trigger_float(value_float=0.0)
                    vpad.update()
                elif btn_name in _VG_BTN_ATTR:
                    vg_btn = getattr(vg.XUSB_BUTTON, _VG_BTN_ATTR[btn_name])
                    vpad.press_button(button=vg_btn)
                    vpad.update()
                    time.sleep(duration)
                    vpad.release_button(button=vg_btn)
                    vpad.update()
                # Unknown names are silently skipped

                time.sleep(interval)
        finally:
            state["just_finished_time"] = time.time()
            state["executing"] = False

    def _flash_macro(self, name: str):
        self._set_status(f"MACRO: {name}", "#f9e2af")
        self.root.after(1200, lambda: self._set_status("Ready", "#a6e3a1"))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self):
        self._running = False
        save_config(self.config)
        try: self.joy.quit()
        except Exception: pass
        try:
            self.vpad.reset(); self.vpad.update()
        except Exception: pass
        self.pg.quit()
        self.root.destroy()

    def _tick(self):
        if self._running:
            self.root.after(16, self._tick)

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Gamepad Macro Tool starting...")
    print(f"Config: {CONFIG_PATH}")
    app = MacroPad()
    app.run()
