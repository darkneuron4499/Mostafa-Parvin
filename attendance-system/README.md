# 🏪 Shop Attendance System

**Fingerprint-based employee attendance & hourly payroll for small shops** — a Python/Tkinter desktop app paired with a **Rubika bot** for live alerts, reports and salary.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

🇮🇷 [نسخه فارسی](README.fa.md)

---

## ✨ Features

- ☝️ **Fingerprint attendance** — employees just touch the sensor; no cards, no typing.
- ⏸ **Pause / resume salary during the day** — scan once to stop the clock (errand, break, end of shift), scan again to continue.
- 🔌 **Plug-and-play device detection** — finds the serial port and baud rate by itself, and reconnects automatically when the device is re-plugged.
- 🤖 **Rubika bot with button menus** (Telegram-style keyboards) — live scan alerts, who's in right now, daily/monthly reports, salaries.
- 💰 **Salary lives only in the bot** — the desktop app never shows pay; hourly wages are edited from Rubika too.
- 📱 **Restricted to two phones** — pairing is done with a one-time code shown only on the PC.
- 🎨 **Colorful dashboard** — live stats, employee cards with status, event log, Jalali (Persian) date & clock.
- 🗄 **Zero setup database** — everything is stored in a local SQLite file.

## 🔄 How a scan works

| Employee's state | Scan result |
|---|---|
| Not here yet today | 🟢 **Check-in** — salary starts |
| Working | ⏸ **Salary paused** (errand / end of day) |
| Paused | ▶️ **Salary resumes** |

If someone forgets the last scan, their session is closed automatically at a configurable time (default `23:59`) and the admins are notified.

## 🧰 Requirements

- Python **3.8+** (Tkinter is included with the Windows installer; on Debian/Ubuntu: `sudo apt install python3-tk`)
- A serial fingerprint module from the **R307 / AS608 / ZFM-20** family (USB-TTL or direct serial)
- A Rubika account and a bot token

> Other fingerprint devices (ZKTeco, HID/USB readers, …) use different protocols and are **not** supported yet.

## 🚀 Installation

```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
pip install -r requirements.txt
python attendance_app.py
```

## ⚙️ Configuration

On the first run the app creates `config.json` next to the script. You can also start from the template:

```bash
cp config.example.json config.json
```

| Key | Meaning |
|---|---|
| `token` | Your Rubika bot token. Alternatively set the `RUBIKA_BOT_TOKEN` environment variable. |
| `port` / `baud` | `"auto"` (default) or a fixed value such as `"COM8"` / `57600`. |
| `auto_close` | Time (`HH:MM`) when still-open sessions are closed automatically. |
| `admins` | Managed by the app — chat IDs of the (max. two) paired phones. |

⚠️ **Never commit `config.json` or `attendance.db`** — they contain your bot token and payroll data. Both are already in `.gitignore`.

### Create the Rubika bot
1. In Rubika, talk to Rubika's BotFather and create a new bot.
2. Copy the token into `config.json` (or `RUBIKA_BOT_TOKEN`).
3. Start the app.

## 📖 Usage

1. **Connect the device** — leave port and speed on *Auto*. If it doesn't connect, press **🔍 Diagnose**; it logs every port and the raw device replies.
2. **Add employees** — **➕ Add employee**, type the name, then place the same finger twice.
3. **Pair your phone** — press **➕ Add phone** in the *Rubika bot* card, open the bot in Rubika, press *Start* and send the 6-digit code. Repeat for a second phone if needed.
4. **Set wages** — in Rubika: `👥 Employees` → pick a person → `✏️ Edit wage`, then send the hourly rate as a number.

### Bot menu

| Button | What it does |
|---|---|
| 🟢 حاضرین | Who is working / paused / not here yet |
| 📊 گزارش امروز | Today's timeline per employee |
| 📅 گزارش این ماه | Monthly attendance summary |
| 💰 حقوق این ماه / ⏮ حقوق ماه قبل | Salaries with totals |
| 👥 کارمندان | Per-employee report, salary and wage editing |

## 💰 How salary is calculated

`salary = total hours worked × hourly wage`, summed over all work sessions in the (Jalali) month. Paused time is not paid.

> ℹ️ The wage is a single value per employee, so changing it re-prices the **whole current month**, including days before the change.

## 🗂 Project structure

```
attendance_app.py     # the whole app: device driver, SQLite, bot, GUI
requirements.txt
config.example.json
```

## 🛠 Troubleshooting

- **Device not found** → check Device Manager → *Ports (COM & LPT)*; install the USB-TTL driver (CH340 / CP2102 / FTDI); close other programs that hold the port; press **🔍 Diagnose**.
- **Bot silent** → the token is wrong/missing (the status chip turns red) or the PC is offline.
- **"Access denied" for a new phone** → both slots are used; remove one phone first.

## 🗺 Roadmap / known limitations

- Wage history (apply a new wage only from the change date)
- Fixed monthly salaries, overtime, deductions
- Support for more fingerprint devices

## 📄 License

[MIT](LICENSE)

---

<p align="center">✦ Made by <b>Mostafa Parvin</b> ✦</p>
