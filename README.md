# Gamepad Macro Tool

Windows gamepad macro tool with configurable bindings. Map any gamepad button to a custom button sequence — all defined in a JSON config file.

## How it works

```
Physical Xbox Controller
        |
   pygame reads input
        |
   [Is this a trigger button?]
        |                        |
       Yes                       No
        |                        |
   Play macro sequence      Forward input
   on virtual controller    to virtual controller
        |                        |
        +--------> Virtual Xbox 360 Controller <-------+
                          |
                     Game reads this
```

- All gamepad input is forwarded to a virtual Xbox 360 controller
- Configured trigger buttons play their macro sequence instead of forwarding
- Multiple bindings supported — each with its own trigger, sequence, and timing
- Settings adjustable in GUI, sequences edited in `config.json`

## Prerequisites

### 1. Install ViGEmBus driver

Required for creating virtual controllers.

**Download:** https://github.com/nefarius/ViGEmBus/releases

Run `ViGEmBus_Setup_x64.msi` and **reboot**.

### 2. Install Python packages

```bash
pip install -r requirements.txt
```

## Usage

```bash
python gamepad_macro.py
```

1. Connect your Xbox controller
2. Run the program — GUI window appears
3. Click **"Set Trigger"** on any binding, then press a button on your gamepad
4. Edit `config.json` to customize the macro sequences (see below)
5. In-game, press the trigger button to fire the corresponding macro

## Configuration

All bindings are defined in `config.json` (auto-created next to the script):

```json
{
  "bindings": [
    {
      "name": "Combo 1",
      "trigger_button": null,
      "sequence": ["X", "A", "RB", "LB", "RT", "LT"],
      "interval_ms": 70,
      "press_duration_ms": 40,
      "cooldown_ms": 350
    },
    {
      "name": "Dodge + Attack",
      "trigger_button": 5,
      "sequence": ["B", "A", "A", "X"],
      "interval_ms": 50,
      "press_duration_ms": 30,
      "cooldown_ms": 300
    }
  ]
}
```

### Binding fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name in GUI |
| `trigger_button` | int/null | pygame button index, set via GUI or manually |
| `sequence` | array | Button names to play in order |
| `interval_ms` | int | Delay between each button in sequence (default: 70) |
| `press_duration_ms` | int | How long each button is held (default: 40) |
| `cooldown_ms` | int | Min gap between two triggers of this binding (default: 350) |

### Available sequence buttons

| Button | Name |
|--------|------|
| `A` `B` `X` `Y` | Face buttons |
| `LB` `RB` | Bumpers |
| `LT` `RT` | Triggers (as full press) |
| `BACK` `START` | Menu buttons |
| `LS` `RS` | Stick clicks |
| `DPAD_UP` `DPAD_DOWN` `DPAD_LEFT` `DPAD_RIGHT` | D-Pad |

### pygame button index reference

| Index | Button |
|-------|--------|
| 0 | A |
| 1 | B |
| 2 | X |
| 3 | Y |
| 4 | LB |
| 5 | RB |
| 6 | BACK |
| 7 | START |
| 8 | LS |
| 9 | RS |
| 10 | Guide |

## GUI controls

- **Set Trigger**: Click, then press any gamepad button to bind it
- **+ Add Binding**: Creates a new binding with default settings
- **Delete**: Removes a binding
- **Interval/Hold sliders**: Adjust timing per binding
- **Sequences**: Edit directly in `config.json`, then restart the program

## GitHub Actions

Push a tag like `v1.0.0` to trigger the build workflow:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow builds `GamepadMacro.exe` with PyInstaller and creates a GitHub Release with the EXE and `config.json` attached.

You can also trigger it manually from the **Actions** tab.

## Build locally

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name GamepadMacro gamepad_macro.py
```

Output: `dist/GamepadMacro.exe` — copy `config.json` next to it.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| ViGEmBus driver not found | Install driver from link above, reboot |
| No gamepad detected | Connect Xbox controller before launching |
| Game ignores virtual controller | Run as Administrator |
| Macro too fast/slow | Adjust `interval_ms` and `press_duration_ms` in config |
| Macro fires multiple times | Increase `cooldown_ms` for that binding |
