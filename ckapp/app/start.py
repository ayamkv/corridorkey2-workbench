"""The start page (no project open) and the New Project dialog."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from . import icons
from . import theme as T
from .project import FILE, MIN_FREE_GB, default_location, documents_dir, fixed_drives, free_gb, suggest_name
from .widgets import ElidedLabel, label

PATH_ROLE = Qt.UserRole + 1


class StartPage(QWidget):
    newRequested = Signal()
    openRequested = Signal()
    recentChosen = Signal(str)            # project.json path
    bringInRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        outer = QHBoxLayout(self)
        outer.addStretch(1)
        col = QWidget()
        col.setFixedWidth(560)
        v = QVBoxLayout(col)
        v.setSpacing(10)
        v.addStretch(2)
        v.addWidget(label("Projects", "SectionTitle"))
        intro = label("A project is a folder. Its renders and masks live inside it, so put it on a drive with room "
                      "for renders.", "Dim")
        intro.setWordWrap(True)
        v.addWidget(intro)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.bt_new = QPushButton("New project…")
        self.bt_new.setObjectName("Primary")
        self.bt_new.setIcon(icons.svg("plus", "ACCENT_FG", 14))
        self.bt_new.setIconSize(QSize(14, 14))
        self.bt_new.setMinimumHeight(34)
        self.bt_new.setToolTip("Create a project folder (Ctrl+Shift+N)")
        self.bt_new.clicked.connect(self.newRequested)
        self.bt_open = QPushButton("Open project…")
        self.bt_open.setIcon(icons.svg("folder-open", "TEXT_DIM", 14))
        self.bt_open.setIconSize(QSize(14, 14))
        self.bt_open.setMinimumHeight(34)
        self.bt_open.setToolTip("Open a project folder or its project.json (Ctrl+Shift+O)")
        self.bt_open.clicked.connect(self.openRequested)
        row.addWidget(self.bt_new)
        row.addWidget(self.bt_open)
        row.addStretch(1)
        v.addLayout(row)

        self.bring = QPushButton("")
        self.bring.setToolTip("Creates a project and adds the clips you had open before projects existed. "
                              "Their renders stay where they are.")
        self.bring.clicked.connect(self.bringInRequested)
        v.addWidget(self.bring)

        v.addSpacing(10)
        self.lb_recent = label("Recent", "Dim")
        v.addWidget(self.lb_recent)
        self.recent = QListWidget()
        self.recent.setObjectName("Panel")
        self.recent.setFrameShape(QListWidget.NoFrame)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent.itemClicked.connect(lambda it: self.recentChosen.emit(it.data(PATH_ROLE)))
        v.addWidget(self.recent)
        v.addStretch(3)
        outer.addWidget(col)
        outer.addStretch(1)
        self.set_bring_in(0)

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for p in paths:
            folder = os.path.dirname(p)
            row = QWidget()
            rv = QVBoxLayout(row)
            rv.setContentsMargins(10, 7, 10, 7)
            rv.setSpacing(1)
            name = label(os.path.basename(folder))
            name.setFont(T.ui_font(9.5, bold=True))
            path = ElidedLabel(folder, "Faint")
            rv.addWidget(name)
            rv.addWidget(path)
            it = QListWidgetItem()
            it.setData(PATH_ROLE, p)
            it.setToolTip(folder)
            it.setSizeHint(QSize(0, row.sizeHint().height()))
            self.recent.addItem(it)
            self.recent.setItemWidget(it, row)
        rows = sum(self.recent.sizeHintForRow(i) for i in range(self.recent.count()))
        self.recent.setFixedHeight(min(rows + 4, 420))
        self.recent.setVisible(bool(paths))
        self.lb_recent.setVisible(bool(paths))

    def set_bring_in(self, n: int) -> None:
        self.bring.setText(f"Bring in my {n} clip{'s' if n != 1 else ''} (renders stay where they are)")
        self.bring.setVisible(n > 0)


class NewProjectDialog(QDialog):
    """Name + location. The location defaults away from a nearly full system drive (see default_location)."""

    def __init__(self, last_parent: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.resize(620, 0)
        docs = documents_dir()
        start = default_location(last_parent, docs, free_gb(docs), fixed_drives())
        form = QFormLayout(self)
        form.setVerticalSpacing(10)
        self.ed_name = QLineEdit(suggest_name(start))
        form.addRow("Name", self.ed_name)
        loc = QHBoxLayout()
        self.lb_parent = ElidedLabel(start, "PathBox")
        b = QPushButton("Choose…")
        b.clicked.connect(self._browse)
        loc.addWidget(self.lb_parent, 1)
        loc.addWidget(b)
        form.addRow("Location", loc)
        self.lb_free = label("", "Faint")
        form.addRow("", self.lb_free)
        self.lb_result = label("", "Dim")
        self.lb_result.setWordWrap(True)
        form.addRow(self.lb_result)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText("Create")
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        form.addRow(self.bb)
        self.ed_name.textChanged.connect(self._update)
        self.ed_name.selectAll()
        self._update()

    def parent_dir(self) -> str:
        return self.lb_parent.full_text()

    def folder(self) -> str:
        return os.path.join(self.parent_dir(), self.ed_name.text().strip())

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Where the project folder goes", self.parent_dir())
        if d:
            self.lb_parent.set_full_text(os.path.normpath(d))
            self._update()

    def _update(self) -> None:
        free = free_gb(self.parent_dir())
        drive = os.path.splitdrive(self.parent_dir())[0] or self.parent_dir()
        if free is None:
            self.lb_free.setText("")
        else:
            self.lb_free.setText(f"{drive} {free:.0f} GB free" + (", tight for renders" if free < MIN_FREE_GB else ""))
            self.lb_free.setStyleSheet(f"color: {T.c('WARN')};" if free < MIN_FREE_GB else "")
        name = self.ed_name.text().strip()
        problem = self.problem(name)
        self.lb_result.setText(problem or f"Creates {self.folder()}")
        self.lb_result.setStyleSheet(f"color: {T.c('ERROR')};" if problem else "")
        self.bb.button(QDialogButtonBox.Ok).setEnabled(not problem)

    def problem(self, name: str) -> Optional[str]:
        if not name:
            return "Type a name."
        if any(ch in name for ch in '<>:"/\\|?*') or name.rstrip(". ") != name:
            return "A folder name can't contain < > : \" / \\ | ? * or end with a dot or space."
        if os.path.exists(os.path.join(self.parent_dir(), name, FILE)):
            return "That folder already has a project. Use Open project instead."
        return None
