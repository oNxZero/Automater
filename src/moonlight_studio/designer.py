"""Native widget layout: workspace, action inspector, library and guided setup."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .editor import StepDelegate
from .inspector import ActionInspector
from .theme import ACCENT, icon
from .widgets import button, label
from .workflow import Workflow


def card(title=None, description=None, hero=False):
    frame = QFrame()
    frame.setObjectName("hero" if hero else "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    if title:
        layout.addWidget(label(title, "heading"))
    if description:
        layout.addWidget(label(description))
    return frame, layout


def scrollable(widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(widget)
    return scroll


def segment(text, callback, group):
    btn = button(text, callback, "segment")
    btn.setCheckable(True)
    group.addButton(btn)
    return btn


def build_ui(w):
    app = QWidget()
    app.setObjectName("app")
    w.setCentralWidget(app)
    root = QHBoxLayout(app)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    sidebar = QWidget()
    sidebar.setObjectName("sidebar")
    sidebar.setFixedWidth(202)
    rail = QVBoxLayout(sidebar)
    rail.setContentsMargins(18, 26, 18, 20)
    rail.setSpacing(7)
    branding = QHBoxLayout()
    moon = label("")
    moon.setPixmap(icon("moon", ACCENT, 31).pixmap(31, 31))
    branding.addWidget(moon)
    branding.addWidget(label("Moonlight", "brand"))
    rail.addLayout(branding)
    subtitle = label("STUDIO  /  AUTOMATION", "eyebrow")
    subtitle.setContentsMargins(5, 3, 0, 26)
    rail.addWidget(subtitle)
    rail.addWidget(label("WORKSPACE", "eyebrow"))
    w.nav_group = QButtonGroup(w)
    w.nav_buttons = []
    for text, glyph, page, view in (
        ("Workflow", "flow", 0, 0),
        ("Events", "list", 0, 1),
        ("Library", "library", 1, 0),
        ("Setup", "settings", 2, 0),
    ):
        nav = button(
            text, lambda checked=False, p=page, v=view: w.navigate(p, v), "nav", glyph=glyph
        )
        nav.setCheckable(True)
        w.nav_group.addButton(nav)
        w.nav_buttons.append(nav)
        rail.addWidget(nav)
    rail.addSpacing(24)
    rail.addWidget(label("QUICK START", "eyebrow"))
    w.new_btn = button("New workflow", w.new_script, "ghost", "Ctrl+N", "plus")
    w.open_btn = button("Import script", w.open_script, "ghost", "Ctrl+O", "open")
    rail.addWidget(w.new_btn)
    rail.addWidget(w.open_btn)
    rail.addWidget(button("Explore example", w.load_example, "ghost", glyph="spark"))
    rail.addStretch()
    rail.addWidget(label("YOUR SHORTCUTS", "eyebrow"))
    for text, key in (("Record / finish", "F6"), ("Play / stop", "F7"), ("Pause / resume", "F8")):
        row = QHBoxLayout()
        row.addWidget(label(text))
        row.addStretch()
        row.addWidget(label(key, "badge"))
        rail.addLayout(row)
    rail.addSpacing(22)
    w.device_badge = button("Check input access", lambda: w.navigate(2), "ghost", glyph="info")
    rail.addWidget(w.device_badge)
    rail.addWidget(label("Moonlight Studio  ·  Linux", "muted"))
    root.addWidget(sidebar)

    content = QWidget()
    body = QVBoxLayout(content)
    body.setContentsMargins(26, 24, 26, 16)
    body.setSpacing(16)
    breadcrumb = QHBoxLayout()
    breadcrumb.addWidget(label("YOUR WORKSPACE", "eyebrow"))
    breadcrumb.addStretch()
    w.saved_badge = label("Saved", "badge")
    breadcrumb.addWidget(w.saved_badge)
    w.save_as_btn = button("Save as", w.save_as, "ghost", "Ctrl+Shift+S")
    w.save_btn = button("Save workflow", w.save_script, "", "Ctrl+S", "save")
    breadcrumb.addWidget(w.save_as_btn)
    breadcrumb.addWidget(w.save_btn)
    body.addLayout(breadcrumb)
    title_row = QHBoxLayout()
    titles = QVBoxLayout()
    titles.setSpacing(5)
    w.name = QLineEdit()
    w.name.setMaxLength(120)
    w.name.setObjectName("scriptTitle")
    w.name.setAccessibleName("Workflow name")
    w.name.setPlaceholderText("Name your workflow")
    titles.addWidget(w.name)
    w.stats = label("Record a routine. Shape it into a workflow.")
    titles.addWidget(w.stats)
    title_row.addLayout(titles, 1)
    w.settings_btn = button("Run settings", lambda: w.show_inspector(1), "ghost", glyph="settings")
    title_row.addWidget(w.settings_btn)
    body.addLayout(title_row)
    # Status guidance is compact, actionable and separate from the canvas.
    notice_card = QFrame()
    notice_card.setObjectName("notice")
    notice = QHBoxLayout(notice_card)
    notice.setContentsMargins(13, 8, 8, 8)
    w.notice = label("", "body")
    notice.addWidget(w.notice, 1)
    w.setup_link = button("Open setup", lambda: w.navigate(2), "ghost", glyph="right")
    notice.addWidget(w.setup_link)
    body.addWidget(notice_card)
    w.pages = QStackedWidget()
    body.addWidget(w.pages, 1)

    workspace = QWidget()
    workspace_layout = QVBoxLayout(workspace)
    workspace_layout.setContentsMargins(0, 0, 0, 0)
    workspace_layout.setSpacing(12)
    toolbar = QHBoxLayout()
    w.view_segments = QFrame()
    w.view_segments.setObjectName("segments")
    segments = QHBoxLayout(w.view_segments)
    segments.setContentsMargins(4, 4, 4, 4)
    segments.setSpacing(2)
    w.view_group = QButtonGroup(w)
    w.flow_btn = segment("Workflow", lambda: w.navigate(0, 0), w.view_group)
    w.flow_btn.setIcon(icon("flow"))
    w.events_btn = segment("Events", lambda: w.navigate(0, 1), w.view_group)
    w.events_btn.setIcon(icon("list"))
    segments.addWidget(w.flow_btn)
    segments.addWidget(w.events_btn)
    toolbar.addWidget(w.view_segments)
    w.undo_btn = button("", w.undo.undo, "ghost", "Undo · Ctrl+Z", "undo")
    w.redo_btn = button("", w.undo.redo, "ghost", "Redo · Ctrl+Shift+Z", "redo")
    w.undo_btn.setEnabled(False)
    w.redo_btn.setEnabled(False)
    w.undo.canUndoChanged.connect(w.update_undo_actions)
    w.undo.canRedoChanged.connect(w.update_undo_actions)
    toolbar.addWidget(w.undo_btn)
    toolbar.addWidget(w.redo_btn)
    toolbar.addStretch()
    w.add_btn = button("Add action", w.choose_action, "primary", glyph="plus")
    toolbar.addWidget(w.add_btn)
    workspace_layout.addLayout(toolbar)
    split = QSplitter(Qt.Horizontal)
    workspace_layout.addWidget(split, 1)
    editor = QFrame()
    editor.setObjectName("card")
    edit_layout = QVBoxLayout(editor)
    edit_layout.setContentsMargins(1, 1, 1, 1)
    edit_layout.setSpacing(0)
    w.editor_stack = QStackedWidget()
    w.workflow = Workflow()
    w.workflow.canvas.selected.connect(w.select_block)
    w.workflow.canvas.insertRequested.connect(w.choose_action)
    w.workflow.canvas.reorderRequested.connect(w.reorder_blocks)
    w.workflow.canvas.command.connect(w.workflow_command)
    w.editor_stack.addWidget(w.workflow)
    events = QWidget()
    events_layout = QVBoxLayout(events)
    events_layout.setContentsMargins(12, 10, 12, 10)
    events_layout.addWidget(label("EVENT EDITOR", "eyebrow"))
    events_layout.addWidget(
        label("Every original input, with its exact delay. Double-click a cell to edit.")
    )
    w.table = QTableView()
    w.table.setAccessibleName("Script event editor")
    w.table.setModel(w.model)
    w.table.setItemDelegate(StepDelegate(w.table))
    w.table.setAlternatingRowColors(True)
    w.table.setShowGrid(False)
    w.table.setSelectionBehavior(QAbstractItemView.SelectRows)
    w.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    w.table.verticalHeader().setDefaultSectionSize(40)
    w.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    for col, width in enumerate((42, 105, 110, 145, 105, 105)):
        w.table.setColumnWidth(col, width)
    w.table.horizontalHeader().setStretchLastSection(True)
    w.table.selectionModel().selectionChanged.connect(w.table_selection_changed)
    events_layout.addWidget(w.table, 1)
    event_tools = QHBoxLayout()
    for text, callback, glyph in (
        ("Duplicate", w.duplicate, "copy"),
        ("Delete", w.delete, "trash"),
        ("Move up", lambda: w.move(-1), "left"),
        ("Move down", lambda: w.move(1), "right"),
    ):
        event_tools.addWidget(button(text, callback, "ghost", glyph=glyph))
    event_tools.addStretch()
    events_layout.addLayout(event_tools)
    w.editor_stack.addWidget(events)
    w.welcome = QWidget()
    welcome = QVBoxLayout(w.welcome)
    welcome.setContentsMargins(50, 35, 50, 35)
    welcome.addStretch()
    emblem = label("")
    emblem.setAlignment(Qt.AlignCenter)
    emblem.setPixmap(icon("flow", ACCENT, 58).pixmap(58, 58))
    welcome.addWidget(emblem)
    heading = label("Your next routine, on autopilot.", "title")
    heading.setAlignment(Qt.AlignCenter)
    welcome.addWidget(heading)
    description = label(
        "Record what you do, or build it one action at a time.\nYour workflow will appear here, from left to right."
    )
    description.setAlignment(Qt.AlignCenter)
    welcome.addWidget(description)
    start = QHBoxLayout()
    start.addStretch()
    w.empty_record = button("Record a routine", w.toggle_record, "primary", glyph="record")
    start.addWidget(w.empty_record)
    start.addWidget(button("Add first action", w.choose_action, glyph="plus"))
    start.addStretch()
    welcome.addLayout(start)
    example = button("Or explore the example workflow →", w.load_example, "ghost")
    welcome.addWidget(example, 0, Qt.AlignCenter)
    welcome.addStretch()
    w.editor_stack.addWidget(w.welcome)
    edit_layout.addWidget(w.editor_stack)
    split.addWidget(editor)
    inspector = QFrame()
    w.inspector_panel = inspector
    inspector.setObjectName("inspector")
    inspector.setMinimumWidth(272)
    inspector.setMaximumWidth(330)
    ins_layout = QVBoxLayout(inspector)
    ins_layout.setContentsMargins(18, 16, 18, 16)
    ins_layout.setSpacing(18)
    tabs = QHBoxLayout()
    w.inspector_group = QButtonGroup(w)
    w.inspector_buttons = []
    for i, name in enumerate(("Action", "Run", "Notes")):
        tab = segment(name, lambda checked=False, p=i: w.show_inspector(p), w.inspector_group)
        tabs.addWidget(tab)
        w.inspector_buttons.append(tab)
    ins_layout.addLayout(tabs)
    w.inspector_stack = QStackedWidget()
    w.action_inspector = ActionInspector()
    w.action_inspector.applied.connect(w.apply_block)
    w.action_inspector.command.connect(w.workflow_command)
    w.inspector_stack.addWidget(w.action_inspector)
    w.inspector_stack.addWidget(build_run_settings(w))
    notes_page = QWidget()
    notes = QVBoxLayout(notes_page)
    notes.setContentsMargins(0, 0, 0, 0)
    notes.addWidget(label("WORKFLOW NOTES", "eyebrow"))
    notes.addWidget(label("Remember the starting point", "heading"))
    notes.addWidget(
        label("Add game bindings, camera position, or anything to check before replay.")
    )
    w.notes = QTextEdit()
    w.notes.setPlaceholderText("e.g. Start at the north gate, facing the stairs…")
    w.notes.setAccessibleName("Script notes")
    notes.addWidget(w.notes, 1)
    w.inspector_stack.addWidget(notes_page)
    ins_layout.addWidget(w.inspector_stack, 1)
    split.addWidget(inspector)
    split.setSizes([850, 290])
    w.edit_workspace = split
    w.pages.addWidget(workspace)
    w.pages.addWidget(build_library(w))
    w.pages.addWidget(build_setup(w))

    transport, controls = card()
    transport.setObjectName("transport")
    controls.setContentsMargins(16, 13, 16, 13)
    row = QHBoxLayout()
    w.run_state = label("●  READY", "badge")
    row.addWidget(w.run_state)
    w.transport_hint = label("Ready when you are")
    row.addWidget(w.transport_hint, 1)
    w.record_btn = button("Record  ·  F6", w.toggle_record, "record", glyph="record")
    w.record_btn.setToolTip(
        "Record a routine after the countdown. Replaces the current actions; Undo restores them."
    )
    w.play_btn = button("Run workflow  ·  F7", w.toggle_play, "primary", glyph="play")
    w.pause_btn = button("Pause", w.pause, "ghost", "Pause / resume · F8", "pause")
    w.stop_btn = button("Stop  ·  F12", w.stop, "stop", glyph="stop")
    for widget in (w.record_btn, w.play_btn, w.pause_btn, w.stop_btn):
        row.addWidget(widget)
    controls.addLayout(row)
    w.progress = QProgressBar()
    w.progress.setRange(0, 1000)
    w.progress.setValue(0)
    w.progress.setTextVisible(False)
    controls.addWidget(w.progress)
    body.addWidget(transport)
    w.status = label("Ready", "status")
    w.status.setMinimumHeight(19)
    body.addWidget(w.status)
    root.addWidget(content, 1)
    w.update_busy(False)
    w.navigate(0, 0)
    w.show_inspector(0)


def build_run_settings(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    layout.addWidget(label("PLAYBACK", "eyebrow"))
    layout.addWidget(label("Make it run your way", "heading"))
    w.test_mode = QCheckBox("Test mode")
    w.test_mode.setToolTip("Runs the real scheduler and highlights actions without emitting input")
    w.test_mode.toggled.connect(w.update_run_summary)
    layout.addWidget(w.test_mode)
    layout.addWidget(label("Preview without sending any input."))
    layout.addWidget(label("Destination"))
    w.mode = QComboBox()
    w.mode.addItems(["Active desktop", "Background window · X11"])
    w.mode.currentIndexChanged.connect(w.routing_changed)
    layout.addWidget(w.mode)
    w.target = QComboBox()
    w.target.setAccessibleName("Target program window")
    w.target.setMinimumContentsLength(12)
    w.target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    layout.addWidget(w.target)
    w.refresh_target_btn = button("Refresh windows", w.refresh_windows, "ghost", glyph="refresh")
    layout.addWidget(w.refresh_target_btn)
    w.routing_hint = label("")
    layout.addWidget(w.routing_hint)
    form = QFormLayout()
    form.setSpacing(12)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    w.speed = QDoubleSpinBox()
    w.speed.setRange(0.1, 10)
    w.speed.setSingleStep(0.1)
    w.speed.setValue(1)
    w.speed.setSuffix(" ×")
    w.repeats = QSpinBox()
    w.repeats.setRange(0, 100_000)
    w.repeats.setValue(1)
    w.repeats.setSpecialValueText("Until stopped")
    w.countdown = QSpinBox()
    w.countdown.setRange(0, 30)
    w.countdown.setValue(3)
    w.countdown.setSuffix(" s")
    w.gap = QDoubleSpinBox()
    w.gap.setRange(0, 3600)
    w.gap.setValue(0.25)
    w.gap.setSuffix(" s")
    for text, widget in (
        ("Speed", w.speed),
        ("Repeat", w.repeats),
        ("Start delay", w.countdown),
        ("Loop gap", w.gap),
    ):
        widget.setMinimumWidth(80)
        widget.valueChanged.connect(w.update_run_summary)
        form.addRow(text, widget)
    layout.addLayout(form)
    w.run_estimate = label("")
    layout.addWidget(w.run_estimate)
    layout.addStretch()
    return scrollable(page)


def build_library(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    heading, top = card(
        "Your routines, all in one place.",
        "Save a workflow once. Come back to it whenever you need it.",
        True,
    )
    actions = QHBoxLayout()
    actions.addWidget(button("New workflow", w.new_script, "primary", glyph="plus"))
    actions.addWidget(button("Import JSON", w.open_script, glyph="open"))
    actions.addStretch()
    actions.addWidget(button("Refresh", w.refresh_library, "ghost", glyph="refresh"))
    top.addLayout(actions)
    layout.addWidget(heading)
    w.library_search = QLineEdit()
    w.library_search.setPlaceholderText("Search your workflows…")
    w.library_search.addAction(icon("search"), QLineEdit.LeadingPosition)
    w.library_search.textChanged.connect(w.filter_library)
    layout.addWidget(w.library_search)
    w.library_empty = label("No saved workflows yet. Use Save workflow to add your first one.")
    layout.addWidget(w.library_empty)
    w.library = QListWidget()
    w.library.setAccessibleName("Saved workflows. Double click to open.")
    w.library.itemDoubleClicked.connect(w.open_library)
    layout.addWidget(w.library, 1)
    return page


def build_setup(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    # Reuse the existing diagnostic controls, now in a dedicated, spacious page.
    hero, intro = card(
        "A little setup. A lot less repetition.",
        "Connect your inputs once, then record and run from anywhere on your desktop.",
        True,
    )
    layout.addWidget(hero)
    columns = QHBoxLayout()
    device_card, device = card(
        "01  Choose your devices", "Select the keyboard and mouse you want to record."
    )
    w.health = label("")
    device.addWidget(w.health)
    w.device_list = QListWidget()
    w.device_list.setMinimumHeight(130)
    w.device_list.setAccessibleName("Physical input devices to monitor")
    device.addWidget(w.device_list, 1)
    device.addWidget(button("Apply / refresh devices", w.refresh_devices, glyph="refresh"))
    device.addWidget(button("Permissions & help", w.show_help, "ghost", glyph="info"))
    columns.addWidget(device_card, 1)
    capture_card, capture = card(
        "02  Choose what to capture", "Keep the inputs you need. Leave the rest out."
    )
    w.capture_keys = QCheckBox("Keyboard presses and releases")
    w.capture_buttons = QCheckBox("Mouse buttons and scrolling")
    w.capture_motion = QCheckBox("Mouse movement")
    for widget in (w.capture_keys, w.capture_buttons, w.capture_motion):
        widget.setChecked(True)
        capture.addWidget(widget)
    capture.addSpacing(15)
    capture.addWidget(label("03  Record your routine", "heading"))
    capture.addWidget(
        label(
            "Press F6, switch to your game during the countdown, and do your routine. Press F6 again to finish."
        )
    )
    capture.addWidget(
        label("A new recording replaces the current actions. Undo brings the previous ones back.")
    )
    capture.addWidget(button("Back to workflow", lambda: w.navigate(0, 0), "primary", glyph="flow"))
    capture.addStretch()
    columns.addWidget(capture_card, 1)
    layout.addLayout(columns, 1)
    layout.addWidget(
        label(
            "Keyboard shortcuts need a selected, readable physical keyboard. F12 stops any active run."
        )
    )
    return scrollable(page)
