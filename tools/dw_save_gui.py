#!/usr/bin/env python3
"""
Dungeon Within Save Editor - GUI

Loads the plain ES3 JSON save produced by the tools, lets you edit resources,
unit stats/levels and mementos, recomputes DataVault checksums, and writes the
file back.  Buttons also convert an encrypted save (via the running game) and
launch the game in plain-save mode.

Build:  pyinstaller --onefile --windowed --name DungeonWithinSaveEditor tools/dw_save_gui.py
"""

import json
import os
import shutil
import sys
import threading
import time
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import dw_save_editor as ed
import dw_theme as theme  # noqa: E402
import dw_android as android  # noqa: E402

CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.dw_save_editor.json')

DEFAULTS = {
    'endpoint': '',
    'adb': '',
    'serial': 'emulator-5554',
    'device_save': '/sdcard/Android/data/com.GameCoaster.DungeonWithin/files/save.es3',
    'dec_rva': '0x3453fa3',
    'enc_rva': '0x34535f8',
}

STATS = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA', 'HP', 'MainStat']
EFT_STATS = ['MaxHP', 'Strength', 'Dexterity', 'Constitution', 'INT', 'WIS', 'CHA']


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.load(open(CONFIG_PATH, encoding='utf-8')))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        json.dump(cfg, open(CONFIG_PATH, 'w', encoding='utf-8'), indent=1)
    except Exception:
        pass


