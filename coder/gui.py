import sys
import json
import base64
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView,
    QGraphicsScene, QGraphicsPathItem,
    QGraphicsTextItem, QFileDialog, QMenuBar,
    QToolBar, QGraphicsItem, QStyle, QMenu,
    QGraphicsRectItem, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QFrame,
    QSplitter,QGridLayout
)
from PySide6.QtGui import (
    QPainterPath, QColor, QFont,
    QFontMetrics, QAction, QPen,
    QBrush, QPainter
)
from PySide6.QtCore import (
    Qt, QPointF, QPropertyAnimation,
    QEasingCurve, QByteArray, QObject,
    Property, QRectF, QAbstractAnimation,
    Signal, QVariantAnimation
)

# ============================================================
# 常量
# ============================================================
GRID_UNIT = 90
PADDING = 8
TEXT_HEIGHT = 36
RADIUS = 10
MAX_LINE_WIDTH = 700
GAP_WIDTH = 4
GAP_HIT_MARGIN = 14

INSPECTOR_WIDTH = 250
INSPECTOR_HEIGHT = 200
INSPECTOR_TITLE = "Inspector"

PANEL_BORDER_STYLE = """
QFrame {
    border: 1px solid #444;
    border-top: none;
    background-color: #1e1e1e;
    padding: 2px;
}
"""

# ============================================================
# 解析函数
# ============================================================
ALLOWED_CONTROL = {0x09, 0x0A}


def is_printable_or_allowed(b):
    return (0x20 <= b <= 0x7E) or b in ALLOWED_CONTROL


def parse_blocks(data):
    blocks = []
    i = 0
    while i < len(data):
        b = data[i]

        if is_printable_or_allowed(b):
            blocks.append(("text", bytes([b])))
            i += 1
            continue

        if b == 0x0D or 0x00 < b < 0x20 or b == 0x7F:
            blocks.append(("hex", bytes([b])))
            i += 1
            continue

        if b < 0x80:
            seq_len = 1
        elif 0xC0 <= b <= 0xDF:
            seq_len = 2
        elif 0xE0 <= b <= 0xEF:
            seq_len = 3
        elif 0xF0 <= b <= 0xF7:
            seq_len = 4
        else:
            seq_len = 1

        chunk = data[i:i + seq_len]
        try:
            chunk.decode("utf-8")
            blocks.append(("text", chunk))
        except UnicodeDecodeError:
            blocks.append(("hex", chunk))

        i += seq_len

    return blocks


# ============================================================
# JSON 读写
# ============================================================
def save_blocks_to_json(blocks, path):
    data = {"version": "1.0", "blocks": []}
    for t, b in blocks:
        data["blocks"].append({
            "type": t,
            "raw_bytes": base64.b64encode(b).decode("utf-8")
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_blocks_from_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    blocks = []
    for item in data["blocks"]:
        raw = base64.b64decode(item["raw_bytes"])
        blocks.append((item["type"], raw))
    return blocks


# ============================================================
# 工具函数
# ============================================================
def create_hex_block(scene, raw=b"\x00", font=None):
    if font is None:
        font = QFont("Consolas", 14)

    block = ByteBlock("hex", raw, font)
    scene.addItem(block)
    block.setZValue(0)
    block.setScale(0.3)
    block.animate_scale(1.0)
    return block


# ============================================================
# GapItem
# ============================================================
class GapItem(QGraphicsRectItem):
    def __init__(self, height=28):
        super().__init__(0, 0, GAP_WIDTH, height)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.left_item = None
        self.right_item = None
        self.setPen(Qt.NoPen)
        self.setBrush(Qt.transparent)
        self._hovered = False

    def shape(self):
        path = QPainterPath()
        m = GAP_HIT_MARGIN
        path.addRect(self.rect().adjusted(-m, -4, m, 4))
        return path

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        opt = option
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, widget)

        if self._hovered:
            painter.setBrush(QColor(180, 180, 180, 80))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())

        if self.isSelected():
            color = QColor(100, 150, 255, 200)
            painter.setPen(QPen(color, 3))
            painter.drawLine(
                int(self.rect().center().x()),
                0,
                int(self.rect().center().x()),
                int(self.rect().height())
            )

    def insert_block(self, scene):
        block = create_hex_block(scene)
        idx = scene.gaps.index(self)
        scene.blocks.insert(idx + 1, block)
        self.setSelected(False)
        scene.relayout()


