# -*- coding: utf-8 -*-
"""
برنامه حضور و غیاب فروشگاه  —  Made by Mostafa Parvin
- دستگاه اثر انگشت سریالی (خانواده R307 / AS608 / ZFM-20)
- رابط گرافیکی رنگی (tkinter)
- ربات روبیکا با دکمه‌های انتخابی

منطق اثر انگشت در طول روز:
  اولین اسکن روز   ← ورود (شروع حقوق)
  اسکن در حال کار  ← توقف حقوق (کار بیرون یا پایان کار)
  اسکن در حال توقف ← ادامه حقوق

نصب:  pip install pyserial requests jdatetime
اجرا: python attendance_app.py
"""
import json
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from datetime import time as dtime
from tkinter import messagebox, simpledialog, ttk

import jdatetime
import requests
import serial
from serial.tools import list_ports

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
DB_FILE = os.path.join(BASE, "attendance.db")

DEFAULT_CONFIG = {
    "port": "auto",   # auto = پیدا کردن خودکار پورت
    "baud": "auto",   # auto = امتحان خودکار سرعت‌ها
    "last_port": None,
    "last_baud": None,
    "token": "",  # توکن ربات: در config.json یا متغیر محیطی RUBIKA_BOT_TOKEN
    "admins": [],  # حداکثر دو گوشی مجاز در روبیکا
    "auto_close": "23:59",  # پایان خودکار روز برای کسانی که اثر انگشت آخر را نزده‌اند
}

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


# ───────────────────────── تنظیمات ─────────────────────────
def load_cfg():
    c = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                c.update(json.load(f))
        except Exception:
            pass
    if not c.get("auto_mode_v2"):  # مهاجرت از نسخه قبلی: حالت خودکار فعال شود
        c["port"], c["baud"], c["auto_mode_v2"] = "auto", "auto", True
    c["admins"] = list(c.get("admins") or [])
    old_admin = c.pop("admin_chat_id", None)  # مهاجرت از نسخه قبلی
    if old_admin and old_admin not in c["admins"]:
        c["admins"].append(old_admin)
    return c


def save_cfg():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


cfg = load_cfg()
save_cfg()
ui_q = queue.Queue()


def get_token():
    """توکن از متغیر محیطی RUBIKA_BOT_TOKEN یا از config.json خوانده می‌شود."""
    return (os.environ.get("RUBIKA_BOT_TOKEN") or cfg.get("token") or "").strip()


def log(msg, tag="info"):
    ui_q.put(("log", f"[{datetime.now():%H:%M:%S}] {msg}", tag))


