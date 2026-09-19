from __future__ import annotations

from pathlib import Path

from office_assistant.naming import parse_name_list
from office_assistant.qt_preload import preload_pyside6
from office_assistant.rename_ops import (
    STATUS_COLLISION,
    STATUS_INVALID,
    STATUS_MISSING_LINE,
    STATUS_OK,
    STATUS_UNCHANGED,
    ExecuteResult,
    execute_renames,
    list_directory_files,
    preview_list_rename,
    preview_template_rename,
    snapshot_ok,
    undo_renames,
)

preload_pyside6()

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

EXTENSIONS = (
    "pdf",
    "dwg",
    "dxf",
    "jpg",
    "jpeg",
    "png",
    "tif",
    "tiff",
    "doc",
    "docx",
    "xls",
    "xlsx",
)
DEFAULT_TEMPLATE = "{原名}_{序号}"
PATH_ROLE = int(Qt.ItemDataRole.UserRole)
COLOR_OK = QColor("#0b6e4f")
COLOR_BAD = QColor("#c0392b")
COLOR_UNCHANGED = QColor("#888888")
STATUS_COLORS = {
    STATUS_OK: COLOR_OK,
    STATUS_MISSING_LINE: COLOR_BAD,
    STATUS_INVALID: COLOR_BAD,
    STATUS_COLLISION: COLOR_BAD,
    STATUS_UNCHANGED: COLOR_UNCHANGED,
}
SNAPSHOT_STALE = "__snapshot_stale__"


class _ReorderTable(QTableWidget):
    reordered = Signal()
    paths_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["参与", "当前文件名", "新文件名"])
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
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

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
        self.reordered.emit()


class RenamePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = False
        self._preview = None
        self._last_batch: ExecuteResult | None = None
        self._ext_boxes: dict[str, QCheckBox] = {}
        self.setAcceptDrops(True)
        self._build_ui()
        self._rebuild_preview()

    def _build_ui(self) -> None:
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择或拖入文件夹")
        self.dir_edit.editingFinished.connect(lambda: self.refresh_files())

        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._browse_directory)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(lambda: self.refresh_files())

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("目录"))
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(refresh_btn)

        ext_row = QHBoxLayout()
        for ext in EXTENSIONS:
            box = QCheckBox(ext)
            box.setChecked(ext == "pdf")
            box.toggled.connect(lambda _checked=False: self._on_ext_toggled())
            self._ext_boxes[ext] = box
            ext_row.addWidget(box)
        ext_row.addStretch(1)

        self.list_radio = QRadioButton("名单改名")
        self.rule_radio = QRadioButton("规则改名")
        self.list_radio.setChecked(True)
        self.list_radio.toggled.connect(lambda _checked=False: self._on_mode_changed())

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.list_radio)
        mode_row.addWidget(self.rule_radio)
        mode_row.addStretch(1)

        self.name_edit = QPlainTextEdit()
        self.name_edit.setPlaceholderText("粘贴名单，一行一个新名字")
        self.name_edit.textChanged.connect(self._rebuild_preview)

        self.template_edit = QLineEdit(DEFAULT_TEMPLATE)
        self.prefix_edit = QLineEdit()
        self.suffix_edit = QLineEdit()
        for widget in (self.template_edit, self.prefix_edit, self.suffix_edit):
            widget.textChanged.connect(lambda _text="": self._rebuild_preview())

        rule_panel = QWidget()
        rule_layout = QHBoxLayout(rule_panel)
        rule_layout.setContentsMargins(0, 0, 0, 0)
        rule_layout.addWidget(QLabel("模板"))
        rule_layout.addWidget(self.template_edit, 1)
        rule_layout.addWidget(QLabel("前缀"))
        rule_layout.addWidget(self.prefix_edit)
        rule_layout.addWidget(QLabel("后缀"))
        rule_layout.addWidget(self.suffix_edit)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.name_edit)
        self.mode_stack.addWidget(rule_panel)

        self.copy_check = QCheckBox("复制保留原件")
        self.copy_check.setChecked(False)
        self.copy_check.toggled.connect(lambda _checked=False: self._rebuild_preview())

        self.table = _ReorderTable()
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.reordered.connect(self._rebuild_preview)
        self.table.paths_dropped.connect(self.handle_dropped_paths)

        self.unused_label = QLabel("")
        self.unused_label.setStyleSheet("color: #c0392b;")
        self.unused_label.setWordWrap(True)

        self.confirm_btn = QPushButton("确认重命名")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._on_confirm)
        self.undo_btn = QPushButton("撤销上次重命名")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._on_undo)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.confirm_btn)
        buttons.addWidget(self.undo_btn)

        root = QVBoxLayout(self)
        root.addLayout(dir_row)
        root.addLayout(ext_row)
        root.addLayout(mode_row)
        root.addWidget(self.mode_stack)
        root.addWidget(self.copy_check)
        root.addWidget(self.table, 1)
        root.addWidget(self.unused_label)
        root.addLayout(buttons)

    def _on_mode_changed(self) -> None:
        self.mode_stack.setCurrentIndex(0 if self.list_radio.isChecked() else 1)
        self._rebuild_preview()

    def _on_ext_toggled(self) -> None:
        if not self._updating:
            self.refresh_files()

    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        if not self._updating:
            self._rebuild_preview()

    def _browse_directory(self) -> None:
        start = self.dir_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择目录", start)
        if chosen:
            self.dir_edit.setText(chosen)
            self.refresh_files()

    def _selected_extensions(self) -> set[str]:
        return {ext for ext, box in self._ext_boxes.items() if box.isChecked()}

    def _insert_file_row(self, path: Path, checked: bool) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        check.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        check.setData(PATH_ROLE, str(path))
        old = QTableWidgetItem(path.name)
        old.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        old.setData(PATH_ROLE, str(path))
        new = QTableWidgetItem("")
        new.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        self.table.setItem(row, 0, check)
        self.table.setItem(row, 1, old)
        self.table.setItem(row, 2, new)

    def _previous_checks(self) -> dict[Path, bool]:
        previous: dict[Path, bool] = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            stored = item.data(PATH_ROLE)
            if not stored:
                continue
            previous[Path(stored).resolve()] = item.checkState() == Qt.CheckState.Checked
        return previous

    def refresh_files(self, checked_paths: set[Path] | None = None) -> None:
        previous = {} if checked_paths is not None else self._previous_checks()
        wanted = {path.resolve() for path in checked_paths} if checked_paths is not None else None
        directory_text = self.dir_edit.text().strip()
        directory = Path(directory_text) if directory_text else None

        self._updating = True
        self.table.setRowCount(0)
        if directory is not None and directory.is_dir():
            files = list_directory_files(directory, self._selected_extensions())
            for path in files:
                key = path.resolve()
                if wanted is not None:
                    checked = key in wanted
                else:
                    checked = previous.get(key, True)
                self._insert_file_row(path, checked)
        self._updating = False
        self._rebuild_preview()

    def handle_dropped_paths(self, paths: list[Path]) -> None:
        cleaned = [Path(path) for path in paths if path]
        if not cleaned:
            return
        if len(cleaned) == 1 and cleaned[0].is_dir():
            self.dir_edit.setText(str(cleaned[0]))
            self.refresh_files()
            return
        files = [path for path in cleaned if path.is_file()]
        if len(files) != len(cleaned) or len({path.parent.resolve() for path in files}) != 1:
            QMessageBox.warning(self, "提示", "只支持同一文件夹")
            return
        directory = files[0].parent
        self.dir_edit.setText(str(directory))
        self._updating = True
        for path in files:
            ext = path.suffix.lstrip(".").casefold()
            box = self._ext_boxes.get(ext)
            if box is not None:
                box.setChecked(True)
        self._updating = False
        self.refresh_files(checked_paths={path.resolve() for path in files})

    def _collect_files_checked(self) -> tuple[list[Path], list[bool]]:
        files: list[Path] = []
        checked: list[bool] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            stored = item.data(PATH_ROLE)
            if not stored:
                continue
            files.append(Path(stored))
            checked.append(item.checkState() == Qt.CheckState.Checked)
        return files, checked

    def _rebuild_preview(self) -> None:
        if self._updating:
            return
        files, checked = self._collect_files_checked()
        copy = self.copy_check.isChecked()
        if self.list_radio.isChecked():
            names = parse_name_list(self.name_edit.toPlainText())
            preview = preview_list_rename(files, checked, names, copy=copy)
        else:
            preview = preview_template_rename(
                files,
                checked,
                template=self.template_edit.text(),
                prefix=self.prefix_edit.text(),
                suffix=self.suffix_edit.text(),
                copy=copy,
            )
        self._preview = preview
        self._updating = True
        for row_index, row in enumerate(preview.rows):
            item = self.table.item(row_index, 2)
            if item is None:
                continue
            if row.status == STATUS_MISSING_LINE:
                text = row.message or "（名单缺一行）"
            else:
                text = row.new_name or row.message
            item.setText(text)
            color = STATUS_COLORS.get(row.status)
            if color is not None:
                item.setForeground(QBrush(color))
            else:
                item.setForeground(QBrush())
            item.setToolTip(row.message)
        self._updating = False
        if preview.unused_names:
            self.unused_label.setText("未使用的名单：" + "、".join(preview.unused_names))
        else:
            self.unused_label.setText("")
        self.sync_action_buttons()

    def _job_busy(self) -> bool:
        window = self.window()
        busy = getattr(window, "job_busy", None)
        if callable(busy):
            return bool(busy())
        return getattr(window, "_thread", None) is not None

    def sync_action_buttons(self) -> None:
        if self._job_busy():
            self.confirm_btn.setEnabled(False)
            self.undo_btn.setEnabled(False)
            return
        has_ok = self._preview is not None and any(
            row.status == STATUS_OK for row in self._preview.rows
        )
        self.confirm_btn.setEnabled(has_ok)
        self.undo_btn.setEnabled(self._last_batch is not None)

    def _disable_rename_actions_for_job(self) -> None:
        self.confirm_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)

    def _set_summary(self, text: str) -> None:
        label = getattr(self.window(), "summary_label", None)
        if label is not None:
            label.setText(text)

    def _format_summary(self, result: ExecuteResult) -> str:
        skipped = f"跳过 {len(result.skipped)} 个"
        if result.skipped:
            skipped += f"（{'；'.join(result.skipped)}）"
        failed = f"失败 {len(result.failed)} 个"
        if result.failed:
            failed += f"（{'；'.join(result.failed)}）"
        text = f"成功 {len(result.succeeded)} 个，{skipped}，{failed}"
        if result.temps_left:
            names = "、".join(path.name for path in result.temps_left)
            text += f"。残留临时文件：{names}"
        return text

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

    def _warn_stale(self) -> None:
        self.refresh_files()
        QMessageBox.warning(self, "提示", "文件已变化，请确认后重试")

    def _on_confirm(self) -> None:
        if self._job_busy():
            return
        preview = self._preview
        if preview is None or not any(row.status == STATUS_OK for row in preview.rows):
            return
        if not snapshot_ok(preview):
            self._warn_stale()
            return
        rows = list(preview.rows)
        copy = preview.copy

        def job():
            if not snapshot_ok(preview):
                return SNAPSHOT_STALE
            return execute_renames(rows, copy=copy, cancel_event=self._cancel_event())

        self._disable_rename_actions_for_job()
        self._start_job(job, self._on_execute_done)

    def _on_execute_done(self, result: object) -> None:
        if result == SNAPSHOT_STALE:
            self._warn_stale()
            self.sync_action_buttons()
            return
        if not isinstance(result, ExecuteResult):
            self._set_summary(str(result))
            self.sync_action_buttons()
            return
        self._last_batch = result if result.succeeded else None
        self._set_summary(self._format_summary(result))
        self.refresh_files()
        self.sync_action_buttons()

    def _on_undo(self) -> None:
        batch = self._last_batch
        if batch is None or self._job_busy():
            return

        def job():
            return undo_renames(batch, cancel_event=self._cancel_event())

        self._disable_rename_actions_for_job()
        self._start_job(job, lambda outcome, source=batch: self._on_undo_done(outcome, source))

    def _residual_undo_batch(
        self, source: ExecuteResult, undo_result: ExecuteResult
    ) -> ExecuteResult | None:
        undone = set(undo_result.succeeded)
        remaining = [(old, new) for old, new in source.succeeded if (new, old) not in undone]
        if not remaining:
            return None
        return ExecuteResult(
            succeeded=remaining,
            skipped=[],
            failed=[],
            temps_left=list(undo_result.temps_left),
            copy=source.copy,
        )

    def _on_undo_done(self, result: object, batch: ExecuteResult | None = None) -> None:
        if not isinstance(result, ExecuteResult):
            self._set_summary(str(result))
            self.sync_action_buttons()
            return
        source = batch if batch is not None else self._last_batch
        if source is None:
            self._last_batch = None
        else:
            self._last_batch = self._residual_undo_batch(source, result)
        self._set_summary(self._format_summary(result))
        self.refresh_files()
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