# ============================================================
# ByteBlock
# ============================================================
class ByteBlock(QObject, QGraphicsPathItem):
    selected = Signal(object)

    def __init__(self, block_type, raw_bytes, font):
        QObject.__init__(self)
        QGraphicsPathItem.__init__(self)

        self.block_type = block_type
        self.raw_bytes = raw_bytes
        self.font = font
        self.metrics = QFontMetrics(font)

        self._scale = 1.0
        self._brush_color = QColor(
            "#3498db" if block_type == "text" else "#e74c3c"
        )

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)

        self._anim_scale = None
        self._anim_color = None
        self._anim_pos = None

        self._update_content(initial=True)

    def get_scale(self):
        return self._scale

    def set_scale(self, s):
        self._scale = s
        self.setScale(s)

    scale = Property(float, get_scale, set_scale)

    def get_brush_color(self):
        return self._brush_color

    def set_brush_color(self, c):
        self._brush_color = c
        self.setBrush(c)

    brushColor = Property(QColor, get_brush_color, set_brush_color)

    def _display_text(self):
        if self.block_type == "text":
            return self.raw_bytes.decode("utf-8", errors="replace")
        return " ".join(f"{b:02X}" for b in self.raw_bytes)

    def _calc_width(self, text):
        w = self.metrics.horizontalAdvance(text)
        units = max(1, (w + PADDING * 2 + GRID_UNIT - 1) // GRID_UNIT)
        return units * GRID_UNIT + (units - 1) * PADDING

    def _update_content(self, initial=False):
        text = self._display_text()
        width = self._calc_width(text)

        rect = QRectF(0.0, 0.0, float(width), float(TEXT_HEIGHT))
        path = QPainterPath()
        path.addRoundedRect(rect, float(RADIUS), float(RADIUS))
        self.setPath(path)

        if not hasattr(self, "text_item"):
            self.text_item = QGraphicsTextItem(self)
            self.text_item.setFont(self.font)
            self.text_item.setDefaultTextColor(Qt.white)
            from PySide6.QtGui import QTextOption
            doc = self.text_item.document()
            option = QTextOption()
            option.setAlignment(Qt.AlignCenter)
            doc.setDefaultTextOption(option)

        self.text_item.setPlainText(text)
        self.text_item.setTextWidth(width)
        self.text_item.setPos(0, 5)
        self.text_item.setAcceptedMouseButtons(Qt.NoButton)
        self.text_item.setAcceptHoverEvents(False)

        if initial:
            self.setBrush(self._brush_color)

        self.setTransformOriginPoint(self.boundingRect().center())

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        opt = option
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, widget)

        if not self.isSelected():
            return

        rect = self.path().boundingRect().adjusted(-2, -2, 2, 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.brush().color().lighter(130))
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

    def hoverEnterEvent(self, event):
        self.animate_scale(1.1)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.animate_scale(1.0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self.selected.emit(self)
        self.animate_scale(0.95)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.animate_scale(1.05)
        super().mouseReleaseEvent(event)

    def safe_start_animation(self, attr_name, anim):
        old = getattr(self, attr_name, None)
        if old and old.state() == QAbstractAnimation.Running:
            old.stop()
        setattr(self, attr_name, anim)
        anim.start()

    def animate_scale(self, target):
        anim = QPropertyAnimation(self, QByteArray(b"scale"))
        anim.setDuration(120)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self.safe_start_animation("_anim_scale", anim)

    def animate_pos(self, target_pos):
        anim = QVariantAnimation(self)
        anim.setDuration(200)
        anim.setStartValue(self.pos())
        anim.setEndValue(target_pos)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self.setPos)
        self.safe_start_animation("_anim_pos", anim)

    def animate_color(self, target_color: QColor):
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setStartValue(self.brush().color())
        anim.setEndValue(target_color)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def update_color(val):
            self.setBrush(val)

        anim.valueChanged.connect(update_color)
        self.safe_start_animation("_anim_color", anim)

    def toggle(self):
        self.block_type = "hex" if self.block_type == "text" else "text"
        self._update_content()
        self.animate_color(
            QColor("#e74c3c" if self.block_type == "hex" else "#3498db")
        )
        self.scene().relayout()

    def append_block(self, scene):
        block = create_hex_block(scene)
        idx = scene.blocks.index(self)
        scene.blocks.insert(idx + 1, block)
        scene.relayout()