class NavBook(ttk.Frame):
    """Page container used instead of a notebook (sidebar navigation)."""

    def __init__(self, master, app):
        super().__init__(master, style='TFrame')
        self.app = app
        self.pages = []

    def add(self, frame, text=''):
        self.pages.append(frame)
        frame.pack_forget()

    def select(self, frame):
        page = getattr(self.app, '_page_of', {}).get(frame, frame)
        self.app.show_page(page)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        theme.apply(self)
        self.title('Dungeon Within Save Editor')
        self.geometry('1280x820')
        self.minsize(1080, 680)
        self.cfg = load_config()
        self.text = None
        self.obj = None
        self.path = None
        self.launch_state = None
        try:
            import dw_names
            self.names = dw_names.load_names()
        except Exception:
            self.names = {}
        self._adb_on_path()
        self._build_ui()
        self.log('Ready. Open a plain save (.json) or convert an encrypted save.es3.')
        if len(sys.argv) <= 1:
            self.after(600, lambda: self.on_auto_detect(silent=True))

    # ---------------------------------------------------------------- UI
    def _scroll_page(self, key):
        outer = ttk.Frame(self.nb)
        canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vs.set)
        vs.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>', lambda e, c=canvas, w=win, f=inner: (
            c.itemconfigure(w, width=e.width),
            c.itemconfigure(w, height=max(e.height, f.winfo_reqheight()))))

        def wheel(event, c=canvas):
            step = -1 if getattr(event, 'delta', 0) > 0 else 1
            c.yview_scroll(step, 'units')

        canvas.bind('<Enter>', lambda e, c=canvas, fn=wheel: c.bind_all('<MouseWheel>', fn))
        canvas.bind('<Leave>', lambda e, c=canvas: c.unbind_all('<MouseWheel>'))
        self._page_of[inner] = outer
        self.nb.add(outer)
        return inner

    def _adb_on_path(self):
        """Put the bundled platform-tools on PATH so Frida spawns the same adb."""
        adb = android.bundled_adb()
        if not adb:
            return
        folder = os.path.dirname(adb)
        parts = os.environ.get('PATH', '').split(os.pathsep)
        if folder not in parts:
            os.environ['PATH'] = folder + os.pathsep + os.environ.get('PATH', '')
        os.environ.setdefault('ADB', adb)

    def _build_ui(self):
        self._titles = {}
        self._nav_buttons = {}
        self._nav_labels = {}
        self._page_of = {}

        bar = tk.Frame(self, bg=theme.BG2, height=46)
        bar.pack(fill='x')
        bar.pack_propagate(False)
        tk.Label(bar, text='\u25c6', bg=theme.BG2, fg=theme.ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(side='left', padx=(12, 6))
        tk.Label(bar, text='Dungeon Within Save Editor', bg=theme.BG2, fg=theme.TEXT,
                 font=('Segoe UI', 10, 'bold')).pack(side='left')
        ttk.Button(bar, text='Apply to file', style='Accent.TButton',
                   command=self.on_apply).pack(side='right', padx=(6, 12), pady=8)
        ttk.Button(bar, text='Encrypt save', style='Accent.TButton',
                   command=self.on_encrypt_save).pack(side='right', pady=8)
        ttk.Button(bar, text='Validate', style='Bar.TButton',
                   command=self.on_validate).pack(side='right', pady=8)
        ttk.Button(bar, text='Backup', style='Bar.TButton',
                   command=self.on_backup).pack(side='right', pady=8)

        sf = tk.Frame(bar, bg=theme.BG2)
        sf.pack(side='right', padx=14)
        tk.Label(sf, text='SEARCH', bg=theme.BG2, fg=theme.DIM,
                 font=('Segoe UI', 8, 'bold')).pack(side='left', padx=(0, 6))
        self.filter_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self.filter_var, width=30).pack(side='left')
        self.filter_var.trace_add('write', lambda *a: self.on_filter_changed())

        st = tk.Frame(self, bg=theme.BG2, height=28)
        st.pack(side='bottom', fill='x')
        st.pack_propagate(False)
        self.status_dot = tk.Canvas(st, width=10, height=10, bg=theme.BG2, highlightthickness=0)
        self.status_dot.pack(side='left', padx=(12, 5), pady=9)
        self._dot = self.status_dot.create_oval(1, 1, 9, 9, fill=theme.DIM, outline='')
        self.status_var = tk.StringVar(value='Ready')
        tk.Label(st, textvariable=self.status_var, bg=theme.BG2, fg=theme.MUTED,
                 font=theme.SMALL).pack(side='left')
        self.path_var = tk.StringVar(value='(no file)')
        tk.Label(st, textvariable=self.path_var, bg=theme.BG2, fg=theme.DIM,
                 font=theme.SMALL).pack(side='left', padx=16)
        tk.Label(st, text='v1.0.0', bg=theme.BG2, fg=theme.DIM,
                 font=theme.SMALL).pack(side='right', padx=12)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill='both', expand=True)

        side = tk.Frame(body, bg=theme.SIDEBAR, width=212)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        tk.Label(side, text='Dungeon Within', bg=theme.SIDEBAR, fg=theme.TEXT,
                 font=('Segoe UI', 13, 'bold'), anchor='w').pack(fill='x', padx=16, pady=(16, 0))
        tk.Label(side, text='save editor 1.0', bg=theme.SIDEBAR, fg=theme.DIM,
                 font=theme.SMALL, anchor='w').pack(fill='x', padx=16, pady=(0, 12))
        self._side = side

        content = tk.Frame(body, bg=theme.BG)
        content.pack(side='left', fill='both', expand=True)
        head = tk.Frame(content, bg=theme.BG)
        head.pack(fill='x', padx=22, pady=(16, 4))
        self.page_title = tk.Label(head, text='', bg=theme.BG, fg=theme.TEXT,
                                   font=theme.TITLE, anchor='w')
        self.page_title.pack(fill='x')
        self.page_sub = tk.Label(head, text='', bg=theme.BG, fg=theme.MUTED,
                                 font=theme.BASE, anchor='w')
        self.page_sub.pack(fill='x', pady=(2, 0))

        host = tk.Frame(content, bg=theme.BG)
        host.pack(fill='both', expand=True, padx=14, pady=(0, 6))
        self.nb = NavBook(host, self)
        self.nb.pack(fill='both', expand=True)

        self.tab_conn = self._scroll_page('conn')
        self.tab_res = self._scroll_page('res')
        self.tab_fac = self._scroll_page('fac')
        self.tab_units = self._scroll_page('units')
        self.tab_abil = self._scroll_page('abil')
        self.tab_dl = self._scroll_page('dl')
        self.tab_var = self._scroll_page('var')
        self.tab_col = self._scroll_page('col')
        self.tab_mem = self._scroll_page('mem')
        self.tab_adv = self._scroll_page('adv')
        self.tab_log = self._scroll_page('log')

        self._build_connection()
        self._build_resources()
        self._build_facilities()
        self._build_units()
        self._build_abilities()
        self._build_darklord()
        self._build_variants()
        self._build_collections()
        self._build_mementos()
        self._build_advanced()
        self._build_log()
        self._build_nav()

        self.nb.select(self.tab_res)

    def _build_nav(self):
        specs = [
            ('SESSION', [
                ('Connection', self.tab_conn, 'Connection',
                 'Device, adb and Frida settings.'),
            ]),
            ('SAVE', [
                ('Resources', self.tab_res, 'Resources',
                 'Currencies and resources stored in USER_DATA.storage.'),
                ('Facilities', self.tab_fac, 'Facilities',
                 'Placed facilities: type, ability modifiers/durability, modifications and rank-up.'),
                ('Units', self.tab_units, 'Units',
                 'Monster roster: progress, stats, traits and variants.'),
                ('Abilities', self.tab_abil, 'Abilities',
                 'Equipped parts per monster, and cloning between monsters.'),
            ]),
            ('DARK LORD', [
                ('Dark Lord', self.tab_dl, 'Dark Lord',
                 'The six forms, aspect and authority stages, skin.'),
                ('Variants', self.tab_var, 'Variants',
                 'Stored variant counts and variant research levels.'),
                ('Collections', self.tab_col, 'Collections',
                 'Collection counters used by codex and costume unlocks.'),
            ]),
            ('TOOLS', [
                ('Mementos', self.tab_mem, 'Mementos', 'Memento buy counts.'),
                ('Advanced', self.tab_adv, 'Advanced', 'Read or write any JSON path.'),
                ('Log', self.tab_log, 'Log', 'Everything the Frida side reports.'),
            ]),
        ]
        for section, items in specs:
            tk.Label(self._side, text=section, bg=theme.SIDEBAR, fg=theme.DIM,
                     font=('Segoe UI', 8, 'bold'), anchor='w').pack(fill='x', padx=16, pady=(12, 2))
            for label, frame, title, sub in items:
                page = self._page_of.get(frame, frame)
                btn = tk.Button(self._side, text=label, bg=theme.SIDEBAR, fg=theme.MUTED,
                                activebackground=theme.CARD, activeforeground=theme.TEXT,
                                bd=0, highlightthickness=0, anchor='w', padx=16, pady=6,
                                font=theme.BASE, command=lambda f=page: self.nb.select(f))
                btn.pack(fill='x')
                self._nav_buttons[page] = btn
                self._nav_labels[page] = label
                self._titles[page] = (title, sub)

    def show_page(self, frame):
        if frame not in self._titles:
            return
        for page in self.nb.pages:
            page.pack_forget()
        frame.pack(fill='both', expand=True)
        title, sub = self._titles[frame]
        self.page_title.configure(text=title)
        self.page_sub.configure(text=sub)
        for f, btn in self._nav_buttons.items():
            on = f is frame
            btn.configure(bg=theme.ACCENT_DARK if on else theme.SIDEBAR,
                          fg=theme.ACCENT if on else theme.MUTED,
                          font=('Segoe UI', 9, 'bold') if on else theme.BASE,
                          text=('\u258c ' if on else '') + self._nav_labels[f])
        self._current_page = frame

    def set_status(self, text, color=None):
        if hasattr(self, 'status_var'):
            self.status_var.set(text)
        if hasattr(self, 'status_dot'):
            self.status_dot.itemconfigure(self._dot, fill=color or theme.DIM)

    def _build_connection(self):
        f = self.tab_conn
        card = ttk.LabelFrame(f, text='Connection (for convert / launch)', padding=10)
        card.pack(fill='x', padx=4, pady=(4, 8))
        self.endpoint = tk.StringVar(value=self.cfg['endpoint'])
        bundled = android.bundled_adb() or ''
        self.adb = tk.StringVar(value=bundled or self.cfg['adb'])
        self.serial = tk.StringVar(value=self.cfg['serial'])
        self.device_save = tk.StringVar(value=self.cfg['device_save'])
        row = ttk.Frame(card); row.pack(fill='x')
        ttk.Label(row, text='frida endpoint (blank = USB)', style='CardMuted.TLabel').pack(side='left')
        ttk.Entry(row, textvariable=self.endpoint, width=22).pack(side='left', padx=(6, 18))
        ttk.Label(row, text='adb', style='CardMuted.TLabel').pack(side='left')
        ttk.Entry(row, textvariable=self.adb, width=70).pack(side='left', padx=6)
        row2 = ttk.Frame(card); row2.pack(fill='x', pady=(8, 0))
        ttk.Label(row2, text='serial', style='CardMuted.TLabel').pack(side='left')
        self.serial_combo = ttk.Combobox(row2, textvariable=self.serial, width=18)
        self.serial_combo.pack(side='left', padx=(6, 10))
        ttk.Button(row2, text='Detect device', command=self.on_detect_device).pack(side='left', padx=(0, 8))
        ttk.Button(row2, text='Prepare device (root + frida-server)', style='Accent.TButton', command=self.on_prepare_device).pack(side='left', padx=(0, 14))
        ttk.Label(row2, text='device save path', style='CardMuted.TLabel').pack(side='left')
        ttk.Entry(row2, textvariable=self.device_save, width=78).pack(side='left', padx=6)

        card2 = ttk.LabelFrame(f, text='Save file', padding=10)
        card2.pack(fill='x', padx=4, pady=(0, 8))
        r1 = ttk.Frame(card2); r1.pack(fill='x')
        ttk.Button(r1, text='Open save\u2026', command=self.on_open).pack(side='left')
        ttk.Button(r1, text='Find save (auto)', command=self.on_auto_detect).pack(side='left', padx=6)
        ttk.Button(r1, text='Convert encrypted\u2026', command=self.on_convert).pack(side='left', padx=6)
        ttk.Button(r1, text='Backup', command=self.on_backup).pack(side='left', padx=6)
        r2 = ttk.Frame(card2); r2.pack(fill='x', pady=(8, 0))
        ttk.Button(r2, text='Launch game (plain mode)', command=self.on_launch).pack(side='left')
        ttk.Button(r2, text='Restore encrypted save', command=self.on_restore_encrypted).pack(side='left', padx=6)
        ttk.Label(card2, text='Prefer Encrypt save: it keeps the normal ES3E container.',
                  style='CardMuted.TLabel').pack(anchor='w', pady=(8, 0))
    def _build_resources(self):
        f = self.tab_res
        cols = ('key', 'value')
        self.res_tree = ttk.Treeview(f, columns=cols, show='headings', height=20)
        for c, w in (('key', 240), ('value', 200)):
            self.res_tree.heading(c, text=c.title())
            self.res_tree.column(c, width=w, anchor='w')
        self.res_tree.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        self.res_tree.bind('<<TreeviewSelect>>', lambda e: self._res_selected())
        side = ttk.Frame(f); side.pack(side='left', fill='y', pady=6)
        ttk.Label(side, text='Selected resource:').pack(anchor='w')
        self.res_key = tk.StringVar()
        ttk.Entry(side, textvariable=self.res_key, width=26, state='readonly').pack(anchor='w', pady=2)
        ttk.Label(side, text='New value:').pack(anchor='w', pady=(8, 0))
        self.res_value = tk.StringVar()
        ttk.Entry(side, textvariable=self.res_value, width=26).pack(anchor='w', pady=2)
        ttk.Button(side, text='Set', command=self.on_set_resource).pack(anchor='w', pady=4)
        ttk.Separator(side).pack(fill='x', pady=10)
        ttk.Label(side, text='All resources at once:').pack(anchor='w')
        self.res_all = tk.StringVar(value='99999')
        ttk.Entry(side, textvariable=self.res_all, width=26).pack(anchor='w', pady=2)
        ttk.Button(side, text='Set all', command=self.on_set_all_resources).pack(anchor='w', pady=4)

    def _build_facilities(self):
        f = self.tab_fac
        cols = ('id', 'facility', 'bonus', 'mods', 'rankup')
        self.fac_tree = ttk.Treeview(f, columns=cols, show='headings', height=12)
        for c, w in (('id', 50), ('facility', 230), ('bonus', 80), ('mods', 230), ('rankup', 80)):
            self.fac_tree.heading(c, text=c.capitalize())
            self.fac_tree.column(c, width=w, anchor='w')
        self.fac_tree.pack(fill='x', padx=(4, 4), pady=(4, 6))
        self.fac_tree.bind('<<TreeviewSelect>>', lambda e: self._fac_selected())

        card = ttk.LabelFrame(f, text='Facility', padding=10)
        card.pack(fill='x', padx=4, pady=(0, 8))
        self.fac_hdr = tk.StringVar(value='(select a facility)')
        ttk.Label(card, textvariable=self.fac_hdr, style='CardHead.TLabel').pack(anchor='w')

        row = ttk.Frame(card); row.pack(fill='x', pady=(8, 0))
        ttk.Label(row, text='Facility type', style='CardMuted.TLabel', width=14).pack(side='left')
        self.fac_key = tk.StringVar()
        self.fac_key_combo = ttk.Combobox(row, textvariable=self.fac_key, width=42,
                                          values=ed.facility_catalog())
        self.fac_key_combo.pack(side='left', padx=6)

        row2 = ttk.Frame(card); row2.pack(fill='x', pady=(6, 0))
        ttk.Label(row2, text='Ability modifiers', style='CardMuted.TLabel', width=14).pack(side='left')
        self.fac_bonus = tk.StringVar()
        self.fac_bonus_combo = ttk.Combobox(row2, textvariable=self.fac_bonus, width=6,
                                            values=[str(i) for i in range(0, 11)])
        self.fac_bonus_combo.pack(side='left', padx=6)
        ttk.Label(row2, text='(bonus index: drives durability and modifier slots)',
                  style='CardMuted.TLabel').pack(side='left', padx=(4, 0))
        ttk.Label(row2, text='RankUp', style='CardMuted.TLabel', width=8).pack(side='left', padx=(18, 0))
        self.fac_rankup = tk.StringVar()
        ttk.Entry(row2, textvariable=self.fac_rankup, width=8).pack(side='left', padx=6)

        row3 = ttk.Frame(card); row3.pack(fill='x', pady=(6, 0))
        ttk.Label(row3, text='Modifications', style='CardMuted.TLabel', width=14).pack(side='left')
        self.fac_mods = tk.StringVar()
        ttk.Entry(row3, textvariable=self.fac_mods, width=52).pack(side='left', padx=6)

        row3b = ttk.Frame(card); row3b.pack(fill='x', pady=(4, 0))
        ttk.Label(row3b, text='', width=14).pack(side='left')
        self.fac_mod_pick = tk.StringVar()
        self.fac_mod_combo = ttk.Combobox(row3b, textvariable=self.fac_mod_pick, width=30,
                                          values=ed.facility_prefix_catalog())
        self.fac_mod_combo.pack(side='left', padx=6)
        ttk.Button(row3b, text='Add modification', command=self.on_add_mod).pack(side='left', padx=4)
        ttk.Button(row3b, text='Clear', command=lambda: self.fac_mods.set('')).pack(side='left')
        ttk.Label(card, text='Pick a modification from the dropdown and press Add, or type the '
                             'comma-separated keys directly. The modification count is the '
                             '"Ability Modifiers" value on the card.',
                  style='CardMuted.TLabel').pack(anchor='w', pady=(6, 0))

        row4 = ttk.Frame(card); row4.pack(fill='x', pady=(8, 0))
        ttk.Button(row4, text='Apply changes', style='Accent.TButton',
                   command=self.on_set_facility).pack(side='left')
        ttk.Button(row4, text='Clear modifications',
                   command=lambda: self.fac_mods.set('')).pack(side='left', padx=6)

    def on_prepare_device(self):
        def work():
            try:
                import dw_setup
                adb = android.find_adb(self.adb.get().strip() or None)
                devs = android.devices(adb)
                if not devs:
                    raise RuntimeError('no adb device attached - start the emulator or connect the '
                                       'phone with USB debugging')
                serial = self.serial.get().strip()
                if serial not in devs:
                    serial = devs[0]
                    self.after(0, lambda s=serial: self.serial.set(s))
                self.log('preparing device: root check, frida-server push and start…')
                res = dw_setup.prepare(adb, serial, log=self.log)
                self.log('device ready: ABI %s, pid %s' % (res.get('abi'), res.get('pid')))
                self.after(0, lambda: messagebox.showinfo('Prepare device', 'frida-server is running (%s).' % res.get('abi')))
            except Exception as e:
                self.log('prepare failed: %s' % e)
                self.after(0, lambda: messagebox.showerror('Prepare device', str(e)))
        threading.Thread(target=work, daemon=True).start()

    def on_add_mod(self):
        key = (self.fac_mod_pick.get() or '').strip()
        if not key:
            return
        mods = [m.strip() for m in self.fac_mods.get().split(',') if m.strip()]
        if key not in mods:
            mods.append(key)
        self.fac_mods.set(','.join(mods))

    def _refresh_facilities(self):
        if not hasattr(self, 'fac_tree'):
            return
        self.fac_tree.delete(*self.fac_tree.get_children())
        for i, fac in enumerate(ed.facility_spans(self.text) if self.text else []):
            info = ed.get_facility(self.text, i)
            mods = ','.join(info.get('prefixs') or [])
            if self._match(info.get('facKey'), info.get('bonus'), mods, info.get('RankUp')):
                self.fac_tree.insert('', 'end', values=(info.get('id'), info.get('facKey'),
                                                        info.get('bonus'), mods, info.get('RankUp')))

    def _fac_selected(self):
        sel = self.fac_tree.selection()
        if not sel:
            return
        row = sel[0]
        idx = self.fac_tree.index(row)
        self._fac_index = idx
        info = ed.get_facility(self.text, idx)
        self.fac_hdr.set('#%s  %s' % (info.get('id'), info.get('facKey')))
        self.fac_key.set(info.get('facKey') or '')
        self.fac_bonus.set(str(info.get('bonus') or 0))
        self.fac_rankup.set(str(info.get('RankUp') or 0))
        self.fac_mods.set(','.join(info.get('prefixs') or []))

    def on_set_facility(self):
        try:
            idx = getattr(self, '_fac_index', None)
            if idx is None:
                return
            if self.fac_key.get().strip():
                self.text = ed.set_facility_field(self.text, idx, 'facKey',
                                                  json.dumps(self.fac_key.get().strip()))
            if self.fac_bonus.get().strip():
                self.text = ed.set_facility_field(self.text, idx, 'bonus', str(int(self.fac_bonus.get())))
            mods = [m.strip() for m in self.fac_mods.get().split(',') if m.strip()]
            self.text = ed.set_facility_prefixes(self.text, idx, mods)
            if self.fac_rankup.get().strip():
                self.text = ed.set_facility_rankup(self.text, idx, int(self.fac_rankup.get()))
            self._reload_from_text()
            rows = self.fac_tree.get_children()
            if idx < len(rows):
                self.fac_tree.selection_set(rows[idx])
                self._fac_selected()
            self.log('facility %d updated (type=%s, durability=%s, mods=%s)' % (
                idx, self.fac_key.get(), self.fac_bonus.get(), ','.join(mods)))
        except Exception as e:
            messagebox.showerror('Facility', str(e))

    def _build_units(self):
        f = self.tab_units
        cols = ('idx', 'unit', 'level', 'stage', 'myth')
        self.unit_tree = ttk.Treeview(f, columns=cols, show='headings', height=22)
        for c, w in (('idx', 45), ('unit', 130), ('level', 60), ('stage', 60), ('myth', 170)):
            self.unit_tree.heading(c, text=c.capitalize())
            self.unit_tree.column(c, width=w, anchor='w')
        self.unit_tree.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        self.unit_tree.bind('<<TreeviewSelect>>', lambda e: self._unit_selected())
        side = ttk.Frame(f); side.pack(side='left', fill='y', pady=6)
        self.unit_hdr = tk.StringVar(value='(select a unit)')
        ttk.Label(side, textvariable=self.unit_hdr, font=('Segoe UI', 10, 'bold')).pack(anchor='w')

        nm = ttk.Frame(side); nm.pack(anchor='w', fill='x', pady=(4, 0))
        ttk.Label(nm, text='Custom name').pack(side='left')
        self.unit_name = tk.StringVar()
        ttk.Entry(nm, textvariable=self.unit_name, width=16).pack(side='left', padx=4)
        ttk.Button(nm, text='Set', width=5, command=self.on_set_unit_name).pack(side='left')

        var = ttk.LabelFrame(side, text='Trait (MonPrefix)')
        var.pack(anchor='w', fill='x', pady=(6, 2))
        vrow = ttk.Frame(var); vrow.pack(fill='x', pady=1)
        ttk.Label(vrow, text='Prefix', width=9).pack(side='left')
        self.unit_prefix = tk.StringVar()
        ttk.Combobox(vrow, textvariable=self.unit_prefix, values=ed.MON_PREFIXES, width=18).pack(side='left')

        v2 = ttk.LabelFrame(side, text='Variant')
        v2.pack(anchor='w', fill='x', pady=(2, 2))
        vrow1 = ttk.Frame(v2); vrow1.pack(fill='x', pady=1)
        ttk.Label(vrow1, text='Irochi', width=9).pack(side='left')
        self.unit_irochi = tk.StringVar()
        ttk.Combobox(vrow1, textvariable=self.unit_irochi, values=ed.IROCHI_TYPES, width=18).pack(side='left')
        vrow2 = ttk.Frame(v2); vrow2.pack(fill='x', pady=1)
        ttk.Label(vrow2, text='Skin', width=9).pack(side='left')
        self.unit_skin = tk.StringVar()
        ttk.Combobox(vrow2, textvariable=self.unit_skin, values=ed.UNIT_SKINS, width=18).pack(side='left')
        ttk.Button(v2, text='Set trait / variant', command=self.on_set_unit_variant).pack(anchor='w', pady=3)

        inn = ttk.LabelFrame(side, text='Innate trait')
        inn.pack(anchor='w', fill='x', pady=(2, 2))
        self.unit_innate = tk.StringVar(value='-')
        ttk.Label(inn, textvariable=self.unit_innate).pack(anchor='w', padx=4, pady=2)
        ttk.Button(inn, text='Monster replacement…', command=self.on_replace_monster).pack(anchor='w', padx=4, pady=(0, 2))
        ttk.Button(inn, text='Capture names…', command=self.on_capture_names).pack(anchor='w', padx=4, pady=(0, 2))
        ttk.Label(inn, text='Fixed by the monster type (UnitTable.strInnateBasicAction =\n'
                            '<unit>_I1). Monster replacement changes unitIdx, which also\n'
                            'changes the innate — it replaces the monster, not just the skill.',
                  foreground='#666').pack(anchor='w', padx=4, pady=(0, 2))

        prog = ttk.LabelFrame(side, text='Promotion (RankUp)')
        prog.pack(anchor='w', fill='x', pady=(2, 2))
        self.unit_vault = tk.StringVar(value='-')
        ttk.Label(prog, textvariable=self.unit_vault).pack(anchor='w', padx=4, pady=2)
        prow = ttk.Frame(prog); prow.pack(fill='x', padx=4, pady=1)
        ttk.Label(prow, text='RankUp', width=8).pack(side='left')
        self.unit_rankup = tk.StringVar()
        ttk.Entry(prow, textvariable=self.unit_rankup, width=6).pack(side='left')
        prow2 = ttk.Frame(prog); prow2.pack(fill='x', padx=4, pady=1)
        ttk.Label(prow2, text='Transcend', width=8).pack(side='left')
        self.unit_transcend = tk.StringVar()
        ttk.Entry(prow2, textvariable=self.unit_transcend, width=6).pack(side='left')
        ttk.Button(prog, text='Set promotion', command=self.on_set_promotion).pack(anchor='w', padx=4, pady=3)

        info = ttk.LabelFrame(side, text='Unit progress (USER_DATA.unitExp)')
        info.pack(anchor='w', fill='x', pady=(6, 4))
        self.unit_level = tk.StringVar()
        self.unit_essence = tk.StringVar()
        self.unit_awake = tk.StringVar()
        self.unit_train = tk.StringVar()
        for label, var in (('Level', self.unit_level), ('Essence / EXP', self.unit_essence),
                           ('Awake level', self.unit_awake), ('Training stage', self.unit_train)):
            row = ttk.Frame(info); row.pack(fill='x', pady=1)
            ttk.Label(row, text=label, width=15).pack(side='left')
            ttk.Entry(row, textvariable=var, width=10).pack(side='left')
        ttk.Button(info, text='Set unit progress', command=self.on_set_unit_progress).pack(anchor='w', pady=4)

        self.unit_stat_vars = {}
        ttk.Label(side, text='Stats (baseEft / growEft):').pack(anchor='w', pady=(8, 2))
        grid = ttk.Frame(side); grid.pack(anchor='w')
        for r, st in enumerate(EFT_STATS):
            ttk.Label(grid, text=st, width=13).grid(row=r, column=0, sticky='w')
            v = tk.StringVar()
            self.unit_stat_vars[st] = v
            ttk.Entry(grid, textvariable=v, width=12).grid(row=r, column=1, pady=1)
            ttk.Button(grid, text='set base', width=9,
                       command=lambda s=st: self.on_set_unit_stat('baseEft', s)).grid(row=r, column=2, padx=2)
            ttk.Button(grid, text='set grow', width=9,
                       command=lambda s=st: self.on_set_unit_stat('growEft', s)).grid(row=r, column=3)

        ttk.Label(side, text='Awake (awakeEft vault):').pack(anchor='w', pady=(10, 2))
        ag = ttk.Frame(side); ag.pack(anchor='w')
        self.awake_vars = {}
        for i, st in enumerate(STATS):
            ttk.Label(ag, text=st, width=9).grid(row=i // 4, column=(i % 4) * 2, sticky='w')
            v = tk.StringVar(value='0')
            self.awake_vars[st] = v
            ttk.Entry(ag, textvariable=v, width=5).grid(row=i // 4, column=(i % 4) * 2 + 1, padx=(0, 6))
        ttk.Button(side, text='Set awake stats', command=self.on_set_awake).pack(anchor='w', pady=4)

    def _build_abilities(self):
        f = self.tab_abil
        left = ttk.Frame(f); left.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        ttk.Label(left, text='Monster').pack(anchor='w')
        self.abil_tree = ttk.Treeview(left, columns=('idx', 'unit'), show='headings', height=24)
        self.abil_tree.heading('idx', text='#')
        self.abil_tree.heading('unit', text='Unit')
        self.abil_tree.column('idx', width=45, anchor='w')
        self.abil_tree.column('unit', width=160, anchor='w')
        self.abil_tree.pack(fill='both', expand=True)
        self.abil_tree.bind('<<TreeviewSelect>>', lambda e: self._abil_selected())

        right = ttk.Frame(f); right.pack(side='left', fill='y', pady=6)
        self.abil_hdr = tk.StringVar(value='(select a monster)')
        ttk.Label(right, textvariable=self.abil_hdr, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(right, text='Equipped parts (M1 / S1 / S2):').pack(anchor='w', pady=(8, 2))
        self.abil_parts = ttk.Treeview(right, columns=('slot', 'key'), show='headings', height=4)
        self.abil_parts.heading('slot', text='Slot')
        self.abil_parts.heading('key', text='Part key')
        self.abil_parts.column('slot', width=50, anchor='w')
        self.abil_parts.column('key', width=230, anchor='w')
        self.abil_parts.pack(anchor='w')
        self.abil_parts.bind('<<TreeviewSelect>>', lambda e: self._part_selected())

        ttk.Label(right, text='New key (type or pick):').pack(anchor='w', pady=(8, 2))
        self.abil_key = tk.StringVar()
        self.abil_combo = ttk.Combobox(right, textvariable=self.abil_key, width=30)
        self.abil_combo.pack(anchor='w')
        ttk.Button(right, text='Set selected slot', command=self.on_set_part).pack(anchor='w', pady=4)

        ttk.Separator(right).pack(fill='x', pady=8)
        ttk.Label(right, text='Clone abilities from:').pack(anchor='w')
        self.abil_src = tk.StringVar()
        self.abil_src_combo = ttk.Combobox(right, textvariable=self.abil_src, width=30, state='readonly')
        self.abil_src_combo.pack(anchor='w', pady=2)
        ttk.Button(right, text='Clone into this monster', command=self.on_clone_parts).pack(anchor='w', pady=4)
        ttk.Button(right, text='Dump part keys (game running)', command=self.on_dump_parts).pack(anchor='w', pady=4)
        ttk.Label(right, text='B (innate) and the Epic Trait come from the monster type /\nmyth, not from the save; '
                              'M1/S1/S2 are the equippable parts.', foreground='#666').pack(anchor='w', pady=(10, 0))

    def _refresh_abilities(self):
        if not hasattr(self, 'abil_tree'):
            return
        self.abil_tree.delete(*self.abil_tree.get_children())
        for i, u in enumerate(self.obj.get('USER_DATA.m_Units', {}).get('value') or []):
            key = u.get('unitIdx')
            name = u.get('customName') or getattr(self, 'names', {}).get(key) or key
            if self._match(name, key):
                self.abil_tree.insert('', 'end', values=(i, name))
        self.abil_src_combo['values'] = ['#%d %s' % (i, u.get('unitIdx'))
                                         for i, u in enumerate(self.obj.get('USER_DATA.m_Units', {}).get('value') or [])]
        try:
            catalog = ed.part_catalog(self.obj)
        except Exception:
            catalog = []
        self.abil_combo['values'] = catalog

    def _abil_selected(self):
        sel = self.abil_tree.selection()
        if not sel:
            return
        idx = int(self.abil_tree.item(sel[0], 'values')[0])
        self._abil_unit = idx
        u = (self.obj.get('USER_DATA.m_Units', {}).get('value') or [])[idx]
        self.abil_hdr.set('#%d  %s' % (idx, u.get('unitIdx')))
        self.abil_parts.delete(*self.abil_parts.get_children())
        for i, p in enumerate(u.get('parts') or []):
            self.abil_parts.insert('', 'end', values=(i, p.get('key')))

    def _part_selected(self):
        sel = self.abil_parts.selection()
        if sel:
            slot, key = self.abil_parts.item(sel[0], 'values')
            self._part_slot = int(slot)
            self.abil_key.set(key)

    def _select_abil_unit(self, idx):
        for row in self.abil_tree.get_children():
            if int(self.abil_tree.item(row, 'values')[0]) == idx:
                self.abil_tree.selection_set(row)
                self._abil_selected()
                return

    def on_set_part(self):
        try:
            idx = getattr(self, '_abil_unit', None)
            slot = getattr(self, '_part_slot', None)
            key = self.abil_key.get().strip()
            if idx is None or slot is None or not key:
                return
            parts = ed.unit_parts(self.text, idx)
            if slot >= len(parts):
                raise IndexError('slot %d out of range' % slot)
            parts[slot]['key'] = key
            self.text = ed.set_unit_parts(self.text, idx, parts)
            self._reload_from_text()
            self._select_abil_unit(idx)
            self.abil_parts.selection_set(self.abil_parts.get_children()[slot])
            self._part_selected()
            self.log('unit %d slot %d = %s' % (idx, slot, key))
        except Exception as e:
            messagebox.showerror('Set part', str(e))

    def on_clone_parts(self):
        try:
            idx = getattr(self, '_abil_unit', None)
            if idx is None:
                return
            src_txt = self.abil_src.get()
            if not src_txt:
                return
            src = int(src_txt.split()[0][1:])
            self.text = ed.copy_unit_parts(self.text, src, idx)
            self._reload_from_text()
            self._select_abil_unit(idx)
            self.log('copied abilities from #%d to #%d' % (src, idx))
        except Exception as e:
            messagebox.showerror('Clone abilities', str(e))

    def _build_darklord(self):
        f = self.tab_dl
        cols = ('key', 'unlocked', 'level', 'token', 'basic')
        self.dl_tree = ttk.Treeview(f, columns=cols, show='headings', height=10)
        for c, w in (('key', 140), ('unlocked', 90), ('level', 70), ('token', 100), ('basic', 70)):
            self.dl_tree.heading(c, text=c.capitalize())
            self.dl_tree.column(c, width=w, anchor='w')
        self.dl_tree.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        self.dl_tree.bind('<<TreeviewSelect>>', lambda e: self._dl_selected())

        side = ttk.Frame(f); side.pack(side='left', fill='y', pady=6)
        self.dl_hdr = tk.StringVar(value='(select a Dark Lord form)')
        ttk.Label(side, textvariable=self.dl_hdr, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(side, text='USER_DATA.mwExp — one entry per Dark Lord form (key = monster).').pack(anchor='w')
        grid = ttk.Frame(side); grid.pack(anchor='w', pady=(8, 2))
        self.dl_unlocked = tk.StringVar()
        self.dl_level = tk.StringVar()
        self.dl_token = tk.StringVar()
        for r, (label, var) in enumerate((('UNLOCKED', self.dl_unlocked), ('LEVEL', self.dl_level),
                                          ('TOKEN', self.dl_token))):
            ttk.Label(grid, text=label, width=10).grid(row=r, column=0, sticky='w')
            ttk.Entry(grid, textvariable=var, width=10).grid(row=r, column=1, pady=1)
        ttk.Button(side, text='Apply to selected form', command=self.on_set_darklord).pack(anchor='w', pady=4)
        ttk.Button(side, text='Unlock all forms', command=self.on_unlock_all_darklords).pack(anchor='w')
        ttk.Separator(side).pack(fill='x', pady=6)
        ttk.Label(side, text='Aspect enhancement (UpgAspe)').pack(anchor='w')
        arow = ttk.Frame(side); arow.pack(anchor='w', pady=1)
        ttk.Label(arow, text='Aspect', width=8).pack(side='left')
        self.aspe_key = tk.StringVar(value='Basic')
        self.aspe_combo = ttk.Combobox(arow, textvariable=self.aspe_key, values=['Basic'], width=12)
        self.aspe_combo.pack(side='left')
        arow2 = ttk.Frame(side); arow2.pack(anchor='w', pady=1)
        ttk.Label(arow2, text='Stage', width=8).pack(side='left')
        self.aspe_val = tk.StringVar()
        ttk.Entry(arow2, textvariable=self.aspe_val, width=8).pack(side='left')
        ttk.Button(side, text='Set aspect stage', command=self.on_set_aspect).pack(anchor='w', pady=3)
        ttk.Label(side, text='Authority enhancement (lcUpg)').pack(anchor='w', pady=(6, 0))
        self.lc_tree = ttk.Treeview(side, columns=('key', 'lvl'), show='headings', height=7)
        self.lc_tree.heading('key', text='Ability')
        self.lc_tree.heading('lvl', text='Stage')
        self.lc_tree.column('key', width=120, anchor='w')
        self.lc_tree.column('lvl', width=50, anchor='w')
        self.lc_tree.pack(anchor='w', fill='x')
        self.lc_tree.bind('<<TreeviewSelect>>', lambda e: self._lc_selected())
        lrow = ttk.Frame(side); lrow.pack(anchor='w', pady=2)
        ttk.Label(lrow, text='Stage', width=6).pack(side='left')
        self.lc_val = tk.StringVar()
        ttk.Entry(lrow, textvariable=self.lc_val, width=8).pack(side='left')
        ttk.Button(side, text='Set ability stage', command=self.on_set_lc).pack(anchor='w')
        ttk.Separator(side).pack(fill='x', pady=6)
        ttk.Label(side, text='Dark Lord skin (lastPlaySkin)').pack(anchor='w')
        srow = ttk.Frame(side); srow.pack(anchor='w', pady=1)
        ttk.Label(srow, text='Unit', width=8).pack(side='left')
        self.mwskin_unit = tk.StringVar()
        self.mwskin_unit_combo = ttk.Combobox(srow, textvariable=self.mwskin_unit, width=14)
        self.mwskin_unit_combo.pack(side='left')
        srow2 = ttk.Frame(side); srow2.pack(anchor='w', pady=1)
        ttk.Label(srow2, text='Skin', width=8).pack(side='left')
        self.mwskin_name = tk.StringVar(value='MOONVEIL')
        ttk.Combobox(srow2, textvariable=self.mwskin_name,
                     values=['None', 'MOONVEIL', 'WEDDING'], width=14).pack(side='left')
        ttk.Button(side, text='Set skin', command=self.on_set_mw_skin).pack(anchor='w', pady=3)
        ttk.Button(side, text='Set for all Dark Lords', command=self.on_set_mw_skin_all).pack(anchor='w')
        ttk.Separator(side).pack(fill='x', pady=8)
        ttk.Label(side, text='Active Dark Lord (PlayerPrefs CurrentPlayMW)').pack(anchor='w')
        self.dl_active = tk.StringVar()
        self.dl_active_combo = ttk.Combobox(side, textvariable=self.dl_active, values=[], width=16)
        self.dl_active_combo.pack(anchor='w', pady=2)
        rowb = ttk.Frame(side); rowb.pack(anchor='w')
        ttk.Button(rowb, text='Read current', command=self.on_read_active_darklord).pack(side='left')
        ttk.Button(rowb, text='Set active (stops game)', command=self.on_set_active_darklord).pack(side='left', padx=4)
        ttk.Label(side, text='The game reads this on launch; it is stored outside save.es3.', foreground='#666').pack(anchor='w', pady=(6, 0))
        ttk.Label(side, text='The game picks the Dark Lord in the Dark Lord\'s Quarters; this edits\n'
                             'which forms are unlocked and their level/tokens.', foreground='#666').pack(anchor='w', pady=(8, 0))

    def _refresh_darklord(self):
        if not hasattr(self, 'dl_tree'):
            return
        self.dl_tree.delete(*self.dl_tree.get_children())
        for i, e in enumerate(self.obj.get('USER_DATA.mwExp', {}).get('value') or []):
            st = (e.get('storage') or {}).get('values') or {}
            basic = ((e.get('UpgAspe') or {}).get('values') or {}).get('Basic', '')
            if self._match(e.get('key'), st.get('LEVEL')):
                self.dl_tree.insert('', 'end', values=(e.get('key'), st.get('UNLOCKED'), st.get('LEVEL'),
                                                       st.get('TOKEN'), basic))

    def _dl_selected(self):
        sel = self.dl_tree.selection()
        if not sel:
            return
        vals = self.dl_tree.item(sel[0], 'values')
        self._dl_index = int(self.dl_tree.index(sel[0]))
        self.dl_hdr.set('%s' % vals[0])
        self.dl_unlocked.set(vals[1])
        self.dl_level.set(vals[2])
        self.dl_token.set(vals[3])
        try:
            aspe = ed.get_mw_vault(self.text, self._dl_index, 'UpgAspe')
            lc = ed.get_mw_vault(self.text, self._dl_index, 'lcUpg')
        except Exception:
            aspe, lc = {}, {}
        self.aspe_combo['values'] = sorted(aspe) or ['Basic']
        if self.aspe_key.get() not in aspe and aspe:
            self.aspe_key.set(sorted(aspe)[0])
        self.aspe_val.set(str(aspe.get(self.aspe_key.get(), 0)))
        self.lc_tree.delete(*self.lc_tree.get_children())
        for k, v in lc.items():
            if self._match(k, v):
                self.lc_tree.insert('', 'end', values=(k, v))

    def _refresh_mw_skins(self):
        if not hasattr(self, 'mwskin_unit_combo'):
            return
        try:
            skins = ed.get_last_skins(self.text)
        except Exception:
            skins = {}
        forms = [e.get('key') for e in (self.obj.get('USER_DATA.mwExp', {}).get('value') or [])]
        keys = sorted(set(list(skins.keys()) + [f.lower() for f in forms if f]))
        self.mwskin_unit_combo['values'] = keys
        if not self.mwskin_unit.get() and keys:
            self.mwskin_unit.set(keys[0])
        self._mwskin_map = skins

    def on_set_mw_skin(self):
        try:
            unit = (self.mwskin_unit.get() or '').strip().lower()
            if not unit:
                return
            self.text = ed.set_last_skin(self.text, unit, self.mwskin_name.get().strip() or 'None')
            self._reload_from_text()
            self.log('skin %s = %s' % (unit, self.mwskin_name.get()))
        except Exception as e:
            messagebox.showerror('Dark Lord skin', str(e))

    def on_set_mw_skin_all(self):
        try:
            name = self.mwskin_name.get().strip() or 'None'
            for e in (self.obj.get('USER_DATA.mwExp', {}).get('value') or []):
                key = (e.get('key') or '').lower()
                if key:
                    self.text = ed.set_last_skin(self.text, key, name)
            self._reload_from_text()
            self.log('all Dark Lord skins set to %s' % name)
        except Exception as e:
            messagebox.showerror('Dark Lord skin', str(e))

    def _lc_selected(self):
        sel = self.lc_tree.selection()
        if not sel:
            return
        k, v = self.lc_tree.item(sel[0], 'values')
        self._lc_key = k
        self.lc_val.set(str(v))

    def on_set_aspect(self):
        try:
            idx = getattr(self, '_dl_index', None)
            if idx is None:
                return
            key = self.aspe_key.get().strip() or 'Basic'
            self.text = ed.set_mw_vault(self.text, idx, 'UpgAspe', key, int(self.aspe_val.get()))
            self._reload_from_text()
            self._select_dl(idx)
            self.log('aspect %s stage = %s (form %d)' % (key, self.aspe_val.get(), idx))
        except Exception as e:
            messagebox.showerror('Aspect', str(e))

    def on_set_lc(self):
        try:
            idx = getattr(self, '_dl_index', None)
            key = getattr(self, '_lc_key', None)
            if idx is None or not key:
                return
            self.text = ed.set_mw_vault(self.text, idx, 'lcUpg', key, int(self.lc_val.get()))
            self._reload_from_text()
            self._select_dl(idx)
            self.log('%s stage = %s (form %d)' % (key, self.lc_val.get(), idx))
        except Exception as e:
            messagebox.showerror('Authority', str(e))

    def on_set_darklord(self):
        try:
            idx = getattr(self, '_dl_index', None)
            if idx is None:
                return
            if self.dl_unlocked.get().strip():
                self.text = ed.set_mw_field(self.text, idx, 'UNLOCKED', int(self.dl_unlocked.get()))
            if self.dl_level.get().strip():
                self.text = ed.set_mw_field(self.text, idx, 'LEVEL', int(self.dl_level.get()))
            if self.dl_token.get().strip():
                self.text = ed.set_mw_field(self.text, idx, 'TOKEN', int(self.dl_token.get()))
            self._reload_from_text()
            self._select_dl(idx)
            self.log('dark lord form %d updated' % idx)
        except Exception as e:
            messagebox.showerror('Dark Lord', str(e))

    def on_unlock_all_darklords(self):
        try:
            for i in range(len(ed.mw_spans(self.text))):
                self.text = ed.set_mw_field(self.text, i, 'UNLOCKED', 1)
            self._reload_from_text()
            self.log('all dark lord forms unlocked')
        except Exception as e:
            messagebox.showerror('Dark Lord', str(e))

    def _select_dl(self, idx):
        rows = self.dl_tree.get_children()
        if 0 <= idx < len(rows):
            self.dl_tree.selection_set(rows[idx])
            self._dl_selected()

    def _app_uid(self, adb, serial):
        rc, out, _ = android.adb(adb, serial, 'shell', 'dumpsys', 'package', android.PACKAGE, timeout=20)
        import re
        m = re.search(r'userId=(\d+)', out or '')
        return m.group(1) if m else None

    def on_read_active_darklord(self):
        def work():
            try:
                adb, serial = self._device_serial()
                cur = android.get_player_pref(adb, serial, 'CurrentPlayMW')
                forms = [self.dl_tree.item(r, 'values')[0] for r in self.dl_tree.get_children()]
                self.after(0, lambda: (self.dl_active.set(cur or ''), self.dl_active_combo.configure(values=forms)))
                self.log('CurrentPlayMW = %s' % cur)
            except Exception as e:
                self.log('read active dark lord failed: %s' % e)
                self.after(0, lambda: messagebox.showerror('Dark Lord', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def on_set_active_darklord(self):
        value = self.dl_active.get().strip()
        if not value:
            return

        def work():
            try:
                adb, serial = self._device_serial()
                uid = self._app_uid(adb, serial)
                android.set_player_pref(adb, serial, 'CurrentPlayMW', value, uid=uid)
                got = android.get_player_pref(adb, serial, 'CurrentPlayMW')
                self.log('CurrentPlayMW set to %s (read back: %s)' % (value, got))
                self.after(0, lambda: messagebox.showinfo(
                    'Dark Lord', 'Active Dark Lord set to %s.\nStart the game to see it.' % got))
            except Exception as e:
                self.log('set active dark lord failed: %s' % e)
                self.after(0, lambda: messagebox.showerror('Dark Lord', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def on_dump_parts(self):
        def work():
            try:
                import dw_dump_parts
                items = dw_dump_parts.dump(log=self.log)
                keys = sorted({it['path'] for it in items if it.get('path')})
                self.log('dumped %d table objects, %d unique paths -> %s' % (
                    len(items), len(keys), dw_dump_parts.DUMP_PATH))
            except Exception as e:
                self.log('dump failed: %s' % e)
                self.after(0, lambda: messagebox.showerror('Dump parts', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _build_variants(self):
        f = self.tab_var
        cols = ('unit', 'none', 'betray', 'log')
        self.var_tree = ttk.Treeview(f, columns=cols, show='headings', height=22)
        for c, w in (('unit', 120), ('none', 70), ('betray', 70), ('log', 220)):
            self.var_tree.heading(c, text=c.capitalize())
            self.var_tree.column(c, width=w, anchor='w')
        self.var_tree.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        self.var_tree.bind('<<TreeviewSelect>>', lambda e: self._var_selected())

        side = ttk.Frame(f); side.pack(side='left', fill='y', pady=6)
        self.var_hdr = tk.StringVar(value='(select a monster)')
        ttk.Label(side, textvariable=self.var_hdr, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(side, text='USER_DATA.irochiLog — variants stored per monster').pack(anchor='w')

        box = ttk.LabelFrame(side, text='Stored variants')
        box.pack(anchor='w', fill='x', pady=(8, 4))
        row = ttk.Frame(box); row.pack(fill='x', pady=2)
        ttk.Label(row, text='Type', width=8).pack(side='left')
        self.var_type = tk.StringVar(value='BETRAY')
        ttk.Combobox(row, textvariable=self.var_type, values=['NONE', 'BETRAY'], width=10).pack(side='left')
        row2 = ttk.Frame(box); row2.pack(fill='x', pady=2)
        ttk.Label(row2, text='Count', width=8).pack(side='left')
        self.var_count = tk.StringVar()
        ttk.Entry(row2, textvariable=self.var_count, width=10).pack(side='left')
        ttk.Button(box, text='Set count', command=self.on_set_variant_count).pack(anchor='w', pady=3)

        box2 = ttk.LabelFrame(side, text='Variant research (irochiResearch)')
        box2.pack(anchor='w', fill='x', pady=(6, 4))
        row3 = ttk.Frame(box2); row3.pack(fill='x', pady=2)
        ttk.Label(row3, text='Monster', width=8).pack(side='left')
        self.res_unit = tk.StringVar()
        self.res_unit_combo = ttk.Combobox(row3, textvariable=self.res_unit, width=14, state='readonly')
        self.res_unit_combo.pack(side='left')
        self.res_unit_combo.bind('<<ComboboxSelected>>', lambda e: self._refresh_research())
        row4 = ttk.Frame(box2); row4.pack(fill='x', pady=2)
        ttk.Label(row4, text='Stat', width=8).pack(side='left')
        self.res_stat = tk.StringVar(value='MaxHP')
        ttk.Combobox(row4, textvariable=self.res_stat,
                     values=['MaxHP', 'STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'], width=10).pack(side='left')
        row5 = ttk.Frame(box2); row5.pack(fill='x', pady=2)
        ttk.Label(row5, text='Value', width=8).pack(side='left')
        self.res_value = tk.StringVar()
        ttk.Entry(row5, textvariable=self.res_value, width=10).pack(side='left')
        ttk.Button(box2, text='Set research', command=self.on_set_variant_research).pack(anchor='w', pady=3)
        self.res_current = tk.StringVar(value='(none)')
        ttk.Label(box2, textvariable=self.res_current, foreground='#444').pack(anchor='w')

    def _refresh_variants(self):
        if not hasattr(self, 'var_tree'):
            return
        self.var_tree.delete(*self.var_tree.get_children())
        log = self.obj.get('USER_DATA.irochiLog', {}).get('value') or {}
        for user, ent in log.items():
            cnt = ((ent.get('count') or {}).get('values') or {})
            logv = ','.join(ent.get('log') or [])
            if self._match(user, logv):
                self.var_tree.insert('', 'end', values=(user, cnt.get('NONE', 0), cnt.get('BETRAY', 0), logv))
        units = [e.get('key') for e in (self.obj.get('USER_DATA.unitExp', {}).get('value') or [])]
        self.res_unit_combo['values'] = units
        if units and not self.res_unit.get():
            self.res_unit.set(units[0])

    def _var_selected(self):
        sel = self.var_tree.selection()
        if not sel:
            return
        vals = self.var_tree.item(sel[0], 'values')
        self._var_user = vals[0]
        self.var_hdr.set(str(vals[0]))
        self.var_count.set(str(vals[2]))

    def _refresh_research(self):
        try:
            cur = ed.get_irochi_research(self.text, self.res_unit.get().strip())
            self.res_current.set(str(cur) if cur else '(none)')
        except Exception:
            self.res_current.set('(none)')

    def on_set_variant_count(self):
        try:
            user = getattr(self, '_var_user', None)
            if not user:
                return
            self.text = ed.set_irochi_count(self.text, user, self.var_type.get().strip(),
                                            int(self.var_count.get()))
            self._reload_from_text()
            self.log('variants %s %s = %s' % (user, self.var_type.get(), self.var_count.get()))
        except Exception as e:
            messagebox.showerror('Variants', str(e))

    def on_set_variant_research(self):
        try:
            unit = self.res_unit.get().strip()
            if not unit:
                return
            self.text = ed.set_irochi_research(self.text, unit, self.res_stat.get().strip(),
                                               int(self.res_value.get()))
            self._refresh_research()
            self._reload_from_text()
            self.log('research %s %s = %s' % (unit, self.res_stat.get(), self.res_value.get()))
        except Exception as e:
            messagebox.showerror('Variant research', str(e))

    def _build_collections(self):
        f = self.tab_col
        self.col_tree = ttk.Treeview(f, columns=('key', 'count'), show='headings', height=22)
        self.col_tree.heading('key', text='Collection')
        self.col_tree.heading('count', text='Collected')
        self.col_tree.column('key', width=180, anchor='w')
        self.col_tree.column('count', width=100, anchor='w')
        self.col_tree.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        self.col_tree.bind('<<TreeviewSelect>>', lambda e: self._col_selected())

        side = ttk.Frame(f); side.pack(side='left', fill='y', pady=6)
        ttk.Label(side, text='Collections', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(side, text='USER_DATA.collections — costume / codex unlock progress.\n'
                             'Raising a count completes its collection set.',
                  justify='left').pack(anchor='w')
        self.col_sel = tk.StringVar(value='(select a collection)')
        ttk.Label(side, textvariable=self.col_sel).pack(anchor='w', pady=(8, 2))
        row = ttk.Frame(side); row.pack(anchor='w')
        ttk.Label(row, text='Count', width=8).pack(side='left')
        self.col_value = tk.StringVar()
        ttk.Entry(row, textvariable=self.col_value, width=10).pack(side='left')
        ttk.Button(side, text='Set count', command=self.on_set_collection).pack(anchor='w', pady=4)
        ttk.Button(side, text='Max all (999)', command=self.on_max_collections).pack(anchor='w')
        ttk.Label(side, text='Only collections already present in the save can be\n'
                             'raised; unknown enum keys would break the load.',
                  foreground='#666').pack(anchor='w', pady=(8, 0))

    def _refresh_collections(self):
        if not hasattr(self, 'col_tree'):
            return
        self.col_tree.delete(*self.col_tree.get_children())
        for k, v in (ed.get_collections(self.text) if self.text else {}).items():
            if k == 'MAX':
                continue
            if self._match(k, v):
                self.col_tree.insert('', 'end', values=(k, v))

    def _col_selected(self):
        sel = self.col_tree.selection()
        if not sel:
            return
        k, v = self.col_tree.item(sel[0], 'values')
        self._col_key = k
        self.col_sel.set(str(k))
        self.col_value.set(str(v))

    def on_set_collection(self):
        try:
            key = getattr(self, '_col_key', None)
            if not key:
                return
            self.text = ed.set_collection(self.text, key, int(self.col_value.get()))
            self._reload_from_text()
            self.log('collection %s = %s' % (key, self.col_value.get()))
        except Exception as e:
            messagebox.showerror('Collection', str(e))

    def on_max_collections(self):
        try:
            for k in list(ed.get_collections(self.text)):
                if k == 'MAX':
                    continue
                self.text = ed.set_collection(self.text, k, 999)
            self._reload_from_text()
            self.log('all collections set to 999')
        except Exception as e:
            messagebox.showerror('Collection', str(e))

    def _build_mementos(self):
        f = self.tab_mem
        cols = ('key', 'buy')
        self.mem_tree = ttk.Treeview(f, columns=cols, show='headings', height=22)
        for c, w in (('key', 300), ('buy', 100)):
            self.mem_tree.heading(c, text='Key' if c == 'key' else 'Buy count')
            self.mem_tree.column(c, width=w, anchor='w')
        self.mem_tree.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)
        self.mem_tree.bind('<<TreeviewSelect>>', lambda e: self._mem_selected())
        side = ttk.Frame(f); side.pack(side='left', fill='y', pady=6)
        self.mem_key = tk.StringVar()
        ttk.Label(side, text='Selected memento:').pack(anchor='w')
        ttk.Entry(side, textvariable=self.mem_key, width=28, state='readonly').pack(anchor='w', pady=2)
        ttk.Label(side, text='Buy count:').pack(anchor='w', pady=(8, 0))
        self.mem_count = tk.StringVar()
        ttk.Entry(side, textvariable=self.mem_count, width=28).pack(anchor='w', pady=2)
        ttk.Button(side, text='Set', command=self.on_set_memento).pack(anchor='w', pady=4)

    def _build_advanced(self):
        f = self.tab_adv
        ttk.Label(f, text='Path (e.g. USER_DATA.runCount):').pack(anchor='w', padx=8, pady=(8, 0))
        self.adv_path = tk.StringVar()
        ttk.Entry(f, textvariable=self.adv_path, width=60).pack(anchor='w', padx=8)
        row = ttk.Frame(f); row.pack(anchor='w', padx=8, pady=6)
        ttk.Button(row, text='Get', command=self.on_adv_get).pack(side='left')
        ttk.Button(row, text='Set JSON literal', command=self.on_adv_set).pack(side='left', padx=6)
        ttk.Label(f, text='Value / JSON:').pack(anchor='w', padx=8)
        self.adv_text = tk.Text(f, height=18)
        theme.style_text(self.adv_text)
        self.adv_text.pack(fill='both', expand=True, padx=8, pady=(0, 8))

    def _build_log(self):
        f = self.tab_log
        self.log_text = tk.Text(f, height=20, state='disabled')
        theme.style_text(self.log_text, wrap='word')
        self.log_text.pack(fill='both', expand=True, padx=8, pady=8)

    # ------------------------------------------------------------- helpers
    def log(self, msg):
        def run():
            self.log_text.configure(state='normal')
            self.log_text.insert('end', time.strftime('[%H:%M:%S] ') + str(msg) + '\n')
            self.log_text.see('end')
            self.log_text.configure(state='disabled')
        try:
            self.after(0, run)
        except Exception:
            pass

    def _refresh_all(self):
        if self.obj is None:
            return
        try:
            self.innate_set = set(ed.innate_keys(self.obj))
        except Exception:
            self.innate_set = set()
        self._refresh_resources()
        self._refresh_facilities()
        self._refresh_units()
        self._refresh_abilities()
        self._refresh_darklord()
        self._refresh_variants()
        self._refresh_collections()
        self._refresh_mw_skins()
        self._refresh_mementos()

    def _match(self, *vals):
        fv = getattr(self, 'filter_var', None)
        if fv is None:
            return True
        q = fv.get().strip().lower()
        if not q:
            return True
        return any(q in str(v).lower() for v in vals if v is not None)

    def on_filter_changed(self):
        if getattr(self, 'obj', None) is None:
            return
        self._refresh_all()

    def _refresh_resources(self):
        self.res_tree.delete(*self.res_tree.get_children())
        st = self.obj.get('USER_DATA.storage', {}).get('value') or {}
        for k, v in (st.get('values') or {}).items():
            if self._match(k, v):
                self.res_tree.insert('', 'end', values=(k, v))

    def _refresh_units(self):
        self.unit_tree.delete(*self.unit_tree.get_children())
        self.exp_map = {}
        for ent in self.obj.get('USER_DATA.unitExp', {}).get('value') or []:
            vals = ((ent.get('storage') or {}).get('values') or {})
            self.exp_map[ent.get('key')] = vals
        for i, u in enumerate(self.obj.get('USER_DATA.m_Units', {}).get('value') or []):
            key = u.get('unitIdx')
            ev = self.exp_map.get(key) or {}
            name = u.get('customName') or getattr(self, 'names', {}).get(key) or key
            if self._match(name, key, ev.get('LEVEL'), u.get('mythType'), u.get('mythLevel')):
                self.unit_tree.insert('', 'end', values=(i, name, ev.get('LEVEL'), ev.get('TRAIN_LEVEL'),
                                                         '%s %s' % (u.get('mythType'), u.get('mythLevel'))))

    def _refresh_mementos(self):
        self.mem_tree.delete(*self.mem_tree.get_children())
        for m in self.obj.get('USER_DATA.mementos', {}).get('value') or []:
            if self._match(m.get('key'), m.get('buyCount')):
                self.mem_tree.insert('', 'end', values=(m.get('key'), m.get('buyCount')))

    def _res_selected(self):
        sel = self.res_tree.selection()
        if sel:
            k, v = self.res_tree.item(sel[0], 'values')
            self.res_key.set(k)
            self.res_value.set(v)

    def _unit_selected(self):
        sel = self.unit_tree.selection()
        if not sel:
            return
        idx = int(self.unit_tree.item(sel[0], 'values')[0])
        u = (self.obj.get('USER_DATA.m_Units', {}).get('value') or [])[idx]
        key = u.get('unitIdx')
        ev = getattr(self, 'exp_map', {}).get(key) or {}
        self.unit_hdr.set('#%d  %s%s' % (idx, key, ('  (%s)' % u.get('customName')) if u.get('customName') else ''))
        self.unit_name.set(u.get('customName') or '')
        self.unit_prefix.set(u.get('prefix') or '')
        self.unit_skin.set(u.get('skin') or '')
        self.unit_irochi.set(u.get('Irochi') or 'NONE')
        innate = key + '_I1'
        known = innate in getattr(self, 'innate_set', set())
        self.unit_innate.set('%s  (%s)' % (innate, 'recorded in AbilityLog' if known else 'not in AbilityLog'))
        try:
            vault = ed.get_unit_vault(self.text, idx)
        except Exception:
            vault = {}
        self.unit_vault.set('RankUp %s  Transcend %s  CallUp %s  GMO %s' % (
            vault.get('RankUp', 0), vault.get('TRANSCEND', 0), vault.get('CALLUP', 0), vault.get('GMO', 0)))
        self.unit_rankup.set(str(vault.get('RankUp', 0)))
        self.unit_transcend.set(str(vault.get('TRANSCEND', 0)))
        self.unit_level.set(str(ev.get('LEVEL', 0)))
        self.unit_essence.set(str(ev.get('EXP', 0)))
        self.unit_awake.set(str(ev.get('AWAKE_LEVEL', 0)))
        self.unit_train.set(str(ev.get('TRAIN_LEVEL', 0)))
        for st in EFT_STATS:
            self.unit_stat_vars[st].set(str((u.get('baseEft') or {}).get(st, '')))
        for st in STATS:
            self.awake_vars[st].set(str(((u.get('awakeEft') or {}).get('values') or {}).get(st, 0)))
        self._selected_unit = idx
        self._selected_unit_key = key

    def _mem_selected(self):
        sel = self.mem_tree.selection()
        if sel:
            k, v = self.mem_tree.item(sel[0], 'values')
            self.mem_key.set(k)
            self.mem_count.set(v)

    def _reload_from_text(self, keep_selection=True):
        self.obj = ed.parse(self.text)
        self._refresh_all()

    def _unit_span(self, idx):
        spans = ed.unit_element_spans(self.text)
        if idx < 0 or idx >= len(spans):
            raise IndexError('unit index out of range')
        return spans[idx]

    # ------------------------------------------------------- auto detection
    def _find_adb(self):
        return android.find_adb(self.adb.get().strip() or None)

    def _adb(self, adb, serial, *args, timeout=25):
        rc, out, err = android.adb(adb, serial, *args, timeout=timeout)
        class R:
            returncode = rc
            stdout = out
            stderr = err
        return R()

    def _local_candidates(self):
        import glob
        roots = [
            os.path.join(os.path.expanduser('~'), 'Downloads'),
            os.path.join(os.path.expanduser('~'), 'OneDrive', 'Documents', 'MuMuSharedFolder', 'Download'),
            os.path.join(os.path.expanduser('~'), 'Desktop'),
            os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)),
        ]
        seen = []
        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for name in ('*.es3', 'save*.json', '*plain*.json'):
                    for p in glob.glob(os.path.join(root, name)):
                        seen.append(p)
            except Exception:
                pass
        seen.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return seen

    def on_detect_device(self):
        adb_hint = self.adb.get().strip()
        serial_hint = self.serial.get().strip()

        def work():
            try:
                adb = android.find_adb(adb_hint or None)
                if not adb:
                    raise RuntimeError('adb not found; install platform-tools or set the path')
                devs = android.devices(adb)
                if not devs:
                    raise RuntimeError('no adb device attached - start the emulator (or connect the phone with USB debugging) and press Detect device again')
                serial = serial_hint if serial_hint in devs else devs[0]
                info = android.device_info(adb, serial)
                path = android.find_save_path(adb, serial)

                def apply():
                    self.adb.set(adb)
                    self.serial_combo['values'] = devs
                    self.serial.set(serial)
                    if path:
                        self.device_save.set(path)
                self.after(0, apply)
                self.log('device %s: Dungeon Within %s, ABI %s, save %s' % (
                    serial, info.get('version') or '?', info.get('abi') or '?', path or 'not found'))
                if not path:
                    self.log('save not found on the device yet - start the game once so it creates save.es3')
            except Exception as e:
                self.log('detect device failed: %s' % e)
                self.after(0, lambda: messagebox.showerror('Detect device', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _detect_device_save(self, adb_hint=None, serial_hint=None):
        adb = android.find_adb(adb_hint or None)
        if not adb:
            raise RuntimeError('adb not found (set the path in Connection settings)')
        devs = android.devices(adb)
        if not devs:
            raise RuntimeError('no adb device attached - start the emulator (or connect the phone with USB debugging) and press Detect device again')
        serial = serial_hint if serial_hint in devs else devs[0]
        path = android.find_save_path(adb, serial)
        if not path:
            raise RuntimeError('save.es3 not found on the device (start the game once)')
        self.after(0, lambda: (self.serial_combo.configure(values=devs), self.serial.set(serial),
                               self.device_save.set(path)))
        cache = self._cache_dir()
        local = os.path.join(cache, 'save_device.es3')
        rc, out, err = android.pull(adb, serial, path, local, timeout=120)
        if rc != 0 or not os.path.exists(local):
            raise RuntimeError('adb pull failed: %s' % (err or out))
        self.log('pulled %s (%s)' % (path, (out or '').strip() or 'ok'))
        return local

    def on_auto_detect(self, silent=False):
        adb_hint = self.adb.get().strip()
        serial_hint = self.serial.get().strip()

        def work():
            path = None
            try:
                path = self._detect_device_save(adb_hint, serial_hint)
                self.log('auto-detected device save: %s' % path)
            except Exception as e:
                if not silent:
                    self.log('device detection failed: %s' % e)
                locals_ = self._local_candidates()
                if locals_:
                    path = locals_[0]
                    self.log('using local save: %s' % path)
                else:
                    if not silent:
                        self.after(0, lambda: messagebox.showwarning(
                            'Find save', 'No save found on the device or in Downloads/Desktop.'))
                    return
            self.after(0, lambda p=path: self._open_detected(p))

        threading.Thread(target=work, daemon=True).start()

    def _open_detected(self, path):
        try:
            data = open(path, 'rb').read()
        except Exception as e:
            messagebox.showerror('Find save', str(e))
            return
        if data[:4] == b'ES3E':
            self.path = path
            self.path_var.set(path + '   [ENCRYPTED]')
            self.log('detected encrypted save: %s' % path)
            if messagebox.askyesno('Encrypted save',
                                   'Found an encrypted save:\n%s\n\nDecrypt it now with the game?' % path):
                self._start_convert(path)
            return
        self._load_plain(path)

    # ------------------------------------------------------------- actions
    def on_open(self):
        path = filedialog.askopenfilename(title='Open save',
                                          filetypes=[('Save/JSON', '*.json;*.es3'), ('All files', '*.*')])
        if not path:
            return
        try:
            data = open(path, 'rb').read()
        except Exception as e:
            messagebox.showerror('Open', str(e))
            return
        if data[:4] == b'ES3E':
            self.path = path
            self.path_var.set(path + '   [ENCRYPTED]')
            self.text = None
            self.obj = None
            for tab in (self.tab_res, self.tab_units, self.tab_mem, self.tab_adv):
                pass
            self.log('This file is encrypted (ES3E). Use "Convert encrypted…" to decrypt it with the game.')
            messagebox.showinfo('Encrypted save',
                                'This save is encrypted (ES3E).\n\nUse "Convert encrypted…": it pushes the file to the '
                                'emulator, starts the game to decrypt it, and loads the plain JSON.')
            return
        try:
            self.text = data.decode('utf-8')
            self.path = path
            self.path_var.set(path)
            self._reload_from_text()
            self.log('loaded %s (%d bytes, %d keys)' % (path, len(data), len(self.obj)))
        except Exception as e:
            messagebox.showerror('Open', 'cannot parse save: %s' % e)

    def on_convert(self):
        path = self.path
        if not path or not os.path.exists(path):
            path = filedialog.askopenfilename(title='Encrypted save.es3', filetypes=[('ES3 save', '*.es3'), ('All files', '*.*')])
            if not path:
                return
        if not messagebox.askyesno('Convert',
                                   'This pushes the file to the device, starts the game to decrypt it, and saves the '
                                   'plain JSON next to the original.\nContinue?'):
            return
        self._start_convert(path)

    def _start_convert(self, path):
        adb_hint = self.adb.get().strip() or None
        serial_hint = self.serial.get().strip() or None
        dev_path = self.device_save.get().strip()
        endpoint = self.endpoint.get().strip() or None

        def work():
            try:
                adb = android.find_adb(adb_hint)
                if adb and dev_path:
                    rc, out, err = android.push(adb, serial_hint, path, dev_path, timeout=60)
                    if rc == 0:
                        self.log('pushed %s -> %s' % (path, dev_path))
                    else:
                        self.log('push failed: %s' % (err or out))
                import dw_save_convert as conv
                import dw_setup
                dw_setup.ensure_frida(adb, serial_hint, log=self.log)
                data = conv.convert_save(endpoint=endpoint,
                                         dec_rva=None,
                                         adb=adb, serial=serial_hint, log=self.log)
                cache = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'DungeonWithinSaveEditor')
                os.makedirs(cache, exist_ok=True)
                out = os.path.join(cache, 'save_plain.json')
                open(out, 'wb').write(data)
                self.log('plain save written: %s (%d bytes)' % (out, len(data)))
                self.after(0, lambda: self._load_plain(out))
            except Exception as e:
                self.log('convert failed: %s' % e)
                self.log(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror('Convert', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _load_plain(self, path):
        self.text = open(path, encoding='utf-8').read()
        self.path = path
        self.path_var.set(path)
        self._reload_from_text()
        self.log('loaded plain save %s (%d bytes)' % (path, len(self.text)))
        self.nb.select(self.tab_res)

    def _device_serial(self):
        adb = self._find_adb()
        if not adb:
            raise RuntimeError('adb not found (set the path in Connection settings)')
        devs = android.devices(adb)
        if not devs:
            raise RuntimeError('no adb device attached - start the emulator (or connect the phone with USB debugging) and press Detect device again')
        serial = self.serial.get().strip() or devs[0]
        return adb, (serial if serial in devs else devs[0])

    def push_to_device(self):
        if not self.path or not os.path.exists(self.path):
            raise RuntimeError('no local save loaded')
        adb, serial = self._device_serial()
        dev = self.device_save.get().strip()
        r = self._adb(adb, serial, 'push', self.path, dev, timeout=120)
        if r.returncode != 0:
            raise RuntimeError('adb push failed: %s' % (r.stderr or r.stdout))
        self.log('pushed %s -> %s' % (self.path, dev))
        return dev

    def on_push(self):
        try:
            self.push_to_device()
            messagebox.showinfo('Push', 'Save pushed to the device.')
        except Exception as e:
            messagebox.showerror('Push', str(e))

    CACHE_SUBDIR = 'DungeonWithinSaveEditor'

    def _cache_dir(self):
        d = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), self.CACHE_SUBDIR)
        os.makedirs(d, exist_ok=True)
        return d

    def on_encrypt_save(self):
        if self.text is None or not self.path:
            messagebox.showwarning('Encrypt', 'Load or convert a save first.')
            return
        text = self.text
        adb_hint = self.adb.get().strip()
        serial_hint = self.serial.get().strip()
        endpoint = self.endpoint.get().strip() or None

        def work():
            try:
                text2 = ed.recompute_checksums(text, False)
                out = os.path.join(self._cache_dir(), 'save_to_encrypt.json')
                open(out, 'w', encoding='utf-8', newline='').write(text2)
                import dw_save_encrypt as enc
                import dw_setup
                adb_use = android.find_adb(adb_hint or None)
                dw_setup.ensure_frida(adb_use, serial_hint, log=self.log)
                res = enc.encrypt_plain(out, adb=adb_use, serial=serial_hint,
                                        endpoint=endpoint, log=self.log)
                self.after(0, lambda: messagebox.showinfo(
                    'Encrypt', 'Encrypted save written to the device:\n%s\n(%d bytes, starts with %s)\n\n'
                    'It is a normal ES3E file now - you can launch the game normally or upload it to the cloud.'
                    % (res['remote'], res.get('cipher_bytes') or 0, res['head'])))
            except Exception as e:
                self.log('encrypt failed: %s' % e)
                self.log(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror('Encrypt', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def on_restore_encrypted(self):
        bak = os.path.join(self._cache_dir(), 'encrypted_backup.es3')
        if not os.path.exists(bak):
            messagebox.showwarning('Restore', 'No encrypted backup stored yet.\nIt is created automatically the '
                                               'first time you press "Launch game (plain mode)".')
            return
        try:
            adb, serial = self._device_serial()
            dev = self.device_save.get().strip()
            r = self._adb(adb, serial, 'push', bak, dev, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(r.stderr or r.stdout)
            self.log('restored encrypted save %s -> %s' % (bak, dev))
            self.path_var.set('(no file)')
            self.text = None
            self.obj = None
            messagebox.showinfo('Restore', 'Encrypted save restored. You can start the game normally now.')
        except Exception as e:
            messagebox.showerror('Restore', str(e))

    def on_apply(self):
        if self.text is None or not self.path:
            messagebox.showwarning('Apply', 'No save loaded.')
            return
        try:
            self.text = ed.recompute_checksums(self.text, False)
            if os.path.exists(self.path):
                shutil.copyfile(self.path, self.path + '.bak')
            open(self.path, 'w', encoding='utf-8', newline='').write(self.text)
            self._reload_from_text()
            self.log('applied locally to %s (backup: %s.bak)' % (self.path, self.path))
            self.log('press "Launch game (plain mode)" to play with these edits')
        except Exception as e:
            messagebox.showerror('Apply', str(e))

    def on_validate(self):
        if self.obj is None:
            return
        bad = 0
        n = 0
        for path, vault in ed.walk_vaults(self.obj):
            n += 1
            vals = vault.get('values') or {}
            if any(not isinstance(v, int) for v in vals.values()):
                continue
            x = 0
            for v in vals.values():
                x ^= (int(v) if isinstance(v, bool) else v) & 0xFFFFFFFF
            want = ed.to_signed32((vault.get('checksumSeed', 0) ^ x) & 0xFFFFFFFF)
            if vault.get('checksum') != want:
                bad += 1
        self.log('validate: %d vaults, %d mismatched' % (n, bad))
        messagebox.showinfo('Validate', '%d DataVaults, %d mismatched' % (n, bad))

    def on_backup(self):
        if not self.path or not os.path.exists(self.path):
            return
        dst = self.path + '.%s.bak' % time.strftime('%Y%m%d-%H%M%S')
        shutil.copyfile(self.path, dst)
        self.log('backup: %s' % dst)

    def on_launch(self):
        text = self.text
        path = self.path
        adb_hint = self.adb.get().strip()
        serial_hint = self.serial.get().strip()
        dev = self.device_save.get().strip()
        endpoint = self.endpoint.get().strip() or None

        def work():
            try:
                if not (text and path):
                    raise RuntimeError('load or convert a save first')
                adb = android.find_adb(adb_hint or None)
                if not adb:
                    raise RuntimeError('adb not found')
                devs = android.devices(adb)
                if not devs:
                    raise RuntimeError('no adb device attached - start the emulator or connect the phone')
                serial = serial_hint if serial_hint in devs else devs[0]
                import dw_setup
                dw_setup.ensure_frida(adb, serial, log=self.log)
                if head_starts(adb, serial, dev, 'ES3E'):
                    # keep a copy of the encrypted save so normal play can be restored later
                    bak = os.path.join(self._cache_dir(), 'encrypted_backup.es3')
                    rc, out, err = android.pull(adb, serial, dev, bak, timeout=120)
                    if rc == 0:
                        self.log('encrypted backup saved: %s' % bak)
                    else:
                        self.log('warning: could not back up the encrypted save: %s' % (err or out))
                # persist and push the plain save, then check the device really holds plain JSON
                open(path, 'w', encoding='utf-8', newline='').write(text)
                rc, out, err = android.push(adb, serial, path, dev, timeout=120)
                if rc != 0:
                    raise RuntimeError('adb push failed: %s' % (err or out))
                if not head_starts(adb, serial, dev, '{'):
                    raise RuntimeError('the save on the device is not plain JSON; refusing to start '
                                       '(this is what causes an empty save).')
                import dw_save_launch as ln
                self.launch_state = ln.launch_patched(
                    endpoint=endpoint,
                    dec_rva=None, enc_rva=None,
                    adb=adb, serial=serial,
                    log=self.log)
                self.log('plain-mode launcher attached. Do NOT start the game normally while this plain save is '
                         'on the device; use "Restore encrypted save" when you want normal play again.')
            except Exception as e:
                self.log('launch failed: %s' % e)
                self.log(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror('Launch', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def on_set_resource(self):
        k = self.res_key.get()
        if not k or self.text is None:
            return
        try:
            v = int(self.res_value.get())
            reg = ed.object_span(self.text, 'USER_DATA.storage')
            vi, vj = ed.object_span(self.text, 'values', reg[0], reg[1])
            self.text = ed.set_token(self.text, k, str(v), vi, vj)
            self.text = ed.recompute_checksums(self.text, False)
            self._reload_from_text()
            self.log('%s = %d' % (k, v))
        except Exception as e:
            messagebox.showerror('Set resource', str(e))

    def on_set_all_resources(self):
        if self.text is None:
            return
        try:
            v = int(self.res_all.get())
            reg = ed.object_span(self.text, 'USER_DATA.storage')
            vi, vj = ed.object_span(self.text, 'values', reg[0], reg[1])
            vals = ed.vault_values(self.text, reg)
            keep = {'FIRSTPLAY', 'MW_TOKEN_SEED', 'RAND_TOKEN_COIN', 'TKQ_IROCHI_RETRO'}
            for k in vals:
                if k in keep:
                    continue
                self.text = ed.set_token(self.text, k, str(v), vi, vj)
            self.text = ed.recompute_checksums(self.text, False)
            self._reload_from_text()
            self.log('all resources = %d' % v)
        except Exception as e:
            messagebox.showerror('All resources', str(e))

    def on_set_unit_name(self):
        try:
            idx = getattr(self, '_selected_unit', None)
            if idx is None:
                return
            s, e = self._unit_span(idx)
            val = self.unit_name.get().strip()
            lit = json.dumps(val) if val else 'null'
            self.text = ed.set_token(self.text, 'customName', lit, s, e)
            self._reload_from_text()
            self.log('unit %d customName = %s' % (idx, lit))
        except Exception as e:
            messagebox.showerror('Unit name', str(e))

    def on_set_unit_variant(self):
        try:
            idx = getattr(self, '_selected_unit', None)
            if idx is None:
                return
            prefix = self.unit_prefix.get().strip()
            skin = self.unit_skin.get().strip()
            irochi = self.unit_irochi.get().strip()
            if prefix:
                self.text = ed.set_unit_field(self.text, idx, 'prefix', prefix)
            if skin:
                self.text = ed.set_unit_field(self.text, idx, 'skin', skin)
            if irochi:
                self.text = ed.set_unit_field(self.text, idx, 'Irochi', irochi)
            self._reload_from_text()
            self._select_unit(idx)
            self.log('unit %d prefix=%s skin=%s irochi=%s' % (idx, prefix, skin, irochi))
        except Exception as e:
            messagebox.showerror('Trait / variant', str(e))

    def _ask_choice(self, title, prompt, values, initial=''):
        """Small modal with a dropdown; returns the chosen value or None."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text=prompt, justify='left').pack(anchor='w', padx=10, pady=(10, 4))
        var = tk.StringVar(value=initial)
        combo = ttk.Combobox(dlg, textvariable=var, values=values, width=34)
        combo.pack(padx=10, pady=4)
        combo.focus_set()
        out = {}

        def ok():
            out['value'] = var.get().strip()
            dlg.destroy()

        def cancel():
            dlg.destroy()

        row = ttk.Frame(dlg); row.pack(pady=(6, 10))
        ttk.Button(row, text='OK', command=ok).pack(side='left', padx=4)
        ttk.Button(row, text='Cancel', command=cancel).pack(side='left', padx=4)
        dlg.bind('<Return>', lambda e: ok())
        dlg.bind('<Escape>', lambda e: cancel())
        dlg.wait_window()
        return out.get('value') or None

    def on_replace_monster(self):
        try:
            idx = getattr(self, '_selected_unit', None)
            if idx is None:
                return
            old = ed.unit_index_key(self.text, idx)
            catalog = ed.unit_type_catalog(self.obj)
            new = self._ask_choice('Monster replacement',
                                   'Replace monster #%d (%s) with which monster type?' % (idx, old),
                                   catalog, old)
            if not new:
                return
            new = new.strip().upper()
            if new == old:
                return
            if not messagebox.askyesno(
                    'Monster replacement',
                    'This replaces %s with %s (writes unitIdx).\n\n'
                    'Stats, parts, prefix and myth stay from the old monster; the innate\n'
                    'trait becomes %s_I1. A .bak is written first.\n\nContinue?' % (old, new, new)):
                return
            if self.path and os.path.exists(self.path):
                shutil.copyfile(self.path, self.path + '.bak')
            self.text = ed.transform_unit_type(self.text, idx, new)
            self._reload_from_text()
            self._select_unit(idx)
            self.log('monster replacement: unit %d %s -> %s (backup written)' % (idx, old, new))
        except Exception as e:
            messagebox.showerror('Monster replacement', str(e))

    def on_capture_names(self):
        def work():
            try:
                import dw_names
                m = dw_names.capture(timeout=90, log=self.log)
                self.names = dw_names.load_names()
                self.log('captured %d names this run (%d total)' % (len(m), len(self.names)))
                self.after(0, self._refresh_units)
            except Exception as e:
                self.log('name capture failed: %s' % e)
                self.after(0, lambda: messagebox.showerror('Capture names', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def on_set_promotion(self):
        try:
            idx = getattr(self, '_selected_unit', None)
            if idx is None:
                return
            if self.unit_rankup.get().strip():
                self.text = ed.set_unit_vault(self.text, idx, 'RankUp', int(self.unit_rankup.get()))
            if self.unit_transcend.get().strip():
                self.text = ed.set_unit_vault(self.text, idx, 'TRANSCEND', int(self.unit_transcend.get()))
            self._reload_from_text()
            self._select_unit(idx)
            self.log('unit %d promotion RankUp=%s Transcend=%s' % (
                idx, self.unit_rankup.get(), self.unit_transcend.get()))
        except Exception as e:
            messagebox.showerror('Promotion', str(e))

    def _select_unit(self, idx):
        for row in self.unit_tree.get_children():
            if int(self.unit_tree.item(row, 'values')[0]) == idx:
                self.unit_tree.selection_set(row)
                self._unit_selected()
                return

    def on_set_unit_progress(self):
        try:
            key = getattr(self, '_selected_unit_key', None)
            if not key:
                return
            if ed.unit_exp_span(self.text, key) is None:
                raise KeyError('unit %s has no unitExp entry' % key)
            self.text = ed.set_unit_exp(self.text, key, 'LEVEL', int(self.unit_level.get()))
            self.text = ed.set_unit_exp(self.text, key, 'EXP', int(self.unit_essence.get()))
            self.text = ed.set_unit_exp(self.text, key, 'AWAKE_LEVEL', int(self.unit_awake.get()))
            self.text = ed.set_unit_exp(self.text, key, 'TRAIN_LEVEL', int(self.unit_train.get()))
            self._reload_from_text()
            self.log('unit %s progress: level=%s essence=%s awake=%s train=%s' % (
                key, self.unit_level.get(), self.unit_essence.get(), self.unit_awake.get(), self.unit_train.get()))
        except Exception as e:
            messagebox.showerror('Unit progress', str(e))

    def on_set_unit_stat(self, field, stat):
        try:
            idx = getattr(self, '_selected_unit', None)
            if idx is None:
                return
            val = float(self.unit_stat_vars[stat].get())
            s, e = self._unit_span(idx)
            fi, fj = ed.object_span(self.text, field, s, e)
            self.text = ed.set_token(self.text, stat, repr(val), fi, fj)
            self._reload_from_text()
            self.log('unit %d %s %s = %s' % (idx, field, stat, val))
        except Exception as e:
            messagebox.showerror('Unit stat', str(e))

    def on_set_awake(self):
        try:
            idx = getattr(self, '_selected_unit', None)
            if idx is None:
                return
            s, e = self._unit_span(idx)
            ai, aj = ed.object_span(self.text, 'awakeEft', s, e)
            vi, vj = ed.object_span(self.text, 'values', ai, aj)
            for st in STATS:
                self.text = ed.set_token(self.text, st, str(int(self.awake_vars[st].get())), vi, vj)
            self.text = ed.recompute_checksums(self.text, False)
            self._reload_from_text()
            self.log('unit %d awake stats updated' % idx)
        except Exception as e:
            messagebox.showerror('Awake', str(e))

    def on_set_memento(self):
        try:
            key = self.mem_key.get()
            if not key:
                return
            ai, aj = ed.array_span(self.text, 'USER_DATA.mementos')
            done = False
            for s, e in ed.split_children(self.text, (ai, aj), '['):
                try:
                    k = ed.get_token(self.text, 'key', s, e).strip('"')
                except KeyError:
                    continue
                if k == key:
                    self.text = ed.set_token(self.text, 'buyCount', str(int(self.mem_count.get())), s, e)
                    done = True
                    break
            if not done:
                raise KeyError(key)
            self._reload_from_text()
            self.log('memento %s buyCount = %s' % (key, self.mem_count.get()))
        except Exception as e:
            messagebox.showerror('Memento', str(e))

    def on_adv_get(self):
        if self.obj is None:
            return
        try:
            node = self.obj
            for part in [p for p in __import__('re').findall(r'[^.\[\]]+|\[\d+\]', self.adv_path.get())]:
                node = node[int(part[1:-1])] if part.startswith('[') else node[part]
            self.adv_text.delete('1.0', 'end')
            self.adv_text.insert('end', json.dumps(node, ensure_ascii=False, indent=1))
        except Exception as e:
            messagebox.showerror('Get', str(e))

    def on_adv_set(self):
        if self.text is None:
            return
        try:
            key = self.adv_path.get().split('.')[-1]
            lit = self.adv_text.get('1.0', 'end').strip()
            json.loads(lit)
            self.text = ed.set_token(self.text, key, lit)
            self.text = ed.recompute_checksums(self.text, False)
            self._reload_from_text()
            self.log('%s set' % key)
        except Exception as e:
            messagebox.showerror('Set', str(e))

    def destroy(self):
        try:
            save_config({
                'endpoint': self.endpoint.get(), 'adb': self.adb.get(), 'serial': self.serial.get(),
                'device_save': self.device_save.get(), 'dec_rva': self.cfg['dec_rva'], 'enc_rva': self.cfg['enc_rva'],
            })
        except Exception:
            pass
        super().destroy()


def head_starts(adb, serial, path, prefix):
    try:
        return android.head(adb, serial, path, len(prefix)).startswith(prefix)
    except Exception:
        return False


def subprocess_run(cmd, timeout=25):
    import subprocess
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        class R:
            returncode = 1
            stdout = ''
            stderr = str(e)
        return R()


def main():
    app = App()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        path = sys.argv[1]
        try:
            data = open(path, 'rb').read()
            if data[:4] == b'ES3E':
                app.path = path
                app.path_var.set(path + '   [ENCRYPTED]')
                app.log('encrypted save passed on the command line; use "Convert encrypted…"')
            else:
                app.text = data.decode('utf-8')
                app.path = path
                app.path_var.set(path)
                app._reload_from_text()
                app.log('loaded %s (%d bytes)' % (path, len(data)))
        except Exception as e:
            app.log('failed to open %s: %r' % (path, e))
    app.mainloop()


if __name__ == '__main__':
    main()
