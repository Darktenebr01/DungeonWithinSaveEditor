"""Dark theme for the save editor (Arisen's-Toolbox-like palette)."""

import tkinter as tk
from tkinter import ttk

BG = '#1b1b1d'
BG2 = '#202024'
SIDEBAR = '#1f1f22'
CARD = '#232326'
CARD2 = '#2a2a2e'
FIELD = '#141416'
BORDER = '#34343a'
TEXT = '#e9e9ec'
MUTED = '#9a9aa3'
DIM = '#6f6f78'
ACCENT = '#f5a623'
ACCENT_DARK = '#3a2e17'
GREEN = '#4ade80'
RED = '#f87171'

BASE = ('Segoe UI', 9)
SMALL = ('Segoe UI', 8)
BOLD = ('Segoe UI', 9, 'bold')
H2 = ('Segoe UI', 10, 'bold')
TITLE = ('Segoe UI', 16, 'bold')
MONO = ('Consolas', 9)


def apply(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    style.configure('.', font=BASE, background=BG, foreground=TEXT,
                    bordercolor=BORDER, darkcolor=BORDER, lightcolor=BORDER,
                    troughcolor=BG2, focuscolor=ACCENT)
    style.configure('TFrame', background=BG)
    style.configure('Bar.TFrame', background=BG2)
    style.configure('Side.TFrame', background=SIDEBAR)
    style.configure('Card.TFrame', background=CARD)
    style.configure('Field.TFrame', background=CARD)

    style.configure('TLabel', background=BG, foreground=TEXT, font=BASE)
    style.configure('Muted.TLabel', background=BG, foreground=MUTED)
    style.configure('Side.TLabel', background=SIDEBAR, foreground=MUTED)
    style.configure('SideTitle.TLabel', background=SIDEBAR, foreground=TEXT,
                    font=('Segoe UI', 12, 'bold'))
    style.configure('SideSub.TLabel', background=SIDEBAR, foreground=DIM, font=SMALL)
    style.configure('Section.TLabel', background=SIDEBAR, foreground=DIM,
                    font=('Segoe UI', 8, 'bold'))
    style.configure('Card.TLabel', background=CARD, foreground=TEXT)
    style.configure('CardMuted.TLabel', background=CARD, foreground=MUTED, font=SMALL)
    style.configure('CardHead.TLabel', background=CARD, foreground=TEXT, font=H2)
    style.configure('PageTitle.TLabel', background=BG, foreground=TEXT, font=TITLE)
    style.configure('PageSub.TLabel', background=BG, foreground=MUTED, font=BASE)

    style.configure('TButton', background=CARD2, foreground=TEXT, borderwidth=1,
                    focusthickness=0, padding=(10, 4), relief='flat', font=BASE)
    style.map('TButton',
              background=[('pressed', '#26262b'), ('active', '#303038')],
              foreground=[('disabled', DIM)])
    style.configure('Accent.TButton', background=ACCENT, foreground='#161616',
                    borderwidth=0, padding=(12, 4), font=('Segoe UI', 9, 'bold'))
    style.map('Accent.TButton',
              background=[('pressed', '#e09a1c'), ('active', '#ffb733')])
    style.configure('Bar.TButton', background=BG2, foreground=MUTED, borderwidth=0,
                    padding=(8, 4))
    style.map('Bar.TButton', background=[('active', CARD2)], foreground=[('active', TEXT)])
    style.configure('Nav.TButton', background=SIDEBAR, foreground=MUTED, borderwidth=0,
                    padding=(14, 6), anchor='w', font=BASE)
    style.map('Nav.TButton', background=[('active', CARD)], foreground=[('active', TEXT)])
    style.configure('NavOn.TButton', background=ACCENT_DARK, foreground=ACCENT,
                    borderwidth=0, padding=(14, 6), anchor='w', font=('Segoe UI', 9, 'bold'))
    style.map('NavOn.TButton', background=[('active', ACCENT_DARK)], foreground=[('active', ACCENT)])

    style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT,
                    insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=3)
    style.map('TEntry', fieldbackground=[('readonly', CARD)], foreground=[('disabled', DIM)])

    style.configure('TCombobox', fieldbackground=FIELD, background=CARD2, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=3)
    style.map('TCombobox',
              fieldbackground=[('readonly', FIELD), ('disabled', BG2)],
              foreground=[('disabled', DIM)],
              selectbackground=[('readonly', FIELD)])

    style.configure('TCheckbutton', background=BG, foreground=TEXT, focuscolor=BG)
    style.map('TCheckbutton', background=[('active', BG)])

    style.configure('TLabelframe', background=CARD, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=CARD, foreground=MUTED,
                    font=('Segoe UI', 8, 'bold'))

    style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=TEXT,
                    bordercolor=BORDER, rowheight=21, font=BASE)
    style.configure('Treeview.Heading', background=BG2, foreground=MUTED,
                    relief='flat', font=('Segoe UI', 8, 'bold'))
    style.map('Treeview.Heading', background=[('active', CARD2)])
    style.map('Treeview', background=[('selected', ACCENT_DARK)],
              foreground=[('selected', ACCENT)])

    style.configure('Vertical.TScrollbar', background=BG2, troughcolor=BG2,
                    bordercolor=BG, arrowcolor=MUTED, arrowsize=10, width=10)
    style.map('Vertical.TScrollbar', background=[('active', CARD2)])

    return style


def style_text(widget, wrap='none'):
    widget.configure(bg=FIELD, fg=TEXT, insertbackground=TEXT,
                     selectbackground=ACCENT_DARK, selectforeground=ACCENT,
                     highlightthickness=0, borderwidth=0, font=MONO,
                     padx=8, pady=6, wrap=wrap)
