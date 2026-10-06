# Shadetree on Windows: start here

Shadetree shows a car's live engine data and trouble codes in your web browser, through an OBDLink EX adapter. It is **read-only**: it never clears codes, never changes a setting and never runs a test on the car. It only asks the car questions and shows the answers.

> Honest status: the Windows installer and launcher have **not been tested on a Windows machine yet** by the author. If something below does not match what you see, take a photo of the window and send it to Neil.

## What you need

1. A Windows 10 or 11 laptop with internet (only for the install and updates).
2. The OBDLink EX adapter and its USB cable.
3. A 1996 or newer car (US OBD-II).
4. Optional: a phone on the same Wi-Fi as the laptop, for the Handheld view.

## Install (about 10 minutes, once)

1. **Download.** Open https://github.com/iamneilroberts/shadetree-ai, press the green **Code** button, then **Download ZIP**. In your Downloads folder, right-click `shadetree-ai-main.zip`, choose **Extract All**, then **Extract**. Open the extracted folder, then the `shadetree-ai-main` folder inside it, then `install`.
   You only need the two files there, `install-windows.ps1` and `shadetree-start.bat`, kept together in one folder.
2. **Run the installer.** Right-click `install-windows.ps1` and choose **Run with PowerShell** (on Windows 11, choose **Show more options** first).
   - If a blue **Windows protected your PC** box appears: click **More info**, then **Run anyway**.
   - If PowerShell asks **Do you want to run ...? [D] Do not run [R] Run once**: type `R` and press Enter.
   - If the window flashes and closes, or says **running scripts is disabled**: open the Start menu, type `cmd`, open **Command Prompt**, and paste this line (change the path if you extracted somewhere else). Tip: in File Explorer, Shift + right-click the file and choose **Copy as path** to get the exact path.
     ```
     powershell -ExecutionPolicy Bypass -File "%USERPROFILE%\Downloads\shadetree-ai-main\shadetree-ai-main\install\install-windows.ps1"
     ```