# ───────────────────────── دیتابیس ─────────────────────────
class DB:
    def __init__(self):
        self.lock = threading.Lock()
        self.c = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.executescript("""
            create table if not exists employees(
                id integer primary key autoincrement,
                name text not null,
                finger_id integer unique,
                hourly_rate integer not null,
                active integer not null default 1);
            create table if not exists attendance(
                id integer primary key autoincrement,
                emp_id integer not null,
                check_in text not null,
                check_out text);
        """)

    def q(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            rows = cur.fetchall()
            self.c.commit()
            return rows


db = DB()


# ───────────────────────── دستگاه اثر انگشت ─────────────────────────
class Fingerprint:
    def __init__(self):
        self.ser = None
        self.lock = threading.RLock()
        self.capacity = 200
        self.reset = True  # درخواست اتصال مجدد
        self.force = True  # جستجوی فوری دستگاه
        self.last_ports = None
        self.last_probe = 0

    @property
    def connected(self):
        return self.ser is not None

    def connect(self, port, baud, timeout=2):
        self.close()
        self.ser = serial.Serial(port, int(baud), timeout=timeout)
        try:
            r = self._cmd(b"\x0f")  # ReadSysPara
            if r[0] != 0:
                raise IOError("دستگاه پاسخ معتبر نداد")
            self.capacity = (r[5] << 8) | r[6]
            self.ser.timeout = 2
        except Exception:
            self.close()
            raise

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def _cmd(self, data):
        ln = len(data) + 2
        body = bytes([0x01, ln >> 8, ln & 255]) + data
        cs = sum(body) & 0xFFFF
        pkt = b"\xEF\x01\xFF\xFF\xFF\xFF" + body + bytes([cs >> 8, cs & 255])
        self.ser.reset_input_buffer()
        self.ser.write(pkt)
        head = self.ser.read(9)
        if len(head) < 9 or head[:2] != b"\xEF\x01":
            raise IOError("پاسخی از دستگاه دریافت نشد")
        n = (head[7] << 8) | head[8]
        rest = self.ser.read(n)
        if len(rest) < n:
            raise IOError("پاسخ ناقص از دستگاه")
        return rest[:-2]

    def gen_img(self):
        return self._cmd(b"\x01")[0]

    def img2tz(self, buf):
        return self._cmd(bytes([0x02, buf]))[0]

    def search(self):
        cap = self.capacity
        r = self._cmd(bytes([0x04, 1, 0, 0, cap >> 8, cap & 255]))
        if r[0] == 0 and len(r) >= 5:
            return 0, (r[1] << 8) | r[2], (r[3] << 8) | r[4]
        return r[0], None, None

    def reg_model(self):
        return self._cmd(b"\x05")[0]

    def store(self, buf, pid):
        return self._cmd(bytes([0x06, buf, pid >> 8, pid & 255]))[0]

    def delete(self, pid):
        return self._cmd(bytes([0x0C, pid >> 8, pid & 255, 0, 1]))[0]

    def _wait_finger(self, timeout):
        t = time.time()
        while time.time() - t < timeout:
            if self.gen_img() == 0:
                return
            time.sleep(0.1)
        raise IOError("زمان تمام شد؛ انگشتی گذاشته نشد")

    def _wait_removed(self, timeout):
        t = time.time()
        while time.time() - t < timeout:
            if self.gen_img() == 2:
                return
            time.sleep(0.15)

    def enroll(self, page_id, cb):
        with self.lock:
            cb("☝️ انگشت را روی دستگاه بگذارید...")
            self._wait_finger(20)
            if self.img2tz(1) != 0:
                raise IOError("تصویر انگشت واضح نبود، دوباره تلاش کنید")
            code, _, _ = self.search()
            if code == 0:
                raise IOError("این اثر انگشت قبلاً ثبت شده است")
            cb("✋ انگشت را بردارید...")
            self._wait_removed(10)
            cb("☝️ همان انگشت را دوباره بگذارید...")
            self._wait_finger(20)
            if self.img2tz(2) != 0:
                raise IOError("تصویر انگشت واضح نبود، دوباره تلاش کنید")
            if self.reg_model() != 0:
                raise IOError("دو اسکن یکسان نبودند، دوباره تلاش کنید")
            if self.store(1, page_id) != 0:
                raise IOError("ذخیره در حافظه دستگاه ناموفق بود")


fp = Fingerprint()


# ───────────────────────── ابزارهای زمان و متن ─────────────────────────
def fmt(dt, with_date=True):
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    return j.strftime("%Y/%m/%d %H:%M") if with_date else j.strftime("%H:%M")


def dur(secs):
    h = int(secs // 3600)
    m = int(secs % 3600 // 60)
    if h and m:
        return f"{h} ساعت و {m} دقیقه"
    if h:
        return f"{h} ساعت"
    return f"{m} دقیقه"


def norm(t):
    return t.replace("ي", "ی").replace("ك", "ک").strip()


def today_bounds():
    t0 = datetime.combine(datetime.now().date(), datetime.min.time())
    return t0, t0 + timedelta(days=1)


def month_range(prev=False):
    j = jdatetime.date.today().replace(day=1)
    if prev:
        j = (j - timedelta(days=1)).replace(day=1)
    nxt = (j + timedelta(days=32)).replace(day=1)

    def g(d):
        return datetime.combine(d.togregorian(), datetime.min.time())

    return g(j), g(nxt), f"{MONTHS[j.month - 1]} {j.year}"


def summarize(start, end):
    now = datetime.now()
    rows = db.q("""
        select e.id eid, e.name, e.hourly_rate, a.check_in, a.check_out
        from attendance a join employees e on e.id = a.emp_id
        where a.check_in < ? and (a.check_out is null or a.check_out > ?)
        order by a.check_in""",
                (end.isoformat(timespec="seconds"), start.isoformat(timespec="seconds")))
    res = {}
    for r in rows:
        s = max(datetime.fromisoformat(r["check_in"]), start)
        e = min(datetime.fromisoformat(r["check_out"]) if r["check_out"] else now, end)
        if e <= s:
            continue
        d = res.setdefault(r["eid"], {"name": r["name"], "rate": r["hourly_rate"],
                                      "secs": 0, "sessions": []})
        d["secs"] += (e - s).total_seconds()
        d["sessions"].append((s, e, r["check_out"] is None))
    return res


def pick(res, name, exact):
    if not name:
        return res
    n = norm(name)
    return {k: v for k, v in res.items()
            if (norm(v["name"]) == n if exact else n in norm(v["name"]))}


DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def find_emp(name):
    n = norm(name)
    for r in db.q("select * from employees where active=1"):
        if norm(r["name"]) == n:
            return r
    return None


def parse_amount(t):
    t = re.sub(r"[,\s،٬.]|تومان", "", t.translate(DIGITS))
    return int(t) if t.isdigit() and int(t) <= 10 ** 9 else None


# ───────────────────────── ثبت اثر انگشت ─────────────────────────
def handle_punch(finger_id):
    rows = db.q("select * from employees where finger_id=? and active=1", (finger_id,))
    if not rows:
        log(f"اثر انگشت ناشناخته (شناسه {finger_id})", "err")
        return
    emp = rows[0]
    now = datetime.now().replace(microsecond=0)
    t0, t1 = today_bounds()
    when = f"🕒 ساعت {tm(now)}   📅 {jdate(now)}"
    op = db.q("select * from attendance where emp_id=? and check_out is null "
              "order by id desc limit 1", (emp["id"],))
    if op:  # در حال کار بود ← توقف حقوق
        a = op[0]
        db.q("update attendance set check_out=? where id=?", (now.isoformat(), a["id"]))
        shift = (now - datetime.fromisoformat(a["check_in"])).total_seconds()
        d = summarize(t0, t1).get(emp["id"])
        secs = d["secs"] if d else shift
        if emp["hourly_rate"]:
            pay_line = f"💰 حقوق امروز تا اینجا: {money(round(secs / 3600 * emp['hourly_rate']))} تومان"
        else:
            pay_line = "⚠️ دستمزد ساعتی هنوز تعیین نشده"
        msg = "\n".join(["⏸ توقف حقوق", BAR, f"👤 {emp['name']}", when, SEP,
                         f"⏱ این نوبت: {dur(shift)}",
                         f"📆 مجموع امروز: {dur(secs)}",
                         pay_line, SEP,
                         "💡 خروج موقت یا پایان کار؛ برای ادامه دوباره اثر انگشت بزنند."])
        log(f"⏸ توقف حقوق: {emp['name']}", "pause")
    else:
        last = db.q("select check_out from attendance where emp_id=? and check_in>=? "
                    "and check_out is not null order by id desc limit 1",
                    (emp["id"], t0.isoformat(timespec="seconds")))
        db.q("insert into attendance(emp_id, check_in) values(?,?)",
             (emp["id"], now.isoformat()))
        if last:  # امروز قبلاً کار کرده ← ادامه حقوق
            gap = (now - datetime.fromisoformat(last[0]["check_out"])).total_seconds()
            msg = "\n".join(["▶️ ادامه حقوق", BAR, f"👤 {emp['name']}", when, SEP,
                             f"⏳ مدت توقف: {dur(gap)}"])
            log(f"▶️ ادامه حقوق: {emp['name']}", "resume")
        else:
            msg = "\n".join(["🟢 ورود ثبت شد", BAR, f"👤 {emp['name']}", when])
            log(f"🟢 ورود: {emp['name']}", "in")
    ui_q.put(("refresh",))
    bot.notify(msg)


BAUDS = [57600, 9600, 115200, 19200, 38400]


def candidate_ports():
    if cfg["port"] != "auto":
        return [cfg["port"]]
    found = [p.device for p in list_ports.comports()]
    last = cfg.get("last_port")
    return sorted(found, key=lambda p: p != last)  # آخرین پورت موفق اول


def candidate_bauds():
    if cfg["baud"] != "auto":
        return [int(cfg["baud"])]
    last = cfg.get("last_baud")
    return sorted(BAUDS, key=lambda b: b != last)


def auto_connect():
    """همه پورت‌ها و سرعت‌های ممکن را امتحان می‌کند؛ اولین دستگاهی که جواب بدهد وصل می‌شود."""
    for port in candidate_ports():
        for baud in candidate_bauds():
            try:
                with fp.lock:
                    fp.connect(port, baud, timeout=0.7)
                cfg["last_port"], cfg["last_baud"] = port, baud
                save_cfg()
                return port, baud
            except serial.SerialException:
                break  # پورت باز نمی‌شود (مشغول یا نامعتبر) ← سراغ پورت بعدی
            except Exception:
                continue  # سرعت اشتباه یا جوابی نیامد ← سرعت بعدی
    return None


def diagnose():
    """گزارش همه پورت‌ها و پاسخ خام دستگاه به هر سرعت را در بخش رویدادها می‌نویسد."""
    ports = list(list_ports.comports())
    if not ports:
        log("🔍 هیچ پورت COM در ویندوز دیده نمی‌شود (درایور نصب نیست، یا دستگاه "
            "USB مستقیم/HID است، یا کابل فقط شارژ است)", "err")
        return
    log(f"🔍 {len(ports)} پورت پیدا شد:", "resume")
    for p in ports:
        log(f"   {p.device} — {p.description} — {p.hwid}")
    pkt = bytes.fromhex("EF01FFFFFFFF0100030F0013")  # ReadSysPara
    with fp.lock:
        for p in ports:
            for baud in BAUDS:
                try:
                    with serial.Serial(p.device, baud, timeout=0.7) as s:
                        s.reset_input_buffer()
                        s.write(pkt)
                        data = s.read(32)
                except serial.SerialException as e:
                    log(f"   {p.device}: باز نشد ({e})", "err")
                    break
                if not data:
                    log(f"   {p.device} @ {baud}: بدون پاسخ")
                elif data[:2] == b"\xEF\x01":
                    log(f"   {p.device} @ {baud}: ✅ پاسخ معتبر دستگاه — {data.hex(' ')}", "in")
                else:
                    log(f"   {p.device} @ {baud}: پاسخ نامفهوم — {data.hex(' ')}", "pause")
    log("🔍 پایان تشخیص", "resume")


def scanner_loop():
    last_err = None
    while True:
        try:
            if fp.reset:
                with fp.lock:
                    fp.close()
                    fp.reset = False
                    fp.force = True
                ui_q.put(("dev", "idle", "⚪ قطع"))
            if not fp.connected:
                ports_now = frozenset(p.device for p in list_ports.comports())
                due = (fp.force or ports_now != fp.last_ports
                       or time.time() - fp.last_probe > 15)
                if not due:
                    time.sleep(1)
                    continue
                fp.force = False
                fp.last_ports = ports_now
                fp.last_probe = time.time()
                ui_q.put(("dev", "idle", "🔎 در حال جستجوی دستگاه..."))
                found = auto_connect()
                if found:
                    ui_q.put(("dev", "ok", f"🟢 متصل ({found[0]} / {found[1]})"))
                    log(f"به دستگاه روی {found[0]} با سرعت {found[1]} وصل شد", "resume")
                    last_err = None
                else:
                    ui_q.put(("dev", "err", "🔴 دستگاه پیدا نشد"))
                    if last_err != "nf":
                        log("دستگاه اثر انگشت پیدا نشد؛ با وصل شدن، خودکار متصل می‌شود", "err")
                        last_err = "nf"
                    time.sleep(1)
                    continue

            result = None
            with fp.lock:
                if fp.gen_img() == 0:
                    if fp.img2tz(1) == 0:
                        code, pid, _ = fp.search()
                        result = pid if code == 0 else -1
                    else:
                        result = -2
            if result is None:
                time.sleep(0.15)
                continue
            if result >= 0:
                handle_punch(result)
            elif result == -1:
                log("اثر انگشت ثبت‌نشده", "err")
            t = time.time()
            while time.time() - t < 5:  # صبر تا برداشتن انگشت
                with fp.lock:
                    if fp.gen_img() == 2:
                        break
                time.sleep(0.2)
            time.sleep(0.5)
        except Exception as e:
            log(f"خطای دستگاه: {e}", "err")
            with fp.lock:
                fp.close()
            ui_q.put(("dev", "err", "🔴 قطع"))
            time.sleep(3)


def auto_close_loop():
    """اگر کسی اثر انگشت آخر روز را نزد، ساعت حضورش در ساعت «پایان خودکار روز» بسته می‌شود."""
    while True:
        try:
            hh, mm = map(int, str(cfg.get("auto_close", "23:59")).split(":"))
            now = datetime.now()
            rows = db.q("select a.id, a.check_in, e.name from attendance a "
                        "join employees e on e.id=a.emp_id where a.check_out is null")
            for r in rows:
                ci = datetime.fromisoformat(r["check_in"])
                cut = datetime.combine(ci.date(), dtime(hh, mm))
                if ci < cut and now >= cut:
                    close_at = cut
                elif ci >= cut and ci.date() < now.date():
                    close_at = ci
                else:
                    continue
                db.q("update attendance set check_out=? where id=?",
                     (close_at.isoformat(timespec="seconds"), r["id"]))
                log(f"پایان خودکار روز: {r['name']}", "err")
                bot.notify("\n".join(["⚠️ پایان خودکار روز", BAR, f"👤 {r['name']}",
                                      f"🕒 حضور تا ساعت {tm(close_at)} حساب شد",
                                      "اثر انگشت پایان کار زده نشده بود."]))
            ui_q.put(("refresh",))
        except Exception as e:
            log(f"خطای پایان خودکار روز: {e}", "err")
        time.sleep(30)


# ───────────────────────── متن گزارش‌ها ─────────────────────────
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
BAR = "━━━━━━━━━━━━━━━"
SEP = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
STATUS_TXT = {"work": "🟢 در حال کار", "pause": "⏸ حقوق متوقف", "absent": "⚪ هنوز نیامده"}


def fa(t):
    return str(t).translate(FA)


def money(n):
    return f"{n:,}".replace(",", "٬")


def jdate(dt):
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d")


def jmd(dt):
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%m/%d")


def tm(dt):
    return dt.strftime("%H:%M")


def weekday(dt):
    return WEEKDAYS[(dt.weekday() + 2) % 7]


def meter(v, mx, n=8):
    k = round(n * v / mx) if mx else 0
    return "▰" * k + "▱" * (n - k)


def emp_status(eid):
    t0, _ = today_bounds()
    if db.q("select 1 from attendance where emp_id=? and check_out is null", (eid,)):
        return "work"
    if db.q("select 1 from attendance where emp_id=? and check_in>=?",
            (eid, t0.isoformat(timespec="seconds"))):
        return "pause"
    return "absent"


def rate_text(rate):
    return f"{money(rate)} تومان در ساعت" if rate else "تعیین نشده ⚠️"


# ───────────────────────── متن گزارش‌ها ─────────────────────────
def present_text():
    t0, _ = today_bounds()
    working = db.q("""select e.name, a.check_in from attendance a
                      join employees e on e.id=a.emp_id
                      where a.check_out is null and e.active=1 order by a.check_in""")
    paused = db.q("""select e.name, max(a.check_out) co from employees e
                     join attendance a on a.emp_id=e.id
                     where e.active=1 and a.check_in>=?
                       and e.id not in (select emp_id from attendance where check_out is null)
                     group by e.id order by e.name""", (t0.isoformat(timespec="seconds"),))
    seen = {r["name"] for r in working} | {r["name"] for r in paused}
    absent = [r["name"] for r in db.q("select name from employees where active=1 order by name")
              if r["name"] not in seen]
    if not seen and not absent:
        return "👥 هنوز کارمندی ثبت نشده است."
    now = datetime.now()
    lines = ["👥 وضعیت لحظه‌ای فروشگاه", BAR,
             f"📅 {weekday(now)} {jdate(now)}   🕒 {tm(now)}", ""]
    if working:
        lines.append(f"🟢 در حال کار ({len(working)})")
        lines += [f"   ▫️ {r['name']} — از {tm(datetime.fromisoformat(r['check_in']))}"
                  for r in working]
        lines.append("")
    if paused:
        lines.append(f"⏸ حقوق متوقف ({len(paused)})")
        lines += [f"   ▫️ {r['name']} — از {tm(datetime.fromisoformat(r['co']))}"
                  for r in paused]
        lines.append("")
    if absent:
        lines.append(f"⚪ هنوز نیامده ({len(absent)})")
        lines += [f"   ▫️ {n}" for n in absent]
    return "\n".join(lines).strip()


def report_text(arg="", emp=None):
    arg = norm(arg)
    t0, t1 = today_bounds()
    absent = []
    today_mode = emp is None and not arg
    if today_mode:
        start, end, detail = t0, t1, True
        title, sub = "📊 گزارش امروز", f"📅 {weekday(t0)} {jdate(t0)}"
        res = summarize(start, end)
        names_in = {v["name"] for v in res.values()}
        absent = [r["name"] for r in db.q("select name from employees where active=1 order by name")
                  if r["name"] not in names_in]
    else:
        prev = arg.startswith("ماه قبل")
        if prev:
            arg = arg[len("ماه قبل"):].strip()
        detail = True
        if emp is None and arg.startswith("ماه"):
            arg = arg[len("ماه"):].strip()
            detail = False
        name = emp if emp is not None else arg
        start, end, t = month_range(prev)
        title = f"📊 گزارش {t}"
        sub = "📅 جزئیات حضور" if name else "📅 خلاصه حضور همه"
        res = pick(summarize(start, end), name, emp is not None)
    if not res and not absent:
        return "🔍 موردی پیدا نشد."
    mx = max((v["secs"] for v in res.values()), default=0)
    lines = [title, BAR, sub, ""]
    for v in res.values():
        lines.append(f"👤 {v['name']}")
        lines.append(f"⏱ مجموع: {dur(v['secs'])}")
        if detail:
            for s_, e_, still in v["sessions"]:
                out = "⏳ در حال کار" if still else f"⏸ {tm(e_)}"
                when = tm(s_) if today_mode else f"{jmd(s_)}  {tm(s_)}"
                lines.append(f"   🟢 {when} ◂ {out}")
        else:
            lines.append(meter(v["secs"], mx))
        lines.append(SEP)
    if res:
        lines.pop()
    if absent:
        lines += ["", "⚪ بدون حضور امروز:"] + [f"   ▫️ {n}" for n in absent]
    return "\n".join(lines).strip()


def salary_text(arg="", emp=None, prev=False):
    arg = norm(arg)
    if emp is None and arg.startswith("ماه قبل"):
        prev = True
        arg = arg[len("ماه قبل"):].strip()
    name = emp if emp is not None else arg
    start, end, title = month_range(prev)
    res = pick(summarize(start, end), name, emp is not None)
    if not res:
        return "🔍 موردی پیدا نشد."
    mx = max(v["secs"] for v in res.values())
    lines = [f"💰 حقوق {title}", BAR, ""]
    total = 0
    for v in res.values():
        pay = round(v["secs"] / 3600 * v["rate"])
        total += pay
        live = "   🟢 الان در حال کار" if any(x[2] for x in v["sessions"]) else ""
        lines.append(f"👤 {v['name']}{live}")
        lines.append(f"⏱ {dur(v['secs'])}")
        if v["rate"]:
            lines.append(f"💵 {money(pay)} تومان")
            lines.append(f"🏷 نرخ: {money(v['rate'])} تومان در ساعت")
        else:
            lines.append("⚠️ دستمزد ساعتی تعیین نشده")
        lines.append(meter(v["secs"], mx))
        lines.append(SEP)
    lines.pop()
    if len(res) > 1:
        lines += ["", BAR, f"🧮 جمع کل: {money(total)} تومان"]
    return "\n".join(lines).strip()


# ───────────────────────── منوی دکمه‌ای ربات ─────────────────────────
WELCOME = ("🏪 سامانه حضور و غیاب فروشگاه\n" + BAR + "\n"
           "👋 خوش آمدید!\nیکی از گزینه‌های زیر را انتخاب کنید 👇\n\n"
           "✦ Made by Mostafa Parvin")
BTN_MENU = "🏠 منوی اصلی"
BTN_PRESENT = "🟢 حاضرین"
BTN_TODAY = "📊 گزارش امروز"
BTN_MONTH = "📅 گزارش این ماه"
BTN_SAL = "💰 حقوق این ماه"
BTN_SAL_PREV = "⏮ حقوق ماه قبل"
BTN_PERSON = "👥 کارمندان"
BTN_CANCEL = "❌ انصراف"
BTN_RATE = "✏️ ویرایش دستمزد | "
MENU_PREFIXES = ("📊", "💰", "⏮", "👤", "👥", "🟢", "📅", "✏", "🏠")


def make_keypad(rows):
    n, out = 0, []
    for row in rows:
        btns = []
        for t in row:
            n += 1
            btns.append({"id": f"b{n}", "type": "Simple", "button_text": t})
        out.append({"buttons": btns})
    return {"rows": out, "resize_keyboard": True, "on_time_keyboard": False}


def main_keypad():
    return make_keypad([[BTN_PRESENT, BTN_TODAY],
                        [BTN_MONTH, BTN_SAL],
                        [BTN_SAL_PREV, BTN_PERSON]])


def employees_keypad():
    names = [r["name"] for r in db.q("select name from employees where active=1 order by name")]
    rows = [["👤 " + n for n in names[i:i + 2]] for i in range(0, len(names), 2)]
    rows.append([BTN_MENU])
    return make_keypad(rows)


def person_keypad(name):
    return make_keypad([[f"📊 گزارش | {name}", f"💰 حقوق | {name}"],
                        [f"⏮ حقوق قبل | {name}", f"{BTN_RATE}{name}"],
                        [BTN_PERSON, BTN_MENU]])


def person_card(row):
    st = emp_status(row["id"])
    return "\n".join([f"👤 {row['name']}", BAR,
                      f"📍 وضعیت: {STATUS_TXT[st]}",
                      f"💵 دستمزد: {rate_text(row['hourly_rate'])}",
                      BAR, "چه کاری انجام شود؟ 👇"])


def route(text):
    t = norm(text)
    if t.lower() in ("/start", "start", "شروع", "/menu", "منو") or t == BTN_MENU:
        return WELCOME, main_keypad()
    if t == BTN_PRESENT:
        return present_text(), main_keypad()
    if t == BTN_TODAY:
        return report_text(), main_keypad()
    if t == BTN_MONTH:
        return report_text("ماه"), main_keypad()
    if t == BTN_SAL:
        return salary_text(), main_keypad()
    if t == BTN_SAL_PREV:
        return salary_text(prev=True), main_keypad()
    if t == BTN_PERSON:
        return "👥 کدام کارمند؟\n" + BAR + "\nنام را انتخاب کنید 👇", employees_keypad()
    for prefix, fn in (("📊 گزارش | ", lambda n: report_text(emp=n)),
                       ("💰 حقوق | ", lambda n: salary_text(emp=n)),
                       ("⏮ حقوق قبل | ", lambda n: salary_text(emp=n, prev=True))):
        if t.startswith(prefix):
            n = t[len(prefix):].strip()
            return fn(n), person_keypad(n)
    if t.startswith("👤 "):
        n = t[2:].strip()
        row = find_emp(n)
        if row:
            return person_card(row), person_keypad(n)
    # سازگاری با دستورهای تایپی
    parts = t.split(None, 1)
    cmd = parts[0].lstrip("/").lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd in ("حاضرین", "present"):
        return present_text(), main_keypad()
    if cmd in ("گزارش", "report"):
        return report_text(arg), main_keypad()
    if cmd in ("حقوق", "salary"):
        return salary_text(arg), main_keypad()
    return WELCOME, main_keypad()


# ───────────────────────── ربات روبیکا ─────────────────────────

MAX_ADMINS = 2
pairing = {"code": None, "expires": 0, "fails": 0}


def start_pairing():
    """کد شش‌رقمی ۵ دقیقه‌ای؛ فقط در برنامه (روی کامپیوتر) نمایش داده می‌شود."""
    if len(cfg["admins"]) >= MAX_ADMINS:
        return None
    pairing.update(code=str(secrets.randbelow(900000) + 100000),
                   expires=time.time() + 300, fails=0)
    return pairing["code"]


class Bot:
    def __init__(self):
        self.offset = None
        self.seen = []
        self.pending = {}  # چت‌هایی که منتظر عدد دستمزد جدید هستند

    def api(self, method, **data):
        url = f"https://botapi.rubika.ir/v3/{get_token()}/{method}"
        return requests.post(url, json=data, timeout=20).json()

    def send(self, chat_id, text, keypad=None):
        chunks = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [" "]
        for i, part in enumerate(chunks):
            data = {"chat_id": chat_id, "text": fa(part)}
            if keypad and i == len(chunks) - 1:
                data["chat_keypad"] = keypad
                data["chat_keypad_type"] = "New"
            try:
                r = self.api("sendMessage", **data)
                if r.get("status") != "OK":
                    log(f"ارسال پیام به روبیکا ناموفق: {r}", "err")
            except Exception as e:
                log(f"خطا در ارسال به روبیکا: {e}", "err")

    def notify(self, text):
        admins = cfg.get("admins") or []
        if not admins:
            log("هیچ گوشی‌ای برای ربات ثبت نشده؛ در برنامه «افزودن گوشی» را بزنید", "err")
        for a in admins:
            threading.Thread(target=self.send, args=(a, text), daemon=True).start()

    def try_pair(self, chat, text):
        admins = cfg["admins"]
        t = norm(text).translate(DIGITS)
        code = pairing["code"]
        if code and time.time() < pairing["expires"] and len(admins) < MAX_ADMINS:
            if t == code:
                admins.append(chat)
                save_cfg()
                pairing["code"] = None
                log("یک گوشی جدید برای ربات ثبت شد", "resume")
                ui_q.put(("phones",))
                self.send(chat, "✅ این گوشی ثبت شد\n" + BAR + "\n\n" + WELCOME, main_keypad())
                return
            if re.fullmatch(r"\d{6}", t):
                pairing["fails"] += 1
                if pairing["fails"] >= 5:
                    pairing["code"] = None
                    log("کد ثبت گوشی به‌دلیل تلاش‌های ناموفق باطل شد", "err")
        if len(admins) >= MAX_ADMINS:
            self.send(chat, "⛔ شما دسترسی ندارید.")
        else:
            self.send(chat, "⛔ شما دسترسی ندارید\n" + BAR + "\n"
                            "برای ثبت این گوشی:\n"
                            "۱) در برنامه روی «➕ افزودن گوشی» بزنید\n"
                            "۲) کد شش‌رقمی را همین‌جا بفرستید")

    def rate_prompt(self, row):
        return "\n".join(["✏️ ویرایش دستمزد", BAR, f"👤 {row['name']}",
                          f"💵 نرخ فعلی: {rate_text(row['hourly_rate'])}", BAR,
                          "عدد جدید را بفرستید (مثلاً 50000) 👇"])

    def handle_pending(self, chat, t):
        """ویرایش دستمزد: منتظر عدد جدید. اگر (None, None) برگردد، پیام عادی پردازش می‌شود."""
        name = self.pending[chat]
        if t == BTN_CANCEL:
            del self.pending[chat]
            return "❎ ویرایش لغو شد.", person_keypad(name)
        rate = parse_amount(t)
        if rate is None:
            if t.startswith(MENU_PREFIXES) or t.lower() in ("/start", "start"):
                del self.pending[chat]
                return None, None
            return ("⚠️ عدد معتبر نیست\nفقط عدد بفرستید، مثلاً 50000",
                    make_keypad([[BTN_CANCEL]]))
        del self.pending[chat]
        row = find_emp(name)
        if not row:
            return "⚠️ این کارمند پیدا نشد.", main_keypad()
        db.q("update employees set hourly_rate=? where id=?", (rate, row["id"]))
        log(f"دستمزد {row['name']} از روبیکا تغییر کرد", "resume")
        return ("\n".join(["✅ دستمزد به‌روز شد", BAR, f"👤 {row['name']}",
                           f"قبل:  {rate_text(row['hourly_rate'])}",
                           f"بعد:  {rate_text(rate)}", BAR,
                           "⚠️ حقوق گزارش‌های همین ماه هم با نرخ جدید حساب می‌شود."]),
                person_keypad(row["name"]))

    def handle(self, u):
        typ = u.get("type")
        chat = u.get("chat_id")
        if not chat:
            return
        if typ == "StartedBot":
            text = "/start"
        elif typ == "NewMessage":
            m = u.get("new_message") or {}
            key = (chat, m.get("message_id"))
            if key in self.seen:
                return
            self.seen = (self.seen + [key])[-200:]
            text = (m.get("text") or "").strip()
            if not text:
                return
        else:
            return
        if chat not in (cfg.get("admins") or []):
            self.try_pair(chat, text)
            return
        t = norm(text)
        if chat in self.pending:
            reply, kp = self.handle_pending(chat, t)
            if reply is not None:
                self.send(chat, reply, kp)
                return
        if t.startswith(BTN_RATE):
            row = find_emp(t[len(BTN_RATE):])
            if row:
                self.pending[chat] = row["name"]
                self.send(chat, self.rate_prompt(row), make_keypad([[BTN_CANCEL]]))
                return
        reply, kp = route(text)
        self.send(chat, reply, kp)

    def loop(self):
        ok_shown = False
        while True:
            if not get_token():
                ui_q.put(("bot", "err", "🔴 توکن ربات تنظیم نشده (config.json)"))
                ok_shown = False
                time.sleep(5)
                continue
            try:
                data = {"limit": 50}
                if self.offset:
                    data["offset_id"] = self.offset
                res = self.api("getUpdates", **data)
                if res.get("status") != "OK":
                    log(f"خطای ربات: {res}", "err")
                    ui_q.put(("bot", "err", "🔴 خطا در ربات (توکن را بررسی کنید)"))
                    ok_shown = False
                    time.sleep(8)
                    continue
                if not ok_shown:
                    n = len(cfg.get("admins") or [])
                    state = f"{n} گوشی ثبت شده" if n else "هنوز گوشی ثبت نشده"
                    ui_q.put(("bot", "ok", f"🟢 ربات فعال ({state})"))
                    ok_shown = True
                d = res.get("data") or {}
                for u in d.get("updates", []):
                    self.handle(u)
                if d.get("next_offset_id"):
                    self.offset = d["next_offset_id"]
            except Exception as e:
                ui_q.put(("bot", "err", "🔴 عدم ارتباط با روبیکا"))
                ok_shown = False
                log(f"خطای شبکه ربات: {e}", "err")
                time.sleep(6)
            time.sleep(1.5)


bot = Bot()


# ───────────────────────── رابط گرافیکی ─────────────────────────
NAVY = "#1b2a4e"
NAVY2 = "#2a3d6e"
ACCENT = "#2f80ed"
GREEN = "#27ae60"
RED = "#e5484d"
ORANGE = "#f2994a"
SLATE = "#64748b"
GOLD = "#f6c453"
BG = "#f2f5fb"
CARD = "#ffffff"
TEXT = "#1f2937"
MUTED = "#6b7280"
LOGBG = "#0f172a"
FONT = "Segoe UI"
AUTO_LABEL = "خودکار"

CHIPS = {"ok": ("#d9f5e5", "#16794a"), "err": ("#fde0e0", "#b42318"),
         "idle": ("#e5e7eb", "#4b5563")}


def shade(hex_color, f=0.85):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))


def color_button(parent, text, color, cmd, **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=color, fg="white", relief="flat",
                  bd=0, font=(FONT, 10, "bold"), padx=14, pady=7, cursor="hand2",
                  activebackground=shade(color), activeforeground="white", **kw)
    b.bind("<Enter>", lambda e: b.config(bg=shade(color)))
    b.bind("<Leave>", lambda e: b.config(bg=color))
    return b


STATUS_CHIP = {"work": ("#d9f5e5", "#16794a"), "pause": ("#ffe8c7", "#9a5b00"),
               "absent": ("#e5e7eb", "#4b5563")}
STATUS_COLOR = {"work": GREEN, "pause": ORANGE, "absent": "#94a3b8"}
STATUS_TINT = {"work": "#effaf3", "pause": "#fff7ea", "absent": "#f6f7fb"}


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("سیستم حضور و غیاب فروشگاه")
        self.geometry("1080x760")
        self.minsize(1000, 700)
        self.configure(bg=BG)
        self.dlg = self.dlg_lbl = self.dlg_bar = None
        self.pair_dlg = None
        self.setup_style()

        # ── سربرگ ──
        head = tk.Frame(self, bg=NAVY)
        head.pack(fill="x")
        tk.Frame(head, bg=GOLD, height=3).pack(fill="x", side="bottom")
        hin = tk.Frame(head, bg=NAVY)
        hin.pack(fill="x", padx=22, pady=12)
        logo = tk.Canvas(hin, width=54, height=54, bg=NAVY, highlightthickness=0)
        logo.pack(side="left", padx=(0, 14))
        logo.create_oval(2, 2, 52, 52, fill=GOLD, outline="")
        logo.create_text(27, 27, text="🏪", font=(FONT, 20))
        left = tk.Frame(hin, bg=NAVY)
        left.pack(side="left")
        tk.Label(left, text="سیستم حضور و غیاب", bg=NAVY, fg="white",
                 font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(left, text="مدیریت ورود، خروج و حقوق کارکنان فروشگاه", bg=NAVY,
                 fg="#9fb3da", font=(FONT, 10)).pack(anchor="w")
        right_h = tk.Frame(hin, bg=NAVY)
        right_h.pack(side="right")
        self.clock = tk.Label(right_h, bg=NAVY, fg=GOLD, font=(FONT, 16, "bold"))
        self.clock.pack(anchor="e")
        self.date_lbl = tk.Label(right_h, bg=NAVY, fg="#9fb3da", font=(FONT, 10))
        self.date_lbl.pack(anchor="e")

        # ── پاورقی ──
        foot = tk.Frame(self, bg=NAVY)
        foot.pack(side="bottom", fill="x")
        tk.Frame(foot, bg=GOLD, height=2).pack(fill="x", side="top")
        tk.Label(foot, text="✦   Made by Mostafa Parvin   ✦", bg=NAVY, fg=GOLD,
                 font=(FONT, 11, "bold italic"), pady=9).pack()

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2, minsize=380)
        body.rowconfigure(1, weight=1)

        # ── کاشی‌های آمار ──
        tiles = tk.Frame(body, bg=BG)
        tiles.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.tile_nums = {}
        specs = [("all", "👥", "کل کارمندان", ACCENT), ("work", "🟢", "در حال کار", GREEN),
                 ("pause", "⏸", "حقوق متوقف", ORANGE), ("absent", "⚪", "هنوز نیامده", "#94a3b8")]
        for i, (key, icon, label, color) in enumerate(specs):
            tiles.columnconfigure(i, weight=1, uniform="tiles")
            f, num = self.stat_tile(tiles, icon, label, color)
            f.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))
            self.tile_nums[key] = num

        # ── ستون چپ: کارمندان ──
        lcol = tk.Frame(body, bg=BG)
        lcol.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        c2 = self.card(lcol, "👥  کارمندان", expand=True,
                       action=("➕  افزودن کارمند", GREEN, self.add_emp))
        self.emp_scroll = ScrollFrame(c2, CARD)
        self.emp_scroll.pack(fill="both", expand=True)

        # ── ستون راست ──
        rcol = tk.Frame(body, bg=BG)
        rcol.grid(row=1, column=1, sticky="nsew")

        c1 = self.card(rcol, "🔌  دستگاه اثر انگشت")
        g = tk.Frame(c1, bg=CARD)
        g.pack(fill="x")
        tk.Label(g, text="پورت:", bg=CARD, fg=TEXT, font=(FONT, 10)).grid(row=0, column=0, sticky="w")
        self.port = ttk.Combobox(g, width=11, postcommand=self.refresh_ports)
        self.port.set(AUTO_LABEL if cfg["port"] == "auto" else cfg["port"])
        self.port.grid(row=0, column=1, padx=6, pady=3)
        tk.Label(g, text="سرعت:", bg=CARD, fg=TEXT, font=(FONT, 10)).grid(row=0, column=2,
                                                                          sticky="w", padx=(8, 0))
        self.baud = ttk.Combobox(g, width=8,
                                 values=[AUTO_LABEL, 9600, 19200, 38400, 57600, 115200])
        self.baud.set(AUTO_LABEL if cfg["baud"] == "auto" else cfg["baud"])
        self.baud.grid(row=0, column=3, padx=6)
        br = tk.Frame(c1, bg=CARD)
        br.pack(fill="x", pady=(8, 0))
        color_button(br, "اتصال", ACCENT, self.connect).pack(side="left")
        color_button(br, "🔍  تشخیص", SLATE,
                     lambda: threading.Thread(target=diagnose, daemon=True).start()
                     ).pack(side="left", padx=8)
        self.dev_chip = self.chip(c1, "⚪ قطع", "idle")
        self.dev_chip.pack(anchor="w", pady=(10, 0))
        ar = tk.Frame(c1, bg=CARD)
        ar.pack(fill="x", pady=(10, 0))
        tk.Label(ar, text="⏰ پایان خودکار روز:", bg=CARD, fg=TEXT,
                 font=(FONT, 10)).pack(side="left")
        self.ac_var = tk.StringVar(value=str(cfg.get("auto_close", "23:59")))
        ent = ttk.Entry(ar, width=7, textvariable=self.ac_var, justify="center")
        ent.pack(side="left", padx=8)
        ent.bind("<Return>", self.set_auto_close)
        ent.bind("<FocusOut>", self.set_auto_close)

        c4 = self.card(rcol, "🤖  ربات روبیکا",
                       action=("➕  افزودن گوشی", GREEN, self.add_phone))
        self.bot_chip = self.chip(c4, "⚪ در حال راه‌اندازی...", "idle")
        self.bot_chip.pack(anchor="w")
        tk.Label(c4, text="📱 گوشی‌های مجاز (حداکثر دو):", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w", pady=(10, 2))
        self.phones_frame = tk.Frame(c4, bg=CARD)
        self.phones_frame.pack(fill="x")

        c3 = self.card(rcol, "📜  رویدادها", expand=True)
        lf = tk.Frame(c3, bg=CARD)
        lf.pack(fill="both", expand=True)
        self.txt = tk.Text(lf, height=6, state="disabled", wrap="word", bg=LOGBG,
                           fg="#e2e8f0", relief="flat", font=("Consolas", 10), padx=10, pady=8)
        sb2 = ttk.Scrollbar(lf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)
        for tag, col in (("in", "#4ade80"), ("pause", "#fbbf24"), ("resume", "#60a5fa"),
                         ("err", "#f87171"), ("info", "#e2e8f0")):
            self.txt.tag_config(tag, foreground=col)

        self.refresh_ports()
        self.refresh_tree()
        self.refresh_phones()
        self.tick()
        self.after(200, self.poll)

    # ── ظاهر ──
    def setup_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox", padding=4)
        s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#e5e9f2")

    def card(self, parent, title, expand=False, action=None):
        outer = tk.Frame(parent, bg=CARD, highlightbackground="#dbe1ee", highlightthickness=1)
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 10))
        tk.Frame(outer, bg=ACCENT, width=4).pack(side="left", fill="y")
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=14, pady=10)
        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=title, bg=CARD, fg=NAVY, font=(FONT, 12, "bold")).pack(side="left")
        if action:
            color_button(top, action[0], action[1], action[2]).pack(side="right")
        return inner

    def stat_tile(self, parent, icon, label, color):
        f = tk.Frame(parent, bg=CARD, highlightbackground="#dbe1ee", highlightthickness=1)
        tk.Frame(f, bg=color, height=4).pack(fill="x")
        num = tk.Label(f, text="۰", bg=CARD, fg=color, font=(FONT, 28, "bold"))
        num.pack(pady=(8, 0))
        tk.Label(f, text=f"{icon} {label}", bg=CARD, fg=MUTED,
                 font=(FONT, 10, "bold")).pack(pady=(0, 10))
        return f, num

    def chip(self, parent, text, kind):
        bg, fg = CHIPS[kind]
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=(FONT, 10, "bold"), padx=12, pady=4)

    def set_chip(self, lbl, kind, text):
        bg, fg = CHIPS[kind]
        lbl.config(text=text, bg=bg, fg=fg)

    def tick(self):
        now = datetime.now()
        self.clock.config(text=fa(now.strftime("%H:%M:%S")))
        self.date_lbl.config(text=fa(f"{weekday(now)}  {jdate(now)}"))
        self.after(1000, self.tick)

    # ── دستگاه و تنظیمات ──
    def refresh_ports(self):
        self.port["values"] = [AUTO_LABEL] + [p.device for p in list_ports.comports()]

    def connect(self):
        p = self.port.get().strip()
        cfg["port"] = "auto" if p in (AUTO_LABEL, "") else p.upper()
        b = self.baud.get().strip()
        if b in (AUTO_LABEL, ""):
            cfg["baud"] = "auto"
        else:
            try:
                cfg["baud"] = int(b)
            except ValueError:
                messagebox.showerror("خطا", "سرعت نامعتبر است")
                return
        save_cfg()
        self.set_chip(self.dev_chip, "idle", "⏳ در حال اتصال...")
        fp.reset = True

    def set_auto_close(self, _e=None):
        v = self.ac_var.get().strip()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            cfg["auto_close"] = f"{int(m.group(1)):02d}:{m.group(2)}"
            self.ac_var.set(cfg["auto_close"])
            save_cfg()
        else:
            self.ac_var.set(str(cfg.get("auto_close", "23:59")))
            messagebox.showerror("خطا", "ساعت را به شکل 23:59 وارد کنید")

    # ── گوشی‌های مجاز ربات ──
    def refresh_phones(self):
        for w in self.phones_frame.winfo_children():
            w.destroy()
        admins = cfg.get("admins") or []
        for i in range(MAX_ADMINS):
            f = tk.Frame(self.phones_frame, bg=CARD)
            f.pack(fill="x", pady=2)
            kind = "ok" if i < len(admins) else "idle"
            txt = f"✅ گوشی {fa(i + 1)} ثبت شده" if i < len(admins) else f"⚪ گوشی {fa(i + 1)}: خالی"
            bg, fg = CHIPS[kind]
            tk.Label(f, text=txt, bg=bg, fg=fg, font=(FONT, 10, "bold"),
                     padx=10, pady=3).pack(side="left")
            if i < len(admins):
                tk.Button(f, text="حذف", command=lambda i=i: self.remove_phone(i), bg=RED,
                          fg="white", relief="flat", bd=0, font=(FONT, 9, "bold"), padx=10,
                          cursor="hand2").pack(side="left", padx=(6, 0))

    def add_phone(self):
        code = start_pairing()
        if code is None:
            messagebox.showinfo("توجه", "ظرفیت پر است (حداکثر دو گوشی).\nابتدا یکی را حذف کنید.")
            return
        if self.pair_dlg:
            try:
                self.pair_dlg.destroy()
            except tk.TclError:
                pass
        d = self.pair_dlg = tk.Toplevel(self, bg=BG)
        d.title("افزودن گوشی")
        d.geometry("440x280")
        d.transient(self)
        tk.Label(d, text="۱) در روبیکا ربات را Start کنید\n۲) این کد را برای ربات بفرستید:",
                 bg=BG, fg=TEXT, font=(FONT, 11), justify="center").pack(pady=(20, 6))
        tk.Label(d, text=code, bg=BG, fg=ACCENT, font=("Consolas", 36, "bold")).pack(pady=6)
        tk.Label(d, text="این کد تا ۵ دقیقه معتبر است.", bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack()
        color_button(d, "بستن", SLATE, d.destroy).pack(pady=14)

    def remove_phone(self, i):
        admins = cfg.get("admins") or []
        if i >= len(admins):
            return
        if messagebox.askyesno("حذف گوشی", f"گوشی {fa(i + 1)} از دسترسی ربات حذف شود؟"):
            gone = admins.pop(i)
            save_cfg()
            bot.pending.pop(gone, None)
            self.refresh_phones()
            log(f"گوشی {i + 1} از دسترسی ربات حذف شد", "err")

    # ── کارمندان ──
    def refresh_tree(self):
        inner = self.emp_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        rows = db.q("select id, name, finger_id from employees where active=1 order by name")
        cnt = {"work": 0, "pause": 0, "absent": 0}
        for r in rows:
            st = emp_status(r["id"])
            cnt[st] += 1
            self.emp_card(inner, r, st)
        if not rows:
            tk.Label(inner, text="هنوز کارمندی ثبت نشده است.\nروی «➕ افزودن کارمند» بزنید.",
                     bg=CARD, fg=MUTED, font=(FONT, 11), justify="center").pack(pady=50)
        self.tile_nums["all"].config(text=fa(len(rows)))
        for k in cnt:
            self.tile_nums[k].config(text=fa(cnt[k]))

    def emp_card(self, parent, r, st):
        tint, col = STATUS_TINT[st], STATUS_COLOR[st]
        f = tk.Frame(parent, bg=tint, highlightbackground="#e1e6f0", highlightthickness=1)
        f.pack(fill="x", pady=4, padx=2)
        av = tk.Canvas(f, width=46, height=46, bg=tint, highlightthickness=0)
        av.pack(side="left", padx=10, pady=8)
        av.create_oval(2, 2, 44, 44, fill=col, outline="")
        av.create_text(23, 23, text=r["name"][:1], fill="white", font=(FONT, 16, "bold"))
        mid = tk.Frame(f, bg=tint)
        mid.pack(side="left", fill="x", expand=True)
        tk.Label(mid, text=r["name"], bg=tint, fg=TEXT, font=(FONT, 12, "bold"),
                 anchor="w").pack(anchor="w")
        tk.Label(mid, text=f"☝️ اثر انگشت شماره {fa(r['finger_id'])}", bg=tint, fg=MUTED,
                 font=(FONT, 9), anchor="w").pack(anchor="w")
        tk.Button(f, text="🗑", command=lambda r=r: self.del_emp(r), bg=tint, fg=RED,
                  activebackground=tint, relief="flat", bd=0, font=(FONT, 13),
                  cursor="hand2").pack(side="right", padx=10)
        bg, fg = STATUS_CHIP[st]
        tk.Label(f, text=STATUS_TXT[st], bg=bg, fg=fg, font=(FONT, 10, "bold"),
                 padx=10, pady=3).pack(side="right", padx=6)

    def add_emp(self):
        if not fp.connected:
            messagebox.showwarning("توجه", "ابتدا به دستگاه وصل شوید")
            return
        name = simpledialog.askstring("افزودن کارمند", "نام و نام خانوادگی:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        used = {r["finger_id"] for r in
                db.q("select finger_id from employees where finger_id is not null")}
        pid = next((i for i in range(fp.capacity) if i not in used), None)
        if pid is None:
            messagebox.showerror("خطا", "حافظه دستگاه پر است")
            return

        self.dlg = tk.Toplevel(self, bg=BG)
        self.dlg.title("ثبت اثر انگشت")
        self.dlg.geometry("400x180")
        self.dlg.transient(self)
        self.dlg.protocol("WM_DELETE_WINDOW", lambda: None)
        tk.Label(self.dlg, text=f"ثبت اثر انگشت: {name}", bg=BG, fg=NAVY,
                 font=(FONT, 12, "bold")).pack(pady=(18, 4))
        self.dlg_lbl = tk.Label(self.dlg, text="در حال آماده‌سازی...", bg=BG, fg=TEXT,
                                font=(FONT, 11), wraplength=360)
        self.dlg_lbl.pack(pady=6)
        self.dlg_bar = ttk.Progressbar(self.dlg, mode="indeterminate", length=300)
        self.dlg_bar.pack(pady=8)
        self.dlg_bar.start(12)

        def work():
            try:
                fp.enroll(pid, lambda m: ui_q.put(("enroll", m)))
                db.q("insert into employees(name, finger_id, hourly_rate) values(?,?,0)",
                     (name, pid))
                ui_q.put(("enroll_done", True, f"کارمند «{name}» ثبت شد.\n"
                          "دستمزد او را از ربات روبیکا تعیین کنید."))
                log(f"کارمند جدید: {name}", "resume")
                bot.notify("\n".join(["🆕 کارمند جدید ثبت شد", BAR, f"👤 {name}",
                                      "⚠️ دستمزد ساعتی هنوز تعیین نشده", SEP,
                                      "💡 از منو: 👥 کارمندان ◂ انتخاب نام ◂ ✏️ ویرایش دستمزد"]))
            except Exception as e:
                ui_q.put(("enroll_done", False, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def del_emp(self, r):
        if not messagebox.askyesno("حذف", f"«{r['name']}» حذف شود؟\n"
                                          "(سوابق حضور و حقوق گذشته او در گزارش‌ها می‌ماند)"):
            return
        try:
            if fp.connected and r["finger_id"] is not None:
                with fp.lock:
                    fp.delete(r["finger_id"])
        except Exception as e:
            log(f"حذف از حافظه دستگاه ناموفق: {e}", "err")
        now = datetime.now().replace(microsecond=0).isoformat()
        db.q("update attendance set check_out=? where emp_id=? and check_out is null",
             (now, r["id"]))
        db.q("update employees set active=0, finger_id=NULL where id=?", (r["id"],))
        log(f"کارمند حذف شد: {r['name']}", "err")
        self.refresh_tree()

    # ── صف رویدادها ──
    def poll(self):
        try:
            while True:
                ev = ui_q.get_nowait()
                k = ev[0]
                if k == "log":
                    self.txt.config(state="normal")
                    self.txt.insert("end", ev[1] + "\n", ev[2])
                    self.txt.see("end")
                    self.txt.config(state="disabled")
                elif k == "dev":
                    self.set_chip(self.dev_chip, ev[1], ev[2])
                elif k == "bot":
                    self.set_chip(self.bot_chip, ev[1], ev[2])
                elif k == "refresh":
                    self.refresh_tree()
                elif k == "phones":
                    self.refresh_phones()
                    if self.pair_dlg:
                        try:
                            self.pair_dlg.destroy()
                        except tk.TclError:
                            pass
                        self.pair_dlg = None
                elif k == "enroll" and self.dlg_lbl:
                    self.dlg_lbl.config(text=ev[1])
                elif k == "enroll_done":
                    if self.dlg:
                        self.dlg_bar.stop()
                        self.dlg.destroy()
                        self.dlg = self.dlg_lbl = self.dlg_bar = None
                    (messagebox.showinfo if ev[1] else messagebox.showerror)(
                        "ثبت اثر انگشت", ev[2])
                    self.refresh_tree()
        except queue.Empty:
            pass
        self.after(200, self.poll)


if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=auto_close_loop, daemon=True).start()
    threading.Thread(target=bot.loop, daemon=True).start()
    App().mainloop()