# ============================================================
# Scene
# ============================================================
class ByteScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.gaps = []
        self._context_menu = None

    def set_blocks(self, blocks):
        self.clear()
        self.blocks = blocks
        self.gaps.clear()
        prev_gap = None

        for b in blocks:
            self.addItem(b)
            b.setZValue(0)
            gap = GapItem()
            gap.left_item = b
            self.addItem(gap)
            gap.setZValue(1)
            self.gaps.append(gap)
            if prev_gap:
                prev_gap.right_item = b
            prev_gap = gap

        if self.gaps:
            self.gaps[-1].right_item = None

    def is_item_visible(self, item):
        view = self.views()[0]
        return view.mapToScene(
            view.viewport().rect()
        ).boundingRect().intersects(item.sceneBoundingRect())

    def relayout(self):
        x, y = 10, 10
        for idx, item in enumerate(self.blocks):
            target_pos = QPointF(x, y)
            if self.is_item_visible(item):
                item.animate_pos(target_pos)
            else:
                item.setPos(target_pos)

            r = item.path().boundingRect()
            x += r.width()

            if idx < len(self.gaps):
                gap = self.gaps[idx]
                gap.setPos(x, y)
                x += GAP_WIDTH

            if x + r.width() > MAX_LINE_WIDTH:
                x = 10
                y += TEXT_HEIGHT + 6

    def contextMenu(self):
        if not self._context_menu:
            self._context_menu = QMenu()
            toggle_action = self._context_menu.addAction("Switch")
            toggle_action.triggered.connect(self.toggle_selected_blocks)
        return self._context_menu

    def toggle_selected_blocks(self):
        for item in self.selectedItems():
            if isinstance(item, ByteBlock):
                item.toggle()

    def handle_insert(self):
        sel = self.selectedItems()
        if not sel:
            return

        item = sel[0]
        if isinstance(item, GapItem):
            item.insert_block(self)
        elif isinstance(item, ByteBlock):
            item.append_block(self)


