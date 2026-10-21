"""Dark, modern Qt stylesheet."""

BG = "#0f1115"
PANEL = "#171a21"
PANEL2 = "#1d212a"
LINE = "#2a2f3a"
TEXT = "#e8eaf0"
MUTED = "#8a90a2"
ACCENT = "#7c5cff"
ACCENT2 = "#22d3ee"
OK = "#34d399"
WARN = "#fbbf24"
ERR = "#f87171"

QSS = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QWidget#Sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
QLabel#Brand {{ font-size: 13pt; font-weight: 700; }}
QLabel#BrandSub {{ color: {MUTED}; font-size: 8.5pt; }}
QPushButton#Nav {{
    text-align: left; padding: 9px 14px; border: none; border-radius: 10px;
    background: transparent; color: {MUTED}; font-weight: 600;
}}
QPushButton#Nav:hover {{ background: {PANEL2}; color: {TEXT}; }}
QPushButton#Nav:checked {{ background: rgba(124,92,255,0.18); color: {TEXT}; }}

QLabel#PageTitle {{ font-size: 18pt; font-weight: 700; }}
QLabel#PageSub {{ color: {MUTED}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#H2 {{ font-size: 11.5pt; font-weight: 700; }}
QFrame#Card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; }}
QFrame#Drop {{ background: {PANEL}; border: 2px dashed {LINE}; border-radius: 16px; }}

QPushButton {{
    background: {PANEL2}; border: 1px solid {LINE}; border-radius: 9px; padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {PANEL2}; }}
QPushButton#Primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {ACCENT}, stop:1 #5b8cff); border: none; color: white;
}}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #8f73ff, stop:1 #6f9bff); }}
QPushButton#Primary:disabled {{ background: {LINE}; color: {MUTED}; }}
QPushButton#Danger {{ background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.5); color: {ERR}; }}
QPushButton#Danger:hover {{ background: rgba(248,113,113,0.22); }}
QPushButton#Seg {{ border-radius: 8px; padding: 5px 9px; background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton#Seg:checked {{ background: {PANEL2}; border: 1px solid {LINE}; color: {TEXT}; }}
QToolButton {{ background: {PANEL2}; border: 1px solid {LINE}; border-radius: 9px; padding: 6px; }}
QToolButton:hover {{ border-color: {ACCENT}; }}
QToolButton:checked {{ background: rgba(124,92,255,0.25); border-color: {ACCENT}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {BG}; border: 1px solid {LINE}; border-radius: 9px; padding: 6px 10px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL2}; border: 1px solid {LINE}; selection-background-color: {ACCENT}; outline: none; padding: 4px; }}
QSpinBox, QDoubleSpinBox {{ padding: 5px 8px; min-height: 22px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; subcontrol-origin: border; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {LINE}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(CHECK_URL); }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; border: 1px solid {LINE}; background: {BG}; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 4px solid {BG}; outline: 1px solid {ACCENT}; }}

QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QProgressBar {{ background: {BG}; border: 1px solid {LINE}; border-radius: 7px; height: 14px; text-align: center; font-size: 8pt; }}
QProgressBar::chunk {{ border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENT}, stop:1 {ACCENT2}); }}

QListView, QTreeWidget, QTableWidget, QListWidget {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; outline: none; alternate-background-color: {PANEL2};
}}
QListView::item {{ border-radius: 10px; padding: 4px; }}
QListView::item:hover {{ background: {PANEL2}; }}
QListView::item:selected {{ background: rgba(124,92,255,0.28); color: {TEXT}; }}
QTreeWidget::item, QTableWidget::item, QListWidget::item {{ padding: 4px; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{ background: rgba(124,92,255,0.28); color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {PANEL}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4050; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px; border-radius: 6px; }}
QMenu {{ background: {PANEL2}; border: 1px solid {LINE}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(124,92,255,0.3); }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
QMessageBox, QDialog {{ background: {PANEL}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
"""