3. **Wait for the five steps.** It finds Python (or installs Python 3.12 just for you; no administrator password needed), installs Shadetree, makes the folder `Documents\Shadetree`, looks for the adapter, and puts three icons on the Desktop. When it says **All done**, press Enter.
4. **Your Desktop now has:**
   - **Shadetree**: the car, through the adapter.
   - **Shadetree demo (no car)**: a simulated car, to practice.
   - **Shadetree with phone**: the car, and a link a phone can open (see [Using the Handheld view](#using-the-handheld-view)).

## Every time: read a car

1. Park the car. Plug the adapter into the car's diagnostic port (under the dashboard, driver's side) and its USB cable into the laptop.
2. Turn the ignition **on**. The engine can stay off; start it if you want idle readings.
3. Double-click **Shadetree**. A black window opens: **leave it open; closing it stops Shadetree.** It finds the adapter and opens the console in your web browser.
4. **What you should see:** a row of chips at the top (adapter, car, check engine, codes and a word such as **LIVE**), and the Dashboard's gauges filling in within a few seconds. On an older car the first connection can take up to a minute: when automatic search finds nothing, Shadetree tries each protocol in turn.
5. Press **Save run** to keep what was recorded. Sampling stops by itself after 10 minutes; press **Start sampling** to go again.
6. When you are done, close the black window.

No car nearby? Double-click **Shadetree demo (no car)** and press the **Demo** button on the page.

## What the words on the page mean

| You see | It means |
|---|---|
| **LIVE** | Reading the car right now. |
| **NOT SAMPLING** | The page is open but not reading. Press **Start sampling**. |
| **STOPPED** | Sampling stopped: the 10-minute auto-stop, or you pressed **Stop sampling**. |
| **ERROR**, "Adapter error" | The adapter or the car did not answer. See [Troubleshooting](#troubleshooting). |
| **NO LINK**, "Lost contact with the console server" | The black window was closed. Double-click **Shadetree** again. |
| "no adapter" (top chip) | No adapter has answered yet (normal in the demo and before the first reading). |
| "no answer from the car" (next to a reading) | The car did not reply to that one reading. Normal for some readings on some cars. |
| "not supported by this car" | The car says it does not have that reading. |
| "Codes not read" | The codes are read once when sampling starts; they have not been read yet. |

The "?" next to a reading explains what it measures. Colors (normal, watch, out of range) are general rules of thumb, not limits for your particular car. Code meanings are plain-words drafts that nobody has reviewed yet.

## Older cars: pin the protocol

If an older car still will not connect, tell Shadetree which protocol to use. Make a copy of the **Shadetree** icon (click it, Ctrl+C, Ctrl+V) and rename the copy, for example "Shadetree GM". Right-click the copy, choose **Properties**, and in **Target** add a space and the number at the very end, after `shadetree-start.bat`:

| Add | Protocol | Usually |
|---|---|---|
| `2` | J1850 VPW | GM cars and trucks |
| `1` | J1850 PWM | Ford |
| `3` | ISO 9141 | many older Chrysler, European and Asian cars |
| `5` | KWP (fast start) | some late-1990s and 2000s cars |
| `4` | KWP (slow start) | try if `5` does not work |

This is the same as `shadetree-ai console --protocol 2` on the command line. The **Shadetree with phone** icon takes a number the same way (its Target ends `phone`; add ` 2` after it).

## Using the Handheld view

The Handheld view is a one-column layout for a phone: the laptop stays plugged into the car and the phone goes wherever you are working.

1. Join the phone and the laptop to the **same Wi-Fi**, or connect the laptop to the phone's hotspot.
2. Double-click **Shadetree with phone**. The black window prints a **PHONE LINK** (`http://<laptop address>:8765/?t=...`) and copies it: paste it into a text or e-mail to yourself and open it on the phone, or type it in.
3. If Windows asks whether to allow Python through the firewall, tick **Private networks** and click **Allow**.
4. The phone opens the Handheld view by itself (any screen 600 px wide or less). On the laptop, click the **Handheld** tab, or add `#v5` to the end of the link.

What is on the Handheld screen:

- **Top line:** the check-engine lamp, the state word (LIVE, NOT SAMPLING, ...) and how many codes the car has.
- **Scenario dropdown:** the same scenarios as the Dashboard's tabs (General, Fuel trims, Cooling, Idle / misfire, Charging / electrical). Each picks the gauges shown.
- **Live / Codes buttons** at the bottom:
  - **Live:** the warning lamps, the scenario's gauges two across, and an **All readings (N)** button that jumps to the full table of every reading in the run.
  - **Codes:** stored, pending and permanent trouble codes (read once when sampling starts, not live), the freeze frame if there is one, and the readiness monitors. Older (pre-CAN) cars have no permanent codes to read, so those show as not read.
- **Menu** (top of the phone screen): the other views and the status buttons (**Start sampling**, **Save run**, **Replay...**).
- **Replay:** press **Replay...**, choose **My runs** (runs you saved) or a run file, then **Load**. A bar pinned to the bottom of the phone screen has restart, play/pause, speed (0.5x to 8x), a slider to jump around, and **Exit replay**. A replay never touches the adapter. (The **Examples** list may be empty on this install.)

Anyone on the same Wi-Fi who has the full link can watch the live data and start or stop sampling; nobody can clear codes or change the car. Use the phone link only on your own Wi-Fi or your phone's hotspot. Do not watch the phone while driving; let a passenger hold it.

## Where your files are saved, and privacy

Everything goes in `Documents\Shadetree`: saved runs in `runs`, the adapter's raw conversation in `transcripts`, and what Shadetree learned about each car in `profiles`. **Transcripts can contain your car's VIN** (its serial number): keep this folder private and do not post its files online. To share a run with Neil, send it to him directly.

## Updating

Close the Shadetree black window, then double-click **Update Shadetree** on the Desktop. It downloads the latest version and installs it over the old one. Run it as often as you like: it keeps your files, the saved adapter port and any number you added to an icon's Target. If the Update icon is missing, run the installer again the way you did the first time.

## Troubleshooting

| What happens | Likely cause | Fix |
|---|---|---|
| The installer window flashes and closes, or says "running scripts is disabled" | Windows blocks scripts by default | Use the Command Prompt line in Install, step 2. |
| Installer: "Python was installed but cannot be found yet" | Windows has not finished setting up Python | Restart the laptop and run the installer again. |
| Installer: "Something went wrong" while downloading | No internet, or a download was interrupted | Check the connection and run it again (it is safe to repeat). |
| Black window: "No OBDLink adapter found" | The adapter is not plugged in, or Windows is still setting up its driver | Plug it in, wait 30 seconds, press `R`. Still nothing: open **Device Manager**, **Ports (COM & LPT)**, note the adapter's `COM` number, and add it to the icon's Target like a protocol number, for example ` COM5` (it is remembered). |
| Black window: "Shadetree is not installed yet" | The installer has not finished | Run the installer (Install, step 2). |
| The browser did not open | Windows did not pass the link on | Copy the `console: http://127.0.0.1:...` line from the black window into the browser. |
| An error on the page or in the black window mentioning "Access is denied" for a COM port | Another program, or a second Shadetree black window, is using the adapter | Close the other OBD program or the other black window, then start again. Only run one Shadetree at a time. |
| Page shows ERROR or "Adapter error" | Ignition off, adapter loose, wrong port, or an older car that needs its protocol pinned | Check the ignition and the plug, then press **Start sampling**. Older car: pin the protocol (above). |
| Page shows "Lost contact with the console server" | The black window was closed | Double-click **Shadetree** again. |
| Sampling stopped after 10 minutes | The auto-stop | Press **Start sampling**. |
| Some readings say "no answer from the car" | That car does not answer those readings | Nothing to fix. |
| The phone cannot open the link | Not on the same network, the Wi-Fi is set to Public, a guest Wi-Fi keeps devices apart, or the firewall was refused | Put both on the same Wi-Fi, or use the phone's hotspot. In Windows **Settings**, **Network & internet**, **Wi-Fi**, choose the network and set it to **Private**. Firewall refused: **Windows Security**, **Firewall & network protection**, **Allow an app through firewall**, tick **Private** for Python. |
