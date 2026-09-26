"""The look.

One stylesheet, one palette. Change ACCENT and the whole app follows; the
button variants are selected with a dynamic "variant" property rather than
separate classes, so a button can be restyled without being rebuilt.
"""

BG        = "#0A0A0C"
SURFACE   = "#151517"
SURFACE_2 = "#1C1C1E"
RAISED    = "#262628"
BORDER    = "#2F2F30"
TEXT      = "#DADADB"
MUTED     = "#919192"
FAINT     = "#676768"

ACCENT    = "#FF4081"
ACCENT_HI = "#FF669A"
ACCENT_LO = "#C23264"

SUCCESS   = "#919192"
WARNING   = "#FF7043"
DANGER    = "#FF7043"

FONT = '"Noto Sans", "DejaVu Sans", sans-serif'
MONO = '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace'


def stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}

QWidget#Root, QMainWindow {{ background: {BG}; }}

/* ---- header ------------------------------------------------------- */
QWidget#Header {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QLabel#Wordmark {{ font-size: 16px; font-weight: 600; letter-spacing: 0.3px; }}
QLabel#Subtitle {{ color: {FAINT}; font-size: 11px; }}

/* ---- search ------------------------------------------------------- */
QLineEdit#Search {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit#Search:focus {{ border-color: {ACCENT}; background: {RAISED}; }}
QLineEdit#Search::placeholder {{ color: {FAINT}; }}

/* ---- buttons ------------------------------------------------------ */
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover:enabled  {{ background: {RAISED}; border-color: {FAINT}; }}
QPushButton:pressed:enabled {{ background: {SURFACE}; }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE}; border-color: {BORDER}; }}

QPushButton[variant="primary"] {{
    background: {ACCENT}; border-color: {ACCENT}; color: #0B0E14; font-weight: 600;
}}
QPushButton[variant="primary"]:hover:enabled  {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton[variant="primary"]:pressed:enabled {{ background: {ACCENT_LO}; }}
QPushButton[variant="primary"]:disabled {{ background: {SURFACE_2}; color: {FAINT}; border-color: {BORDER}; }}

QPushButton[variant="danger"] {{ color: {DANGER}; border-color: #402018; }}
QPushButton[variant="danger"]:hover:enabled {{ background: #271613; border-color: {DANGER}; }}
QPushButton[variant="danger"]:disabled {{ color: {FAINT}; border-color: {BORDER}; background: {SURFACE}; }}

/* ---- sidebar ------------------------------------------------------ */
QWidget#Sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel[role="section"] {{
    color: {FAINT}; font-size: 10px; font-weight: 700;
    letter-spacing: 1.2px; padding: 14px 14px 6px 14px;
}}
QListWidget#Filters {{ background: transparent; border: none; padding: 0 8px; }}
QListWidget#Filters::item {{
    padding: 8px 10px; border-radius: 8px; margin: 1px 0; color: {MUTED};
}}
QListWidget#Filters::item:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QListWidget#Filters::item:selected {{ background: {RAISED}; color: {TEXT}; font-weight: 600; }}

/* ---- table -------------------------------------------------------- */
QTableView {{
    background: {BG};
    alternate-background-color: #12151C;
    border: none;
    gridline-color: transparent;
    selection-background-color: {RAISED};
    selection-color: {TEXT};
}}
QTableView::item {{ padding: 7px 10px; border: none; }}
QTableView::item:selected {{ background: {RAISED}; }}
QHeaderView::section {{
    background: {SURFACE};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 10px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.4px;
}}
QHeaderView::section:hover {{ color: {TEXT}; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

/* ---- detail panel ------------------------------------------------- */
QWidget#Detail {{ background: {SURFACE}; border-left: 1px solid {BORDER}; }}
QLabel#DetailName {{ font-size: 17px; font-weight: 600; }}
QLabel#DetailVersion {{ color: {ACCENT}; font-size: 12px; }}
QLabel[role="key"] {{ color: {FAINT}; font-size: 11px; }}
QLabel[role="value"] {{ color: {TEXT}; font-size: 12px; }}
QLabel#DetailBody {{ color: {MUTED}; font-size: 12px; }}

QLabel[badge="installed"] {{
    color: {SUCCESS}; background: #19191B; border: 1px solid #2C2C2E;
    border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;
}}
QLabel[badge="differs"] {{
    color: {WARNING}; background: #221412; border: 1px solid #4F271B;
    border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;
}}
QLabel[badge="available"] {{
    color: {MUTED}; background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;
}}

/* ---- console ------------------------------------------------------ */
QWidget#ConsoleBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QPlainTextEdit#Console {{
    background: #0B0D12; border: none; color: #C7D0E0;
    font-family: {MONO}; font-size: 12px; padding: 10px;
    selection-background-color: {ACCENT_LO};
}}
QLabel#Status {{ color: {MUTED}; font-size: 12px; }}

/* ---- scrollbars --------------------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #2E3545; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3B455A; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #2E3545; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #3B455A; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- misc --------------------------------------------------------- */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QToolTip {{
    background: {RAISED}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
}}
QDialog {{ background: {BG}; }}
QCheckBox {{ color: {MUTED}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER}; background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
"""
