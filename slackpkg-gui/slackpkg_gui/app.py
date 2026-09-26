"""The window.

Reading is free, acting is not: the package list is built from files any user
can read, and nothing is ever handed to slackpkg without a confirmation dialog
that shows the exact argv first.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import (QAbstractTableModel, QModelIndex,
                          QSortFilterProxyModel, Qt, QTimer)
from PyQt6.QtGui import QColor, QKeySequence, QShortcut, QTextCursor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication,
                             QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QSizePolicy, QSplitter, QTableView,
                             QVBoxLayout, QWidget)

from . import backend, console, runner, theme

COLUMNS = ["Package", "Status", "Version", "Repository", "Size"]
SORT_ROLE = Qt.ItemDataRole.UserRole + 1

CATEGORIES = [
    ("all", "All packages"),
    ("updates", "Updates"),
    ("installed", "Installed"),
    ("available", "Not installed"),
    ("local", "Not in any repo"),
]


def status_of(pkg: backend.Package) -> str:
    # Held before Update: a blacklisted package differs from the mirror
    # permanently, and calling that an update promises something slackpkg
    # will refuse to do.
    if pkg.differs and pkg.blacklisted:
        return "Held"
    if pkg.upgradable:
        return "Update"
    if pkg.is_installed and not pkg.in_repo:
        return "Local"
    if pkg.is_installed:
        return "Installed"
    return "Available"


class PackageModel(QAbstractTableModel):
    def __init__(self, packages: list[backend.Package]) -> None:
        super().__init__()
        self.packages = packages

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.packages)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def package(self, row: int) -> backend.Package:
        return self.packages[row]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        pkg = self.packages[index.row()]
        column = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, SORT_ROLE):
            if column == 0:
                return pkg.name
            if column == 1:
                return status_of(pkg)
            if column == 2:
                # one column, three cases: an upgrade shows the transition,
                # otherwise whichever version actually exists
                if pkg.differs:
                    return f"{pkg.installed}  →  {pkg.available_id}"
                return pkg.installed or pkg.available_id or "—"
            if column == 3:
                return pkg.repo or "—"
            if column == 4:
                if role == SORT_ROLE:
                    return backend.size_to_bytes(pkg.size_c)
                return pkg.size_c or "—"

        if role == Qt.ItemDataRole.ForegroundRole:
            if pkg.blacklisted:
                return QColor(theme.FAINT)
            if pkg.differs:
                return QColor(theme.WARNING if column in (1, 2) else theme.TEXT)
            if not pkg.is_installed:
                return QColor(theme.MUTED)
            if column == 1:
                return QColor(theme.SUCCESS if pkg.in_repo else theme.FAINT)

        if role == Qt.ItemDataRole.ToolTipRole:
            if pkg.blacklisted:
                return ("Blacklisted in /etc/slackpkg/blacklist — slackpkg "
                        "will not upgrade or remove it.")
            return pkg.summary or pkg.name

        if role == Qt.ItemDataRole.TextAlignmentRole and column == 4:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(SORT_ROLE)
        self._text = ""
        self._category = "all"
        self._repo: str | None = None

    def set_text(self, text: str) -> None:
        self._text = text.strip().lower()
        self.invalidateFilter()

    def set_category(self, category: str) -> None:
        self._category = category
        self.invalidateFilter()

    def set_repo(self, repo: str | None) -> None:
        self._repo = repo
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        pkg: backend.Package = self.sourceModel().package(row)

        if self._category == "updates" and not pkg.upgradable:
            return False
        if self._category == "installed" and not pkg.is_installed:
            return False
        if self._category == "available" and pkg.is_installed:
            return False
        if self._category == "local" and (pkg.in_repo or not pkg.is_installed):
            return False
        if self._repo and pkg.repo != self._repo:
            return False

        if self._text:
            haystack = f"{pkg.name} {pkg.summary}".lower()
            return all(token in haystack for token in self._text.split())
        return True


class ConfirmDialog(QDialog):
    """Shows the exact command before anything runs.

    slackpkg is driven with -batch=on -default_answer=y, so this dialog is the
    only place a human gets to say no.
    """

    def __init__(self, parent, title: str, blurb: str, command: str,
                 packages: list[str], destructive: bool,
                 space: backend.SpaceReport | None = None,
                 warning: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setStyleSheet(
            f"font-size:16px;font-weight:600;color:"
            f"{theme.DANGER if destructive else theme.TEXT};"
        )
        layout.addWidget(heading)

        summary = QLabel(blurb)
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color:{theme.MUTED};")
        layout.addWidget(summary)

        if warning:
            flag = QLabel(warning)
            flag.setWordWrap(True)
            flag.setStyleSheet(
                f"color:{theme.WARNING};font-size:12px;font-weight:600;")
            layout.addWidget(flag)

        if packages:
            listing = QPlainTextEdit("\n".join(packages))
            listing.setReadOnly(True)
            listing.setMaximumHeight(150)
            listing.setObjectName("Console")
            layout.addWidget(listing)

        if space is not None:
            lines = [
                f"Download  {backend.human_bytes(space.download_need)}"
                f"   ({backend.human_bytes(space.download_free)} free on "
                f"{space.download_path})"
                if space.download_free is not None else
                f"Download  {backend.human_bytes(space.download_need)}",
                f"Install   {backend.human_bytes(space.install_need)}"
                f"   ({backend.human_bytes(space.install_free)} free on "
                f"{space.install_path})"
                if space.install_free is not None else
                f"Install   {backend.human_bytes(space.install_need)}",
            ]
            sizes = QLabel("\n".join(lines))
            sizes.setStyleSheet(
                f"color:{theme.WARNING if space.short else theme.MUTED};"
                "font-family:monospace;font-size:11px;"
            )
            layout.addWidget(sizes)

            if space.short:
                which = []
                if space.download_short:
                    which.append(f"the download cache on {space.download_path}")
                if space.install_short:
                    which.append(f"{space.install_path}")
                warn = QLabel(
                    "Not enough free space on " + " and ".join(which) + ". "
                    "Running out part-way through leaves packages half-installed, "
                    "which on a system package can be hard to recover from. The "
                    "install figure does not subtract what the outgoing versions "
                    "give back, so it errs high."
                )
                warn.setWordWrap(True)
                warn.setStyleSheet(
                    f"color:{theme.WARNING};font-size:12px;font-weight:600;")
                layout.addWidget(warn)

        layout.addWidget(QLabel("Command", objectName="Status"))
        shown = QPlainTextEdit(command)
        shown.setReadOnly(True)
        shown.setObjectName("Console")
        shown.setMaximumHeight(64)
        layout.addWidget(shown)

        note = QLabel(
            "slackpkg will ask its own questions as it runs — including what to "
            "do with any new /etc config files. Answer them in the box under the "
            "log. Root access is requested separately."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.FAINT};font-size:11px;")
        layout.addWidget(note)

        # Enter must never be what uninstalls something, or what fills a disk.
        risky = destructive or bool(warning) or (space is not None and space.short)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        proceed = buttons.addButton(
            "Remove" if destructive else "Proceed", QDialogButtonBox.ButtonRole.AcceptRole
        )
        # The styling has to agree with the default button. Leaving Proceed as
        # the pink primary while Enter is wired to Cancel reads as a
        # recommendation to continue, which is the opposite of the intent.
        proceed.setProperty("variant", "danger" if risky else "primary")
        cancel.clicked.connect(self.reject)
        proceed.clicked.connect(self.accept)

        # setDefault() alone is not enough: QDialogButtonBox re-asserts the
        # AcceptRole button as default when the dialog is shown, so a plain
        # setDefault(True) on Cancel is silently undone and Enter still
        # proceeds. autoDefault has to be cleared on the other button for the
        # choice to survive show(). This is asserted in the tests rather than
        # trusted, because the failure is invisible -- the dialog looks right.
        for button, is_default in ((cancel, risky), (proceed, not risky)):
            button.setAutoDefault(is_default)
            button.setDefault(is_default)
        layout.addWidget(buttons)


class DetailPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Detail")
        self.setMinimumWidth(300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)

        self.name = QLabel("Nothing selected", objectName="DetailName")
        self.name.setWordWrap(True)
        self.version = QLabel("", objectName="DetailVersion")
        self.badge = QLabel("")
        self.badge.setVisible(False)

        badge_row = QHBoxLayout()
        badge_row.addWidget(self.badge)
        badge_row.addStretch(1)

        outer.addWidget(self.name)
        outer.addWidget(self.version)
        outer.addLayout(badge_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{theme.BORDER};")
        outer.addWidget(line)

        self.fields = QVBoxLayout()
        self.fields.setSpacing(8)
        outer.addLayout(self.fields)

        self.body = QLabel("", objectName="DetailBody")
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.body, 1)

        self._rows: list[QWidget] = []

    def _clear_fields(self) -> None:
        for widget in self._rows:
            widget.setParent(None)
        self._rows = []

    def _add_field(self, key: str, value: str) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        k = QLabel(key)
        k.setProperty("role", "key")
        k.setFixedWidth(92)
        v = QLabel(value)
        v.setProperty("role", "value")
        v.setWordWrap(True)
        layout.addWidget(k)
        layout.addWidget(v, 1)
        self.fields.addWidget(row)
        self._rows.append(row)

    def show_package(self, pkg: backend.Package | None) -> None:
        self._clear_fields()
        if pkg is None:
            self.name.setText("Nothing selected")
            self.version.setText("")
            self.body.setText("Select a package to see its details.")
            self.badge.setVisible(False)
            return

        self.name.setText(pkg.name)
        self.version.setText(pkg.available_id if pkg.in_repo else (pkg.installed or ""))

        status = status_of(pkg)
        self.badge.setText(status.upper())
        self.badge.setProperty(
            "badge",
            {"Update": "differs", "Installed": "installed",
             "Local": "installed", "Held": "installed"}.get(status, "available"),
        )
        self.badge.setVisible(True)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

        if pkg.is_installed:
            self._add_field("Installed", pkg.installed or "")
        if pkg.in_repo:
            self._add_field("Available", pkg.available_id)
            self._add_field("Repository", pkg.repo)
            if pkg.location:
                self._add_field("Location", pkg.location)
            if pkg.size_c:
                self._add_field("Download", pkg.size_c)
            if pkg.size_u:
                self._add_field("Installed size", pkg.size_u)
        else:
            self._add_field("Repository", "not offered by any configured mirror")

        self.body.setText(pkg.body or pkg.summary or "No description provided.")


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("slackpkg")
        self.resize(1320, 840)

        # .new files present before the current run, so the report afterwards
        # can tell what this run shipped from what was already waiting.
        self._configs_before: set = set()

        self.runner = runner.SlackpkgRunner(self)
        self.runner.output.connect(self._append_output)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self.runner.secret_input.connect(self._on_secret_input)

        self.model = PackageModel([])
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_sidebar())

        middle = QSplitter(Qt.Orientation.Vertical)
        middle.addWidget(self._build_table())
        middle.addWidget(self._build_console())
        middle.setSizes([700, 150])
        split.addWidget(middle)

        self.detail = DetailPanel()
        split.addWidget(self.detail)
        split.setSizes([196, 806, 318])
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        root.addWidget(self._build_actions())

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.reload)
        self.detail.show_package(None)
        self.reload()

    # ---- construction ------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QWidget(objectName="Header")
        header.setFixedHeight(72)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(14)

        title_holder = QWidget()
        title_holder.setFixedWidth(272)
        title_box = QVBoxLayout(title_holder)
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(1)
        title_box.addWidget(QLabel("slackpkg", objectName="Wordmark"))
        self.subtitle = QLabel("", objectName="Subtitle")
        self.subtitle.setWordWrap(True)
        title_box.addWidget(self.subtitle)
        layout.addWidget(title_holder)

        self.search = QLineEdit(objectName="Search")
        self.search.setPlaceholderText("Search packages…   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_text)
        self.search.setMaximumWidth(460)
        layout.addWidget(self.search, 1)

        self.btn_update = QPushButton("Refresh mirrors")
        self.btn_update.setToolTip("slackpkg update — re-download the package lists")
        self.btn_update.clicked.connect(self.do_update)
        layout.addWidget(self.btn_update)

        # Sequence left to right, because that is the order they must run in:
        # install-new before upgrade-all. A package the release has split in two
        # gets its other half from install-new; upgrade-all alone never installs
        # anything that is not already present, so it cannot fix that.
        self.btn_install_new = QPushButton("Install new")
        self.btn_install_new.setToolTip(
            "slackpkg install-new — install packages the distribution has added. "
            "Run this before Upgrade all.")
        self.btn_install_new.clicked.connect(self.do_install_new)
        layout.addWidget(self.btn_install_new)

        self.btn_upgrade_all = QPushButton("Upgrade all")
        self.btn_upgrade_all.clicked.connect(self.do_upgrade_all)
        layout.addWidget(self.btn_upgrade_all)
        return header

    def _build_sidebar(self) -> QWidget:
        side = QWidget(objectName="Sidebar")
        side.setMinimumWidth(180)
        side.setMaximumWidth(280)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        view_label = QLabel("VIEW")
        view_label.setProperty("role", "section")
        layout.addWidget(view_label)

        self.filters = QListWidget(objectName="Filters")
        self.filters.setFrameShape(QFrame.Shape.NoFrame)
        for key, label in CATEGORIES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.filters.addItem(item)
        self.filters.setCurrentRow(0)
        self.filters.currentItemChanged.connect(self._on_category)
        self.filters.setFixedHeight(len(CATEGORIES) * 36 + 8)
        layout.addWidget(self.filters)

        repo_label = QLabel("REPOSITORIES")
        repo_label.setProperty("role", "section")
        layout.addWidget(repo_label)

        self.repos = QListWidget(objectName="Filters")
        self.repos.setFrameShape(QFrame.Shape.NoFrame)
        self.repos.currentItemChanged.connect(self._on_repo)
        layout.addWidget(self.repos, 1)
        return side

    def _build_table(self) -> QWidget:
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setHighlightSections(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 240)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        return self.table

    def _build_console(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QWidget(objectName="ConsoleBar")
        bar.setFixedHeight(38)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 0, 10, 0)
        self.status = QLabel("Ready", objectName="Status")
        bar_layout.addWidget(self.status)
        bar_layout.addStretch(1)
        self.btn_cancel = QPushButton("Stop")
        self.btn_cancel.setProperty("variant", "danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.runner.cancel)
        bar_layout.addWidget(self.btn_cancel)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.console.clear())
        bar_layout.addWidget(clear)
        layout.addWidget(bar)

        self.console = QPlainTextEdit(objectName="Console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        layout.addWidget(self.console, 1)

        # slackpkg asks real questions now, so there has to be somewhere to
        # answer them. A line plus Enter rather than raw keystrokes on purpose:
        # a single stray keypress should not be able to answer "overwrite all
        # my config files", and the pty echoes what is sent so the answer lands
        # in the transcript next to the question.
        reply = QWidget(objectName="ConsoleBar")
        reply.setFixedHeight(42)
        reply_layout = QHBoxLayout(reply)
        reply_layout.setContentsMargins(14, 0, 10, 0)
        reply_layout.setSpacing(8)

        self.prompt_hint = QLabel("Answer", objectName="Status")
        reply_layout.addWidget(self.prompt_hint)

        self.reply = QLineEdit(objectName="Search")
        self.reply.setPlaceholderText("nothing is waiting for input")
        self.reply.setEnabled(False)
        self.reply.returnPressed.connect(self._send_reply)
        reply_layout.addWidget(self.reply, 1)

        self.btn_send = QPushButton("Send")
        self.btn_send.setEnabled(False)
        self.btn_send.clicked.connect(self._send_reply)
        reply_layout.addWidget(self.btn_send)

        layout.addWidget(reply)
        return wrapper

    def _on_secret_input(self, secret: bool) -> None:
        """Mask the answer box while the child has terminal echo switched off.

        That is a password prompt -- pkexec's own, if polkit ever falls back
        from the KDE agent to a text one. The pty will not echo it back into
        the log, so the box is the only place it could have been visible.
        """
        self.reply.setEchoMode(
            QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)
        self.prompt_hint.setText("Password" if secret else "Answer")
        if secret:
            self.reply.setPlaceholderText("hidden — press Enter to send")
            self.reply.setFocus()

    def _send_reply(self) -> None:
        if not self.runner.busy:
            return
        # Empty is a legitimate answer -- it is how you take a prompt's own
        # default -- so this deliberately does not require any text.
        self.runner.send(self.reply.text())
        self.reply.clear()

    def _build_actions(self) -> QWidget:
        bar = QWidget(objectName="ConsoleBar")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)

        self.selection_label = QLabel("No selection", objectName="Status")
        layout.addWidget(self.selection_label)
        layout.addStretch(1)

        self.btn_install = QPushButton("Install")
        self.btn_install.setProperty("variant", "primary")
        self.btn_install.clicked.connect(lambda: self.act("install"))
        self.btn_upgrade = QPushButton("Upgrade")
        self.btn_upgrade.clicked.connect(lambda: self.act("upgrade"))
        self.btn_reinstall = QPushButton("Reinstall")
        self.btn_reinstall.clicked.connect(lambda: self.act("reinstall"))
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setProperty("variant", "danger")
        self.btn_remove.clicked.connect(lambda: self.act("remove"))

        for button in (self.btn_install, self.btn_upgrade, self.btn_reinstall, self.btn_remove):
            button.setEnabled(False)
            layout.addWidget(button)
        return bar

    # ---- data --------------------------------------------------------
    def reload(self) -> None:
        packages = backend.load()
        self.model.beginResetModel()
        self.model.packages = packages
        self.model.endResetModel()

        repos = sorted({p.repo for p in packages if p.repo})
        self.repos.blockSignals(True)
        self.repos.clear()
        every = QListWidgetItem("All repositories")
        every.setData(Qt.ItemDataRole.UserRole, None)
        self.repos.addItem(every)
        for repo in repos:
            item = QListWidgetItem(repo)
            item.setData(Qt.ItemDataRole.UserRole, repo)
            self.repos.addItem(item)
        self.repos.setCurrentRow(0)
        self.repos.blockSignals(False)

        updates = sum(1 for p in packages if p.upgradable)
        installed = sum(1 for p in packages if p.is_installed)
        pending_new = len(backend.pending_new_packages(packages))

        # Both top-bar buttons carry their own count and only light up when
        # they have something to do. Neither did before: "Upgrade all" was
        # hardcoded to the primary variant so it read as the recommended action
        # on a fully up-to-date system, and "Install new" had no variant at all
        # so it stayed flat even with packages waiting -- the two failures point
        # opposite ways and cancel out into "the buttons mean nothing".
        self._set_action_state(self.btn_install_new, "Install new", pending_new)
        self._set_action_state(self.btn_upgrade_all, "Upgrade all", updates)

        updated = backend.last_update()
        stamp = f"package lists from {updated}" if updated else "package lists never refreshed"
        counts = f"{len(packages)} packages · {installed} installed · {updates} updates"
        if pending_new:
            counts += f" · {pending_new} new"
        self.subtitle.setText(f"{counts}\n{stamp}")
        self._on_selection()

    @staticmethod
    def _set_action_state(button, label: str, count: int) -> None:
        """Label with the count, and light the button only when count > 0.

        Qt does not restyle on a dynamic property change by itself, so the
        unpolish/polish pair is required -- without it the property is correct
        and the button keeps its old colour, which looks exactly like the bug
        this is fixing.
        """
        button.setText(f"{label} ({count})" if count else label)
        button.setProperty("variant", "primary" if count else None)
        button.style().unpolish(button)
        button.style().polish(button)

    def selected(self) -> list[backend.Package]:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [self.model.package(self.proxy.mapToSource(
            self.proxy.index(row, 0)).row()) for row in rows]

    # ---- events ------------------------------------------------------
    def _on_category(self, current: QListWidgetItem | None) -> None:
        if current:
            self.proxy.set_category(current.data(Qt.ItemDataRole.UserRole))

    def _on_repo(self, current: QListWidgetItem | None) -> None:
        if current:
            self.proxy.set_repo(current.data(Qt.ItemDataRole.UserRole))

    def _on_selection(self, *_args) -> None:
        packages = self.selected()
        self.detail.show_package(packages[0] if len(packages) == 1 else None)

        busy = self.runner.busy
        # makelist applies the blacklist to every command except search and
        # download (core-functions.sh:865-873), so a held package is inert for
        # all four of these -- not just upgrade.
        live = [p for p in packages if not p.blacklisted]
        installable = [p for p in live if p.in_repo and not p.is_installed]
        upgradable = [p for p in live if p.upgradable]
        removable = [p for p in live if p.is_installed]
        reinstallable = [p for p in live if p.in_repo and p.is_installed]

        self.btn_install.setEnabled(bool(installable) and not busy)
        self.btn_upgrade.setEnabled(bool(upgradable) and not busy)
        self.btn_reinstall.setEnabled(bool(reinstallable) and not busy)
        self.btn_remove.setEnabled(bool(removable) and not busy)

        if not packages:
            self.selection_label.setText("No selection")
        elif len(packages) == 1:
            self.selection_label.setText(f"{packages[0].name} selected")
        else:
            self.selection_label.setText(f"{len(packages)} packages selected")

    # ---- actions -----------------------------------------------------
    def _confirm_and_run(self, command: str, packages: list[str],
                         blurb: str, destructive: bool = False,
                         pkg_objs: list[backend.Package] | None = None,
                         warning: str | None = None) -> None:
        if self.runner.busy:
            return
        space = backend.space_report(pkg_objs or [], command)
        dialog = ConfirmDialog(
            self,
            {"install": "Install packages", "upgrade": "Upgrade packages",
             "reinstall": "Reinstall packages", "remove": "Remove packages",
             "upgrade-all": "Upgrade everything", "update": "Refresh package lists",
             "install-new": "Install new packages"}[command],
            blurb,
            runner.describe(command, packages),
            packages,
            destructive,
            space,
            warning,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.runner.run(command, packages)

    def act(self, command: str) -> None:
        wanted = {
            "install": lambda p: p.in_repo and not p.is_installed,
            "upgrade": lambda p: p.upgradable,
            "reinstall": lambda p: p.in_repo and p.is_installed,
            "remove": lambda p: p.is_installed,
        }[command]
        # Blacklisted packages are filtered out of slackpkg's own list, so
        # passing one produces exit 20 and no work. Drop them here instead.
        chosen = [p for p in self.selected() if wanted(p) and not p.blacklisted]
        if not chosen:
            return
        names = [p.name for p in chosen]
        blurbs = {
            "install": "These packages will be downloaded and installed.",
            "upgrade": "These packages will be replaced with the version the mirror offers.",
            "reinstall": "These packages will be downloaded and installed over the current copy.",
            "remove": "These packages will be uninstalled. Removing a system package can "
                      "leave the machine unbootable — check the list carefully.",
        }
        self._confirm_and_run(command, names, blurbs[command],
                              destructive=(command == "remove"), pkg_objs=chosen)

    def do_update(self) -> None:
        self._confirm_and_run(
            "update", [],
            "Refreshes the package lists in /var/lib/slackpkg. If the mirror's "
            "ChangeLog has not moved since the last refresh, slackpkg stops "
            "rather than re-downloading the metadata unchanged. Installed "
            "packages are not touched.",
        )

    def do_install_new(self) -> None:
        pending = backend.pending_new_packages(self.model.packages)
        if not pending:
            QMessageBox.information(
                self, "Nothing to do",
                "The distribution has not added any package that is missing "
                "here. Nothing for install-new to install.")
            return
        self._confirm_and_run(
            "install-new", [],
            f"{len(pending)} package(s) have been added to the distribution and "
            "are not installed here. slackpkg upgrades the solibs packages "
            "first, then installs these. Nothing already installed is touched.",
            pkg_objs=pending,
        )

    def do_upgrade_all(self) -> None:
        count = sum(1 for p in self.model.packages if p.upgradable)
        held = sum(1 for p in self.model.packages if p.differs and p.blacklisted)
        pending_new = backend.pending_new_packages(self.model.packages)
        if count == 0:
            note = "No installed package differs from the mirror."
            if held:
                note = (f"{held} package(s) differ from the mirror, but every one "
                        "is blacklisted in /etc/slackpkg/blacklist, so slackpkg "
                        "will not upgrade them.")
            QMessageBox.information(self, "Nothing to do", note)
            return
        self._confirm_and_run(
            "upgrade-all", [],
            f"{count} packages differ from the mirror. slackpkg upgrades its own "
            "package first if needed, then pkgtools and the core libraries, before "
            "everything else. If it upgrades itself it will stop and ask to be run again.",
            pkg_objs=[p for p in self.model.packages if p.upgradable],
            warning=(
                f"{len(pending_new)} new package(s) are waiting — run Install new "
                "first. upgrade-all only touches packages you already have, so "
                "anything the release has newly split out or added stays missing, "
                "and the upgraded packages may expect it."
                if pending_new else None
            ),
        )

    # ---- process feedback --------------------------------------------
    def _on_started(self, command: str) -> None:
        self._configs_before = set(backend.find_new_config_files())
        self.console.appendPlainText(f"$ {command}\n")
        self.status.setText("Running…")
        self.btn_cancel.setEnabled(True)
        self.reply.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.reply.setPlaceholderText(
            "type an answer and press Enter — e.g. y, n, or K/O/R/P")
        self.reply.setFocus()
        for button in (self.btn_install, self.btn_upgrade, self.btn_reinstall,
                       self.btn_remove, self.btn_update, self.btn_install_new,
                       self.btn_upgrade_all):
            button.setEnabled(False)

    def _append_output(self, chunk: str) -> None:
        # slackpkg writes for a terminal, so the stream carries backspaces and
        # carriage returns meant to move a cursor that a document does not
        # have.  Appending it verbatim is what drew the box-character trail
        # through the progress counter.  console.tokenize turns those into
        # edits; see console.py for which sequences and why.
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for op, value in console.tokenize(chunk):
            if op == console.TEXT:
                cursor.insertText(str(value))
            elif op == console.BACK:
                for _ in range(int(value)):
                    if cursor.positionInBlock() == 0:
                        break          # column 0: a backspace is a no-op here
                    cursor.deletePreviousChar()
            elif op == console.KILL:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock,
                                    QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def _on_finished(self, code: int, message: str) -> None:
        self.console.appendPlainText(f"\n— {message} (exit {code})\n")
        self.status.setText(message)
        self.btn_cancel.setEnabled(False)
        self.reply.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.reply.setPlaceholderText("nothing is waiting for input")
        self.btn_update.setEnabled(True)
        self.btn_install_new.setEnabled(True)
        self.btn_upgrade_all.setEnabled(True)
        self._report_new_configs()
        QTimer.singleShot(200, self.reload)

    def _report_new_configs(self) -> None:
        """Say which .new config files are waiting. Never touch them.

        slackpkg would have ended the run by offering to overwrite the live
        files with these; runner.py disables that hook, so this replaces it
        with a report. Merging a shipped config into one you have edited is a
        decision that belongs to you, and the GUI deliberately has no button
        for it.
        """
        waiting = backend.find_new_config_files()
        if not waiting:
            return

        fresh = [f for f in waiting if f not in self._configs_before]
        # Careful with the wording: slackpkg now asks about these itself, so
        # claiming nothing changed would be a lie if the answer was O or R.
        self.console.appendPlainText(
            f"{len(waiting)} new configuration file(s) still on disk "
            f"({len(fresh)} appeared during this run):"
        )
        for path in waiting:
            self.console.appendPlainText(f"    {path}"
                                         + ("   <- new" if path in fresh else ""))
        self.console.appendPlainText("")

        # Only interrupt for files this run actually produced. The ones already
        # sitting there are reported every time and do not warrant a dialog.
        if not fresh:
            return
        listing = "\n".join(f"    {f}" for f in fresh)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("New configuration files")
        box.setText(f"{len(fresh)} package(s) shipped a new config file.")
        box.setInformativeText(
            f"These are still waiting after the run:\n\n{listing}\n\n"
            "slackpkg asks what to do with them as part of the run; anything "
            "left here was kept. Merge them when you are ready — the GUI itself "
            "never edits /etc."
        )
        box.exec()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    app = QApplication(argv)
    app.setApplicationName("slackpkg")
    app.setStyleSheet(theme.stylesheet())

    window = MainWindow()
    window.show()

    # --screenshot PATH renders the window and exits; used to iterate on the
    # design without a display.
    if "--screenshot" in argv:
        target = Path(argv[argv.index("--screenshot") + 1])
        window.filters.setCurrentRow(1)          # the Updates view
        app.processEvents()
        if window.proxy.rowCount():
            window.table.selectRow(0)
        app.processEvents()
        QTimer.singleShot(60, lambda: (window.grab().save(str(target)), app.quit()))
        return app.exec()

    return app.exec()
