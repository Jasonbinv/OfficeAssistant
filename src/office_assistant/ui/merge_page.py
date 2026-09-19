from __future__ import annotations

from pathlib import Path

from office_assistant.naming import natural_sort_key, unique_path, unique_path_excluding
from office_assistant.pdf_ops import merge_pdfs, probe_pdf
from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

PATH_ROLE = int(Qt.ItemDataRole.UserRole)
COLOR_OK = QColor("#0b6e4f")
COLOR_BAD = QColor("#c0392b")
STATUS_OK = "完好"
STATUS_PASSWORD = "需要密码"
STATUS_BROKEN = "损坏"
STATUS_NOT_PDF = "非 PDF"


def ask_existing_dest(parent: QWidget | None, dest: Path) -> Path | None:
    box = QMessageBox(parent)
    box.setWindowTitle("提示")
    box.setText(f"目标已存在：{dest.name}\n请选择：")
    unique_btn = box.addButton("自动加序号", QMessageBox.ButtonRole.AcceptRole)
    overwrite_btn = box.addButton("覆盖该目标", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked == unique_btn:
        return unique_path(dest)
    if clicked == overwrite_btn:
        return dest
    return None


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _dest_is_source(dest: Path, sources: list[Path]) -> bool:
    return any(_same_path(dest, src) for src in sources)


class _MergeTable(QTableWidget):
    paths_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["文件", "状态"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.source() is self:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls() or event.source() is self:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.toLocalFile()]
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
            return
        source_row = self.currentRow()
        pos = event.position().toPoint()
        target_row = self.indexAt(pos).row()
        if target_row < 0:
            target_row = self.rowCount() - 1
        if source_row < 0 or target_row < 0 or source_row == target_row:
            event.ignore()
            return
        items = [self.takeItem(source_row, col) for col in range(self.columnCount())]
        self.removeRow(source_row)
        insert_at = target_row if target_row < source_row else target_row
        insert_at = min(insert_at, self.rowCount())
        self.insertRow(insert_at)
        for col, item in enumerate(items):
            self.setItem(insert_at, col, item)
        self.selectRow(insert_at)
        event.acceptProposedAction()


class MergePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.passwords: dict[Path, str] = {}
        self.setAcceptDrops(True)
        self._build_ui()
        self.sync_action_buttons()

    def _build_ui(self) -> None:
        self.add_btn = QPushButton("添加文件")
        self.remove_btn = QPushButton("移除")
        self.up_btn = QPushButton("上移")
        self.down_btn = QPushButton("下移")
        self.clear_btn = QPushButton("清空")
        self.add_btn.clicked.connect(self._browse_files)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.up_btn.clicked.connect(lambda: self._move_row(-1))
        self.down_btn.clicked.connect(lambda: self._move_row(1))
        self.clear_btn.clicked.connect(self._clear_rows)

        tools = QHBoxLayout()
        tools.addWidget(self.add_btn)
        tools.addWidget(self.remove_btn)
        tools.addWidget(self.up_btn)
        tools.addWidget(self.down_btn)
        tools.addWidget(self.clear_btn)
        tools.addStretch(1)

        self.table = _MergeTable()
        self.table.paths_dropped.connect(self.handle_dropped_paths)
        self.table.cellClicked.connect(lambda row, _col: self.prompt_password_for_row(row))

        self.skip_check = QCheckBox("合并其余完好文件")
        self.skip_check.setChecked(False)
        self.skip_check.toggled.connect(lambda _checked=False: self.sync_action_buttons())

        self.start_btn = QPushButton("开始合并")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.start_btn)

        root = QVBoxLayout(self)
        root.addLayout(tools)
        root.addWidget(self.table, 1)
        root.addWidget(self.skip_check)
        root.addLayout(buttons)

    def _path_at(self, row: int) -> Path:
        item = self.table.item(row, 0)
        stored = item.data(PATH_ROLE) if item is not None else None
        return Path(stored) if stored else Path()

    def _known_paths(self) -> set[Path]:
        known: set[Path] = set()
        for row in range(self.table.rowCount()):
            path = self._path_at(row)
            if path.as_posix() != ".":
                known.add(path.resolve())
        return known

    def _all_paths(self) -> list[Path]:
        return [self._path_at(row) for row in range(self.table.rowCount())]

    def _status_at(self, row: int) -> str:
        item = self.table.item(row, 1)
        return item.text() if item is not None else ""

    def _good_paths(self) -> list[Path]:
        return [
            self._path_at(row)
            for row in range(self.table.rowCount())
            if self._status_at(row) == STATUS_OK
        ]

    def _has_non_good(self) -> bool:
        return any(self._status_at(row) != STATUS_OK for row in range(self.table.rowCount()))

    def _status_text(self, path: Path, info) -> str:
        if path.suffix.lower() != ".pdf":
            return STATUS_NOT_PDF
        if info.ok:
            return STATUS_OK
        if info.needs_password:
            return STATUS_PASSWORD
        if info.error == "损坏":
            return STATUS_BROKEN
        return info.error or STATUS_BROKEN

    def _set_status_item(self, row: int, status: str) -> None:
        item = self.table.item(row, 1)
        if item is None:
            item = QTableWidgetItem(status)
            self.table.setItem(row, 1, item)
        item.setText(status)
        color = COLOR_OK if status == STATUS_OK else COLOR_BAD
        item.setForeground(QBrush(color))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)

    def _insert_row(self, path: Path, status: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(path.name)
        name.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        name.setData(PATH_ROLE, str(path))
        status_item = QTableWidgetItem(status)
        status_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        status_item.setData(PATH_ROLE, str(path))
        self.table.setItem(row, 0, name)
        self.table.setItem(row, 1, status_item)
        self._set_status_item(row, status)

    def _add_one(self, path: Path) -> None:
        path = Path(path)
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in self._known_paths():
            return
        password = self.passwords.get(key)
        info = probe_pdf(path, password)
        self._insert_row(path, self._status_text(path, info))

    def add_paths(self, paths: list[Path]) -> None:
        for path in paths:
            path = Path(path)
            if path.is_dir():
                children = sorted(path.iterdir(), key=lambda child: natural_sort_key(child.name))
                for child in children:
                    if child.is_file() and child.suffix.lower() == ".pdf":
                        self._add_one(child)
            elif path.is_file():
                self._add_one(path)
        self.sync_action_buttons()

    def handle_dropped_paths(self, paths: list[Path]) -> None:
        self.add_paths([Path(path) for path in paths if path])

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "添加 PDF", "", "PDF (*.pdf);;所有文件 (*.*)")
        if files:
            self.add_paths([Path(name) for name in files])

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        path = self._path_at(row)
        self.passwords.pop(path.resolve(), None)
        self.table.removeRow(row)
        self.sync_action_buttons()

    def _move_row(self, delta: int) -> None:
        row = self.table.currentRow()
        dest = row + delta
        if row < 0 or dest < 0 or dest >= self.table.rowCount():
            return
        items = [self.table.takeItem(row, col) for col in range(self.table.columnCount())]
        self.table.removeRow(row)
        self.table.insertRow(dest)
        for col, item in enumerate(items):
            self.table.setItem(dest, col, item)
        self.table.selectRow(dest)

    def _clear_rows(self) -> None:
        self.table.setRowCount(0)
        self.passwords.clear()
        self.sync_action_buttons()

    def prompt_password_for_row(self, row: int) -> None:
        if row < 0 or self._status_at(row) != STATUS_PASSWORD:
            return
        path = self._path_at(row)
        text, ok = QInputDialog.getText(
            self, "密码", f"{path.name} 需要密码", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        password = text if text else None
        info = probe_pdf(path, password)
        if info.ok:
            if password is not None:
                self.passwords[path.resolve()] = password
            self._set_status_item(row, STATUS_OK)
            self.sync_action_buttons()
            return
        QMessageBox.warning(self, "提示", "密码错误")

    def _job_busy(self) -> bool:
        window = self.window()
        busy = getattr(window, "job_busy", None)
        if callable(busy):
            return bool(busy())
        return getattr(window, "_thread", None) is not None

    def sync_action_buttons(self) -> None:
        if self._job_busy():
            self.start_btn.setEnabled(False)
            return
        good = self._good_paths()
        if len(good) < 2:
            self.start_btn.setEnabled(False)
            return
        if self._has_non_good() and not self.skip_check.isChecked():
            self.start_btn.setEnabled(False)
            return
        self.start_btn.setEnabled(True)

    def _cancel_event(self):
        return getattr(self.window(), "cancel_event", None)

    def _start_job(self, fn, on_done) -> None:
        window = self.window()
        start = getattr(window, "start_job", None)
        if callable(start):
            start(fn, on_done)
            return
        try:
            on_done(fn())
        except Exception as exc:
            QMessageBox.warning(self, "提示", str(exc))

    def _set_summary(self, text: str) -> None:
        label = getattr(self.window(), "summary_label", None)
        if label is not None:
            label.setText(text)

    def _on_start(self) -> None:
        if not self.start_btn.isEnabled():
            return
        good = self._good_paths()
        if len(good) < 2:
            return
        first = good[0]
        default = first.with_name(f"{first.stem}_合并.pdf")
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "保存合并结果",
            str(default),
            "PDF (*.pdf)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not chosen:
            return
        dest = Path(chosen)
        sources = self._all_paths()
        if _dest_is_source(dest, sources):
            QMessageBox.warning(self, "提示", "输出路径不能与源文件相同，请换一个名字")
            return
        if dest.exists():
            dest = ask_existing_dest(self, dest)
            if dest is None:
                return
        if _dest_is_source(dest, sources):
            dest = unique_path_excluding(dest, sources)
            if _dest_is_source(dest, sources):
                QMessageBox.warning(self, "提示", "输出路径不能与源文件相同，请换一个名字")
                return
        paths = list(good)
        passwords = dict(self.passwords)

        def job():
            completed = merge_pdfs(paths, dest, passwords=passwords, cancel_event=self._cancel_event())
            return dest if completed else None

        self.start_btn.setEnabled(False)
        self._start_job(job, self._on_merge_done)

    def _on_merge_done(self, result: object) -> None:
        if isinstance(result, Path):
            self._set_summary(f"已合并保存到 {result.name}")
        elif result is None:
            self._set_summary("已取消")
        else:
            self._set_summary(str(result))
        self.sync_action_buttons()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.toLocalFile()]
        self.handle_dropped_paths(paths)
        event.acceptProposedAction()