# ============================================================
# InspectorPanel
# ============================================================
class InspectorPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(INSPECTOR_WIDTH)
        self.setMinimumHeight(INSPECTOR_HEIGHT)

        layout = QGridLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)

        # ===== HEX MODE =====
        self.hex_label = QLabel("Enter Hex")
        self.hex_label.setStyleSheet("""
            QFrame {
                border: 0px solid #444;
                background-color: #1e1e1e;
            }
        """)
        self.hex1 = QLineEdit()
        self.hex2 = QLineEdit()
        self.hex1.setMaxLength(1)
        self.hex2.setMaxLength(1)
        self.hex1.setFixedWidth(20)
        self.hex2.setFixedWidth(20)

        self.dec_label = QLabel("Enter Dec")
        self.dec_label.setStyleSheet("""
            QFrame {
                border: 0px solid #444;
                background-color: #1e1e1e;
            }
        """)
        self.dec = QLineEdit()
        self.dec.setFixedWidth(65)

        # ===== TEXT MODE =====
        self.text_label = QLabel("Enter Text")
        self.text = QLineEdit()
        self.text_label.setStyleSheet("""
            QFrame {
                border: 0px solid #444;
                background-color: #1e1e1e;
            }
        """)
        self.text.setFixedWidth(140)
        self.text.setFixedHeight(100)   # 多行高度

        # 添加到 grid
        layout.addWidget(self.hex_label)
        layout.addWidget(self.hex1, 0, 1)
        layout.addWidget(self.hex2, 0, 2)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)
        layout.setColumnMinimumWidth(2, 0)

        layout.addWidget(self.dec_label)
        layout.addWidget(self.dec, 1, 1, 1, 2)

        layout.addWidget(self.text_label, 0, 0, Qt.AlignRight)
        layout.addWidget(self.text, 0, 1, 1, 2)

        self.current_block = None

        # signals
        self.hex1.returnPressed.connect(self.apply)
        self.hex2.returnPressed.connect(self.apply)
        self.dec.returnPressed.connect(self.apply)
        self.text.returnPressed.connect(self.apply)

        self._show_hex()

    # ------------------------
    def _show_hex(self):
        self.hex_label.show()
        self.hex1.show()
        self.hex2.show()
        self.dec_label.show()
        self.dec.show()

        self.text_label.hide()
        self.text.hide()

    def _show_text(self):
        self.hex_label.hide()
        self.hex1.hide()
        self.hex2.hide()
        self.dec_label.hide()
        self.dec.hide()

        self.text_label.show()
        self.text.show()

    # ------------------------
    def set_block(self, block: ByteBlock):
        self.current_block = block

        if block.block_type == "hex":
            self._show_hex()
            v = block.raw_bytes[0]
            self.hex1.setText(f"{(v >> 4) & 0xF:X}")
            self.hex2.setText(f"{v & 0xF:X}")
            self.dec.setText(str(v))
        else:
            self._show_text()
            self.text.setText(
                block.raw_bytes.decode("utf-8", errors="replace")
            )

    def apply(self):
        if not self.current_block:
            return

        if self.current_block.block_type == "hex":
            try:
                h = (int(self.hex1.text(), 16) << 4) | int(self.hex2.text(), 16)
                d = int(self.dec.text())
                val = h if abs(h - d) <= 1 else h
            except ValueError:
                return
            self.current_block.raw_bytes = bytes([val])
        else:
            self.current_block.raw_bytes = self.text.text().encode("utf-8")

        self.current_block._update_content()
        self.current_block.scene().relayout()


