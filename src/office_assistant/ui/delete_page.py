from __future__ import annotations

import threading
from pathlib import Path

from office_assistant.fs_ops import is_locked
from office_assistant.naming import format_page_ranges, parse_page_ranges, unique_path, unique_path_excluding
from office_assistant.pdf_ops import delete_pages, probe_pdf, render_thumbnail
from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

THUMB_EDGE = 160
PAGE_ROLE = int(Qt.ItemDataRole.UserRole)


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


class _ThumbWorker(QObject):
    ready = Signal(int, bytes)
    finished = Signal()

    def __init__(
        self,
        path: Path,
        indexes: list[int],
        password: str | None,
        cancel_event: threading.Event,
        max_edge: int = THUMB_EDGE,
    ) -> None:
        super().__init__()
        self._path = path
        self._indexes = indexes
        self._password = password
        self._cancel = cancel_event
        self._max_edge = max_edge

    @Slot()
    def run(self) -> None:
        for index in self._indexes:
            if self._cancel.is_set():
                break
            try:
                data = render_thumbnail(
                    self._path,
                    index,
                    max_edge=self._max_edge,
                    password=self._password,
                    cancel_event=self._cancel,
                )
            except Exception:
                data = b""
            if data and not self._cancel.is_set():
                self.ready.emit(index, data)
        self.finished.emit()


class DeletePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selected_pages: set[int] = set()
        self._src: Path | None = None
        self._password: str | None = None
        self._page_count = 0
        self._syncing = False
        self._rendered: set[int] = set()
        self._thumb_gen = 0
        self._thumb_cancel = threading.Event()
        self._thumb_thread: QThread | None = None
        self._thumb_worker: _ThumbWorker | None = None
        self._pending_indexes: list[int] = []
        self._thumbs_paused = False
        self.setAcceptDrops(True)
        self._build_ui()
        self.sync_action_buttons()

    def _build_ui(self) -> None:
        self.open_btn = QPushButton("打开")
        self.open_btn.clicked.connect(self._browse_file)
        self.path_label = QLabel("未打开文件")
        self.path_label.setWordWrap(True)

        top = QHBoxLayout()
        top.addWidget(self.open_btn)
        top.addWidget(self.path_label, 1)

        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText("例如 1,3,5-8")
        self.pages_edit.editingFinished.connect(self._on_pages_edit_finished)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")

        pages_row = QHBoxLayout()
        pages_row.addWidget(QLabel("页码"))
        pages_row.addWidget(self.pages_edit, 1)
        pages_row.addWidget(self.error_label)

        self.select_all_btn = QPushButton("全选")
        self.invert_btn = QPushButton("反选")
        self.select_all_btn.clicked.connect(self._select_all)
        self.invert_btn.clicked.connect(self._invert)

        select_row = QHBoxLayout()
        select_row.addWidget(self.select_all_btn)
        select_row.addWidget(self.invert_btn)
        select_row.addStretch(1)

        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.thumbs.setIconSize(QSize(THUMB_EDGE, THUMB_EDGE))
        self.thumbs.setGridSize(QSize(THUMB_EDGE + 30, THUMB_EDGE + 50))
        self.thumbs.setWordWrap(True)
        self.thumbs.itemChanged.connect(self._on_thumb_changed)
        self.thumbs.verticalScrollBar().valueChanged.connect(lambda _v: self._queue_visible_thumbs())
        self.thumbs.horizontalScrollBar().valueChanged.connect(lambda _v: self._queue_visible_thumbs())

        self.overwrite_check = QCheckBox("覆盖原文件")
        self.overwrite_check.setChecked(False)

        self.save_btn = QPushButton("另存为")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_execute)

        buttons = QHBoxLayout()
        buttons.addWidget(self.overwrite_check)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(pages_row)
        root.addLayout(select_row)
        root.addWidget(self.thumbs, 1)
        root.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._queue_visible_thumbs()

    def _cancel_thumbs(self) -> None:
        self._thumb_gen += 1
        self._thumb_cancel.set()
        self._pending_indexes = []
        thread = self._thumb_thread
        self._thumb_thread = None
        self._thumb_worker = None
        if thread is not None:
            thread.quit()
            thread.wait()

    def _thumbs_blocked(self) -> bool:
        return self._thumbs_paused or self._job_busy()

    def _clear_thumb_thread(self) -> None:
        sender = self.sender()
        if sender is not None and sender is not self._thumb_thread:
            return
        self._thumb_thread = None
        self._thumb_worker = None
        if self._thumbs_blocked():
            self._pending_indexes = []
            return
        if self._pending_indexes:
            pending = self._pending_indexes
            self._pending_indexes = []
            self._start_thumb_worker(pending)

    def _visible_indexes(self) -> list[int]:
        viewport = self.thumbs.viewport().rect()
        visible: list[int] = []
        for index in range(self.thumbs.count()):
            item = self.thumbs.item(index)
            if item is None:
                continue
            if self.thumbs.visualItemRect(item).intersects(viewport):
                visible.append(index)
        return visible

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DeferredDelete:
            self._cancel_thumbs()
        return super().event(event)

    def _queue_visible_thumbs(self) -> None:
        if self._src is None or not self.isVisible() or self._thumbs_blocked():
            return
        pending = [index for index in self._visible_indexes() if index not in self._rendered]
        if not pending:
            return
        thread = self._thumb_thread
        if thread is not None and thread.isRunning():
            self._pending_indexes = pending
            return
        self._start_thumb_worker(pending)

    def _start_thumb_worker(self, indexes: list[int]) -> None:
        if self._src is None or not indexes or not self.isVisible() or self._thumbs_blocked():
            return
        self._thumb_cancel = threading.Event()
        gen = self._thumb_gen
        thread = QThread(self)
        worker = _ThumbWorker(self._src, indexes, self._password, self._thumb_cancel, THUMB_EDGE)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ready.connect(lambda index, data, g=gen: self._on_thumb_ready(g, index, data))
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_thumb_thread)
        self._thumb_thread = thread
        self._thumb_worker = worker
        thread.start()

    def _on_thumb_ready(self, gen: int, index: int, data: bytes) -> None:
        if gen != self._thumb_gen:
            return
        item = self.thumbs.item(index)
        if item is None or not data:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data, "PNG"):
            return
        item.setIcon(QIcon(pixmap))
        self._rendered.add(index)

    def _rebuild_thumbs(self) -> None:
        self._syncing = True
        self.thumbs.clear()
        self._rendered.clear()
        for page in range(1, self._page_count + 1):
            item = QListWidgetItem(str(page))
            item.setData(PAGE_ROLE, page)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            self.thumbs.addItem(item)
        self._syncing = False

    def _apply_selection_to_thumbs(self) -> None:
        self._syncing = True
        for index in range(self.thumbs.count()):
            item = self.thumbs.item(index)
            if item is None:
                continue
            page = index + 1
            wanted = Qt.CheckState.Checked if page in self.selected_pages else Qt.CheckState.Unchecked
            if item.checkState() != wanted:
                item.setCheckState(wanted)
        self._syncing = False

    def _write_pages_edit(self) -> None:
        self._syncing = True
        self.pages_edit.setText(format_page_ranges(self.selected_pages))
        self._syncing = False

    def _on_pages_edit_finished(self) -> None:
        if self._syncing or self._src is None:
            return
        parsed = parse_page_ranges(self.pages_edit.text(), self._page_count)
        if parsed.errors:
            self.error_label.setText("无效：" + ",".join(parsed.errors))
        else:
            self.error_label.setText("")
        self.selected_pages = set(parsed.pages)
        self._apply_selection_to_thumbs()
        self.sync_action_buttons()

    def _on_thumb_changed(self, item: QListWidgetItem) -> None:
        if self._syncing or self._src is None:
            return
        page = item.data(PAGE_ROLE)
        if not isinstance(page, int):
            page = self.thumbs.row(item) + 1
        if item.checkState() == Qt.CheckState.Checked:
            self.selected_pages.add(page)
        else:
            self.selected_pages.discard(page)
        self._write_pages_edit()
        self.error_label.setText("")
        self.sync_action_buttons()

    def _select_all(self) -> None:
        if self._src is None or self._page_count <= 0:
            return
        self.selected_pages = set(range(1, self._page_count + 1))
        self._write_pages_edit()
        self._apply_selection_to_thumbs()
        self.error_label.setText("")
        self.sync_action_buttons()

    def _invert(self) -> None:
        if self._src is None or self._page_count <= 0:
            return
        all_pages = set(range(1, self._page_count + 1))
        self.selected_pages = all_pages - self.selected_pages
        self._write_pages_edit()
        self._apply_selection_to_thumbs()
        self.error_label.setText("")
        self.sync_action_buttons()

    def open_pdf(self, path: Path, password: str | None = None) -> None:
        path = Path(path)
        self._cancel_thumbs()
        info = probe_pdf(path, password)
        if info.needs_password:
            text, ok = QInputDialog.getText(
                self, "密码", f"{path.name} 需要密码", QLineEdit.EchoMode.Password
            )
            if not ok:
                return
            if not text:
                QMessageBox.warning(self, "提示", "需要密码")
                return
            info = probe_pdf(path, text)
            if not info.ok:
                QMessageBox.warning(self, "提示", "密码错误")
                return
            password = text
        if not info.ok:
            QMessageBox.warning(self, "提示", info.error or "无法打开")
            return
        self._src = path
        self._password = password
        self._page_count = info.page_count
        self.selected_pages = set()
        self.path_label.setText(str(path))
        self._rebuild_thumbs()
        self._write_pages_edit()
        self.error_label.setText("")
        self.sync_action_buttons()
        self._queue_visible_thumbs()

    def handle_dropped_paths(self, paths: list[Path]) -> None:
        files = [Path(path) for path in paths if path and Path(path).is_file()]
        if not files:
            return
        if len(files) > 1:
            QMessageBox.warning(self, "提示", "已忽略其余文件，只打开第一个")
        self.open_pdf(files[0])

    def _browse_file(self) -> None:
        start = str(self._src.parent) if self._src is not None else ""
        chosen, _ = QFileDialog.getOpenFileName(self, "打开 PDF", start, "PDF (*.pdf)")
        if chosen:
            self.open_pdf(Path(chosen))

    def _can_execute(self) -> bool:
        if self._src is None or self._job_busy():
            return False
        if not self.selected_pages:
            return False
        if len(self.selected_pages) >= self._page_count:
            return False
        return True

    def _job_busy(self) -> bool:
        window = self.window()
        busy = getattr(window, "job_busy", None)
        if callable(busy):
            return bool(busy())
        return getattr(window, "_thread", None) is not None

    def sync_action_buttons(self) -> None:
        self.save_btn.setEnabled(self._can_execute())

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

    def _confirm_overwrite(self) -> bool:
        answer = QMessageBox.question(self, "确认", "确定覆盖原文件？")
        return answer == QMessageBox.StandardButton.Yes

    def _prepare_overwrite_src(self) -> Path | None:
        src = self._src
        if src is None:
            return None
        if not self._confirm_overwrite():
            return None
        self._thumbs_paused = True
        self._cancel_thumbs()
        if is_locked(src):
            self._thumbs_paused = False
            QMessageBox.warning(self, "提示", "文件被占用，请先关闭后再试")
            return None
        return src

    def _prepare_dest(self) -> Path | None:
        src = self._src
        if src is None:
            return None
        if self.overwrite_check.isChecked():
            dest = src
        else:
            default = src.with_name(f"{src.stem}_删页.pdf")
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                "另存为",
                str(default),
                "PDF (*.pdf)",
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
            if not chosen:
                return None
            dest = Path(chosen)
        if dest.resolve() == src.resolve():
            return self._prepare_overwrite_src()
        if dest.exists():
            dest = ask_existing_dest(self, dest)
            if dest is None:
                return None
        if dest.resolve() == src.resolve():
            dest = unique_path_excluding(dest, [src])
            if dest.resolve() == src.resolve():
                QMessageBox.warning(self, "提示", "输出路径不能与源文件相同，请换一个名字")
                return None
        return dest

    def _on_execute(self) -> None:
        if not self._can_execute():
            return
        dest = self._prepare_dest()
        if dest is None or self._src is None:
            self._thumbs_paused = False
            return
        src = self._src
        pages = set(self.selected_pages)
        password = self._password
        if dest.resolve() == src.resolve():
            self._thumbs_paused = True
            self._cancel_thumbs()

        def job():
            completed = delete_pages(src, dest, pages, password=password, cancel_event=self._cancel_event())
            return dest if completed else None

        self.save_btn.setEnabled(False)
        self._start_job(job, self._on_delete_done)

    def _on_delete_done(self, result: object) -> None:
        self._thumbs_paused = False
        if isinstance(result, Path):
            self._set_summary(f"已保存到 {result.name}")
            if self._src is not None and result.resolve() == self._src.resolve():
                self.open_pdf(self._src, password=self._password)
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