# ============================================================
# InspectorContainer
# ============================================================
class InspectorContainer(QWidget):
    def __init__(self, title=INSPECTOR_TITLE):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                border: 1px solid #444;
                background-color: #1e1e1e;
            }
        """)

        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_label.setStyleSheet("""
            QLabel {
                padding: 4px 6px;
                background-color: #2a2a2a;
                color: white;
                font-weight: bold;
            }
        """)

        fl.addWidget(title_label)
        fl.addWidget(InspectorPanel())

        layout.addWidget(frame)


        



# ============================================================
# WPanel（与 Inspector 并列）
# ============================================================
class WPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        placeholder = QLabel("WPanel Content")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #888;")

        layout.addWidget(placeholder)


# ============================================================
# WPanelContainer（只包 WPanel）
# ============================================================
class WPanelContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(INSPECTOR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                border: 1px solid #444;
                background-color: #1e1e1e;
            }
        """)

        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        panel_title = QLabel("Panels")
        panel_title.setFixedHeight(22)
        panel_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        panel_title.setStyleSheet("""
            QLabel {
                padding: 2px 8px;
                background-color: #2a2a2a;
                color: #cccccc;
                font-weight: bold;
            }
        """)

        fl.addWidget(panel_title)
        fl.addWidget(WPanel())

        layout.addWidget(frame)


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bytes 块视图")
        self.resize(1100, 600)

        self.current_file = None
        self.scene = ByteScene()

        central = QWidget()
        self.setCentralWidget(central)

        # ---- 左侧 ----
        byte_title = QLabel("Byte Editor")
        byte_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        byte_title.setStyleSheet("""
            QLabel {
                padding: 4px 8px;
                background-color: #2a2a2a;
                color: white;
                font-weight: bold;
                border: 1px solid #444;
                border-bottom: none;
            }
        """)

        self.view = QGraphicsView(self.scene)
        self.view.setMinimumWidth(600)
        self.view.setStyleSheet("border: none;")

        left_content = QFrame()
        left_content.setStyleSheet(PANEL_BORDER_STYLE)

        lcl = QVBoxLayout(left_content)
        lcl.setContentsMargins(0, 0, 0, 0)
        lcl.addWidget(self.view)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(byte_title)
        left_layout.addWidget(left_content)

        left_frame = QWidget()
        left_frame.setLayout(left_layout)

        # ---- 右侧（WPanel + Inspector）----
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(WPanelContainer())
        right_splitter.addWidget(InspectorContainer())
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 0)

        main_layout = QHBoxLayout(central)
        main_layout.addWidget(left_frame, stretch=1)
        main_layout.addWidget(right_splitter)

        self._create_actions()
        self._create_menu_bar()
        self._create_toolbar()

        self.scene.selectionChanged.connect(self.on_selection_changed)

    def _create_actions(self):
        self.open_action = QAction("Open", self)
        self.open_action.triggered.connect(self.open_file)
        self.open_action.setShortcut("Ctrl+O")

        self.save_action = QAction("Save", self)
        self.save_action.triggered.connect(self.save_file)
        self.save_action.setShortcut("Ctrl+S")

        self.save_as_action = QAction("Save As...", self)
        self.save_as_action.triggered.connect(self.save_file_as)
        self.save_as_action.setShortcut("Ctrl+Shift+S")

        self.toggle_action = QAction("Switch", self)
        self.toggle_action.triggered.connect(self.toggle_selected_blocks)
        self.toggle_action.setShortcut("F")

        self.new_block_action = QAction("New Block", self)
        self.new_block_action.triggered.connect(self.handle_new_block)
        self.new_block_action.setShortcut("A")

    def _create_menu_bar(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)

        edit_menu = mb.addMenu("Edit")
        edit_menu.addAction(self.toggle_action)
        edit_menu.addAction(self.new_block_action)

    def _create_toolbar(self):
        self.addToolBar(QToolBar("Main Toolbar"))

    def handle_new_block(self):
        self.scene.handle_insert()

    def toggle_selected_blocks(self):
        self.scene.toggle_selected_blocks()

    def on_selection_changed(self):
        items = self.scene.selectedItems()
        if not items:
            return

        block = items[0]
        if isinstance(block, ByteBlock):
            ic = self.findChild(InspectorContainer)
            if ic:
                ic.findChild(InspectorPanel).set_block(block)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "JSON Files (*.json);;Bytes Files (*.bytes);;All Files (*.*)"
        )
        if not path:
            return

        self.current_file = path
        blocks = load_blocks_from_json(path) if path.endswith(".json") \
            else parse_blocks(open(path, "rb").read())

        self.render_blocks(blocks)

    def save_file(self):
        if not self.current_file:
            self.save_file_as()
            return

        blocks = [(b.block_type, b.raw_bytes) for b in self.scene.blocks]

        if self.current_file.lower().endswith(".json"):
            save_blocks_to_json(blocks, self.current_file)
        else:
            with open(self.current_file, "wb") as f:
                f.write(b"".join(raw for _, raw in blocks))

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", "",
            "Bytes Files (*.bytes);;JSON Files (*.json)"
        )
        if not path:
            return

        if not path.lower().endswith((".json", ".bytes")):
            path += ".bytes"

        self.current_file = path
        self.save_file()

    def render_blocks(self, blocks):
        font = QFont("Consolas", 14)
        x, y = 10, 10
        block_objs = []

        for t, b in blocks:
            block = ByteBlock(t, b, font)
            block.setPos(x, y)
            block_objs.append(block)

            r = block.path().boundingRect()
            x += r.width() + PADDING

            if x + r.width() > MAX_LINE_WIDTH:
                x = 10
                y += TEXT_HEIGHT + 6

        self.scene.set_blocks(block_objs)
        self.scene.relayout()


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())