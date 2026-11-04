"""Native widget layout: workspace, action inspector, library and guided setup."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .editor import EventTable, StepDelegate
from .group_inspector import GroupNotesInspector
from .inspector import ActionInspector
from .live_preview import RecordingPreview
from .theme import ACCENT, icon
from .widgets import ElidedLabel, WindowTargetButton, WorkflowTabBar, button, label
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
    body = QVBoxLayout(app)
    body.setContentsMargins(24, 18, 24, 18)
    body.setSpacing(14)
    top = QHBoxLayout()
    brand_icon = label("")
    brand_icon.setProperty("themeGlyph", "automation")
    brand_icon.setProperty("themeSize", 24)
    brand_icon.setPixmap(icon("automation", ACCENT, 24).pixmap(24, 24))
    top.addWidget(brand_icon)
    top.addWidget(label("Automater", "brand"))
    top.addSpacing(24)
    w.nav_group = QButtonGroup(w)
    w.nav_buttons = []
    for text, glyph, page, view in (
        ("Workflow", "flow", 0, 0),
        ("Events", "list", 0, 1),
        ("Library", "library", 1, 0),
        ("Devices", "settings", 2, 0),
    ):
        nav = button(
            text, lambda checked=False, p=page, v=view: w.navigate(p, v), "segment", glyph=glyph
        )
        nav.setCheckable(True)
        w.nav_group.addButton(nav)
        w.nav_buttons.append(nav)
        top.addWidget(nav)
    w.flow_btn, w.events_btn = w.nav_buttons[:2]
    w.device_badge = w.nav_buttons[3]
    top.addStretch()
    menu = QMenu(w)
    w.new_btn = menu.addAction("New workflow\tCtrl+N", w.new_script)
    w.open_btn = menu.addAction("Open…\tCtrl+O", w.open_script)
    w.save_as_btn = menu.addAction("Save as…\tCtrl+Shift+S", w.save_as)
    menu.addSeparator()
    menu.addAction("Load example", w.load_example)
    menu.addAction("Input controls example", w.load_controls_example)
    menu.addSeparator()
    menu.addAction("Appearance & themes…\tCtrl+,", w.show_appearance)
    menu.addAction("Getting started…", w.show_getting_started)
    menu.addAction("Linux compatibility…", w.show_compatibility)
    file_btn = QPushButton("File")
    file_btn.setObjectName("ghost")
    file_btn.setMenu(menu)
    top.addWidget(file_btn)
    edit_menu = QMenu(w)
    for title, command in (
        ("Undo\tCtrl+Z", "undo"),
        ("Redo\tCtrl+Shift+Z", "redo"),
        ("Copy\tCtrl+C", "copy"),
        ("Cut\tCtrl+X", "cut"),
        ("Paste\tCtrl+V", "paste"),
        ("Duplicate\tCtrl+D", "duplicate"),
        ("Select all\tCtrl+A", "select_all"),
        ("Delete\tDelete", "delete"),
        ("Notes for selected group…\tCtrl+Shift+N", "group_notes"),
        ("Group selection…\tCtrl+G", "group"),
        ("Ungroup selection\tCtrl+Shift+G", "ungroup"),
        ("Randomize selected timing…", "randomize"),
        ("Re-record selected actions…", "rerecord"),
        ("Show pointer path…", "preview_pointer"),
        ("Last playback details", "run_details"),
        ("Clear run highlights", "clear_run"),
        ("Keyboard shortcuts\tF1", "help"),
    ):
        action = edit_menu.addAction(title)
        action.triggered.connect(lambda checked=False, c=command: w.workflow_command(c))
    edit_btn = QPushButton("Edit")
    edit_btn.setObjectName("ghost")
    edit_btn.setMenu(edit_menu)
    top.addWidget(edit_btn)
    w.save_btn = button("Save", w.save_script, "", "Save workflow · Ctrl+S", "save")
    top.addWidget(w.save_btn)
    body.addLayout(top)
    w.workflow_tabs = QWidget()
    tabs = QHBoxLayout(w.workflow_tabs)
    tabs.setContentsMargins(0, 0, 0, 0)
    w.document_tabs = WorkflowTabBar()
    w.document_tabs.setTabsClosable(True)
    w.document_tabs.setMovable(True)
    w.document_tabs.setExpanding(False)
    w.document_tabs.setDrawBase(False)
    w.document_tabs.setElideMode(Qt.ElideRight)
    w.document_tabs.setUsesScrollButtons(True)
    w.document_tabs.setAccessibleName("Open workflows")
    w.document_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
    w.document_tabs.customContextMenuRequested.connect(w.document_menu)
    w.document_tabs.tabBarDoubleClicked.connect(w.rename_document)
    w.document_tabs.currentChanged.connect(w.activate_document)
    w.document_tabs.tabCloseRequested.connect(w.close_document)
    tabs.addWidget(w.document_tabs)
    w.new_tab_btn = button("+", w.new_script, "ghost", "New workflow tab · Ctrl+T")
    w.new_tab_btn.setFixedSize(36, 36)
    w.new_tab_btn.setAccessibleName("New workflow tab · Ctrl+T")
    w.new_tab_btn.setStyleSheet("font-size: 22px; padding: 0;")
    tabs.addWidget(w.new_tab_btn)
    tabs.addStretch(1)
    w.workspace_header = QWidget()
    w.title_row = QHBoxLayout(w.workspace_header)
    w.title_row.setContentsMargins(0, 8, 0, 4)
    titles = QVBoxLayout()
    titles.setSpacing(4)
    name_row = QHBoxLayout()
    w.name = QLineEdit()
    w.name.setMaxLength(120)
    w.name.setObjectName("scriptTitle")
    w.name.setAccessibleName("Workflow name")
    w.name.setPlaceholderText("Name your workflow")
    name_row.addWidget(w.name, 1)
    w.saved_badge = label("Unsaved", "muted")
    w.saved_badge.setObjectName("saveState")
    w.saved_badge.setWordWrap(False)
    titles.addLayout(name_row)
    w.stats = ElidedLabel()
    w.stats.setObjectName("muted")
    details = QHBoxLayout()
    details.setSpacing(10)
    details.addWidget(w.stats)
    details.addWidget(w.saved_badge)
    details.addStretch()
    titles.addLayout(details)
    w.title_row.addLayout(titles, 1)
    w.settings_btn = button("Settings", lambda: w.show_inspector(1), "ghost", glyph="settings")
    body.addWidget(w.workspace_header)
    w.preview_banner = QFrame()
    preview = QHBoxLayout(w.preview_banner)
    preview.setContentsMargins(8, 0, 8, 0)
    preview.addWidget(
        label("Test mode · workflow preview only. Your mouse and keyboard will not move."), 1
    )
    w.real_inputs_btn = button(
        "Use real inputs", lambda: w.test_mode.setChecked(False), "ghost", glyph="play"
    )
    preview.addWidget(w.real_inputs_btn)
    w.preview_banner.hide()
    body.addWidget(w.preview_banner)
    w.countdown_banner = QFrame()
    w.countdown_banner.setObjectName("hero")
    countdown = QHBoxLayout(w.countdown_banner)
    countdown.setContentsMargins(22, 12, 18, 12)
    w.countdown_number = label("3", "title")
    w.countdown_number.setMinimumWidth(50)
    countdown.addWidget(w.countdown_number)
    w.countdown_message = label("Switch to your target window", "body")
    countdown.addWidget(w.countdown_message, 1)
    w.countdown_progress = QProgressBar()
    w.countdown_progress.setRange(0, 1000)
    w.countdown_progress.setTextVisible(False)
    countdown.addWidget(w.countdown_progress, 1)
    countdown.addWidget(button("Cancel · F12", w.stop, "ghost", glyph="stop"))
    w.countdown_banner.hide()
    body.addWidget(w.countdown_banner)
    w.pages = QStackedWidget()
    body.addWidget(w.pages, 1)

    workspace = QWidget()
    workspace_layout = QVBoxLayout(workspace)
    workspace_layout.setContentsMargins(0, 0, 0, 0)
    workspace_layout.setSpacing(12)
    workspace_layout.addWidget(w.workflow_tabs)
    w.record_preview = RecordingPreview()
    workspace_layout.addWidget(w.record_preview)
    toolbar = w.title_row
    w.undo_btn = button("", lambda: w.workflow_command("undo"), "ghost", "Undo · Ctrl+Z", "undo")
    w.redo_btn = button(
        "", lambda: w.workflow_command("redo"), "ghost", "Redo · Ctrl+Shift+Z", "redo"
    )
    w.undo_btn.setEnabled(False)
    w.redo_btn.setEnabled(False)
    w.undo.canUndoChanged.connect(w.update_undo_actions)
    w.undo.canRedoChanged.connect(w.update_undo_actions)
    toolbar.addWidget(w.undo_btn)
    toolbar.addWidget(w.redo_btn)
    toolbar.addStretch()
    w.add_btn = button("Add action", w.choose_action, "primary", glyph="plus")
    toolbar.addWidget(w.add_btn)
    toolbar.addWidget(w.settings_btn)
    split = QSplitter(Qt.Horizontal)
    workspace_layout.addWidget(split, 1)
    editor = QFrame()
    editor.setObjectName("card")
    edit_layout = QVBoxLayout(editor)
    edit_layout.setContentsMargins(1, 1, 1, 1)
    edit_layout.setSpacing(0)
    w.editor_stack = QStackedWidget()
    w.workflow = Workflow()
    w.workflow.canvas.selected.connect(w.select_blocks)
    w.workflow.canvas.insertRequested.connect(w.choose_action)
    w.workflow.canvas.reorderRequested.connect(w.reorder_blocks)
    w.workflow.canvas.command.connect(w.workflow_command)
    w.workflow.canvas.groupRequested.connect(w.handle_group_command)
    w.workflow.layout_choice.currentIndexChanged.connect(w.save_preferences)
    w.editor_stack.addWidget(w.workflow)
    events = QWidget()
    events_layout = QVBoxLayout(events)
    events_layout.setContentsMargins(12, 10, 12, 10)
    events_layout.addWidget(label("EVENT EDITOR", "eyebrow"))
    events_layout.addWidget(
        label("Every original input, with its exact delay. Double-click a cell to edit.")
    )
    w.table = EventTable()
    w.table.command.connect(w.workflow_command)
    w.table.setAccessibleName("Script event editor")
    w.table.setModel(w.model)
    w.table.setItemDelegate(StepDelegate(w.table))
    w.table.setAlternatingRowColors(True)
    w.table.setShowGrid(False)
    w.table.setSelectionBehavior(QAbstractItemView.SelectRows)
    w.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    w.table.verticalHeader().setDefaultSectionSize(40)
    w.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    for col, width in enumerate((42, 105, 110, 165, 90, 90, 115)):
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
    emblem.setProperty("themeGlyph", "flow")
    emblem.setProperty("themeSize", 58)
    emblem.setAlignment(Qt.AlignCenter)
    emblem.setPixmap(icon("flow", ACCENT, 58).pixmap(58, 58))
    welcome.addWidget(emblem)
    heading = w.welcome_heading = label("Create your first workflow", "title")
    heading.setAlignment(Qt.AlignCenter)
    welcome.addWidget(heading)
    description = w.welcome_description = label("Click Record below, or Add action above.")
    description.setAlignment(Qt.AlignCenter)
    welcome.addWidget(description)
    example = w.welcome_example = button("Try an example", w.load_example, "ghost")
    welcome.addWidget(example, 0, Qt.AlignCenter)
    welcome.addWidget(
        button("Quick guide", w.show_getting_started, "ghost", glyph="info"), 0, Qt.AlignCenter
    )
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
    tabs.setSpacing(3)
    w.inspector_group = QButtonGroup(w)
    w.inspector_buttons = []
    for i, name in enumerate(("Action", "Run", "Start", "Group")):
        tab = segment(name, lambda checked=False, p=i: w.show_inspector(p), w.inspector_group)
        tab.setStyleSheet("padding: 6px 5px; font-size: 12px;")
        tabs.addWidget(tab)
        w.inspector_buttons.append(tab)
    tabs.addWidget(button("", w.hide_inspector, "ghost", "Close properties", "close"))
    ins_layout.addLayout(tabs)
    w.inspector_stack = QStackedWidget()
    w.action_inspector = ActionInspector()
    w.action_inspector.applied.connect(w.apply_block)
    w.action_inspector.command.connect(w.workflow_command)
    w.inspector_stack.addWidget(w.action_inspector)
    w.inspector_stack.addWidget(build_run_settings(w))
    w.inspector_stack.addWidget(build_start_settings(w))
    w.group_inspector = GroupNotesInspector()
    w.group_inspector.applied.connect(w.save_group_notes)
    w.group_inspector.command.connect(w.handle_group_command)
    w.group_inspector.draftChanged.connect(
        lambda: (w.saved_badge.show(), w.update_document_title(True))
    )
    w.notes = w.group_inspector.imported_notes
    w.inspector_stack.addWidget(scrollable(w.group_inspector))
    ins_layout.addWidget(w.inspector_stack, 1)
    split.addWidget(inspector)
    split.setSizes([850, 290])
    w.edit_workspace = split
    w.pages.addWidget(workspace)
    w.pages.addWidget(build_library(w))
    w.pages.addWidget(build_setup(w))

    transport = QFrame()
    transport.setObjectName("transport")
    controls = QVBoxLayout(transport)
    controls.setContentsMargins(14, 10, 14, 10)
    controls.setSpacing(6)
    row = QHBoxLayout()
    w.record_btn = button(
        "Record · F6", w.toggle_record, "record", "Record / finish · F6", "record"
    )
    w.play_btn = button("Run · F7", w.toggle_play, "primary", "Run / stop · F7", "play")
    w.pause_btn = button("Pause · F8", w.pause, "ghost", "Pause / resume · F8", "pause")
    w.stop_btn = button("Stop · F12", w.stop, "stop", "Emergency stop · F12", "stop")
    for widget in (w.record_btn, w.play_btn, w.pause_btn, w.stop_btn):
        row.addWidget(widget)
    w.cancel_capture_btn = button(
        "Discard",
        lambda: w.stop(discard_recording=True),
        "ghost",
        "Discard this recording and keep existing actions",
        "undo",
    )
    w.cancel_capture_btn.hide()
    row.addWidget(w.cancel_capture_btn)
    w.run_state = label("", "muted")
    row.addWidget(w.run_state)
    w.status = label("Ready", "status")
    w.status.setMinimumWidth(100)
    row.addWidget(w.status, 1)
    w.transport_hint = label("")
    w.transport_hint.setWordWrap(False)
    row.addWidget(w.transport_hint)
    controls.addLayout(row)
    w.progress = QProgressBar()
    w.progress.setRange(0, 1000)
    w.progress.setTextVisible(False)
    controls.addWidget(w.progress)
    body.addWidget(transport)
    w.update_busy(False)
    w.navigate(0, 0)
    w.inspector_panel.hide()


def build_run_settings(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    layout.addWidget(label("Run settings", "heading"))
    layout.addWidget(button("Appearance & themes…", w.show_appearance, "ghost", glyph="spark"))
    w.test_mode = QCheckBox("Test mode")
    w.test_mode.setToolTip("Runs the real scheduler and highlights actions without emitting input")
    w.test_mode.toggled.connect(w.update_run_summary)
    layout.addWidget(w.test_mode)
    layout.addWidget(label("Preview without sending any input."))
    layout.addWidget(label("Destination"))
    w.mode = QComboBox()
    w.mode.setMinimumContentsLength(12)
    w.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    w.mode.addItems(
        ["Active desktop", "Background window · X11", "Separate game session · Gamescope"]
    )
    w.mode.currentIndexChanged.connect(w.routing_changed)
    layout.addWidget(w.mode)
    w.target = QComboBox()
    w.target.setAccessibleName("Target program window")
    w.target.setMinimumContentsLength(12)
    w.target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    w.target.currentIndexChanged.connect(w.update_run_summary)
    layout.addWidget(w.target)
    w.refresh_target_btn = WindowTargetButton(w.choose_open_window)
    layout.addWidget(w.refresh_target_btn)
    w.activate_target = QCheckBox("Focus selected window on start")
    w.activate_target.setChecked(True)
    w.activate_target.setToolTip(
        "After the countdown, restore and focus your chosen desktop window. This uses your normal mouse and keyboard."
    )
    layout.addWidget(w.activate_target)
    w.routing_hint = label("")
    layout.addWidget(w.routing_hint)
    w.session_controls = QWidget()
    compact_session = QVBoxLayout(w.session_controls)
    compact_session.setContentsMargins(0, 0, 0, 0)
    w.session_status = label("Not launched. Set up a separate display for your game.")
    compact_session.addWidget(w.session_status)
    w.session_dialog = QDialog(w)
    w.session_dialog.setWindowTitle("Separate game session")
    w.session_dialog.setMinimumWidth(460)
    session = QVBoxLayout(w.session_dialog)
    session.setContentsMargins(24, 24, 24, 24)
    session.setSpacing(14)
    session.addWidget(label("Separate game session", "heading"))
    session.addWidget(
        label(
            "Advanced: launch a new game instance with independent mouse and keyboard. To use a game that is already open, choose Active desktop or Existing window in Run settings instead. Closing Automater leaves the game open."
        )
    )
    compact_session.addWidget(
        button("Set up game session…", lambda: w.session_dialog.show(), glyph="target")
    )
    session.addWidget(
        button(
            "Use an already open window…", w.choose_existing_desktop_window, "ghost", glyph="target"
        )
    )
    w.session_app = QComboBox()
    w.session_app.addItems(["Sober · Flatpak", "Custom application"])
    session.addWidget(w.session_app)
    w.session_command = QLineEdit()
    w.session_command.setPlaceholderText("/path/to/game --option")
    w.session_command.setAccessibleName("Custom game command; no shell expansion")
    w.session_command.hide()
    w.session_app.currentIndexChanged.connect(lambda i: w.session_command.setVisible(i == 1))
    session.addWidget(w.session_command)
    w.session_size = QComboBox()
    for width, height in ((1280, 720), (1920, 1080), (2560, 1440)):
        w.session_size.addItem(f"{width} × {height}", (width, height))
    session.addWidget(w.session_size)
    w.launch_session_btn = button("Launch game in session", w.launch_game_session, glyph="play")
    session.addWidget(w.launch_session_btn)
    w.session_dialog_status = label(
        "Choose an application and launch it, then select its window in Run settings."
    )
    session.addWidget(w.session_dialog_status)
    session.addWidget(
        button("Session diagnostics", w.show_session_diagnostics, "ghost", glyph="info")
    )
    w.close_session_btn = button("Close game session", w.close_game_session, "ghost", glyph="close")
    w.close_session_btn.setEnabled(False)
    session.addWidget(w.close_session_btn)
    session.addWidget(button("Done", w.session_dialog.hide, "primary", glyph="check"))
    w.session_controls.hide()
    layout.insertWidget(layout.indexOf(w.target), w.session_controls)
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
    w.gap = QDoubleSpinBox()
    w.gap.setRange(0, 3600)
    w.gap.setValue(0.25)
    w.gap.setSuffix(" s")
    for text, widget in (
        ("Speed", w.speed),
        ("Repeat", w.repeats),
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


def build_start_settings(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addWidget(label("Starting countdown", "heading"))
    layout.addWidget(
        label("Time to switch windows before recording or replay starts. F12 cancels.")
    )
    w.countdown = QSpinBox()
    w.countdown.setRange(0, 30)
    w.countdown.setValue(3)
    w.countdown.setSuffix(" s")
    w.countdown.valueChanged.connect(w.update_run_summary)
    layout.addWidget(w.countdown)
    layout.addSpacing(10)
    layout.addWidget(label("Loop starting point", "heading"))
    w.start_enabled = QCheckBox("Reset cursor each loop")
    w.start_enabled.toggled.connect(w.update_run_summary)
    layout.addWidget(w.start_enabled)
    w.start_capability = label("")
    layout.addWidget(w.start_capability)
    w.portal_connect_btn = button("Connect Wayland pointer", w.connect_pointer, glyph="target")
    layout.addWidget(w.portal_connect_btn)
    form = QFormLayout()
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    w.start_x, w.start_y = QSpinBox(), QSpinBox()
    for axis in (w.start_x, w.start_y):
        axis.setRange(-32768, 32767)
        axis.valueChanged.connect(w.update_run_summary)
    form.addRow("X", w.start_x)
    form.addRow("Y", w.start_y)
    w.start_settle = QDoubleSpinBox()
    w.start_settle.setRange(0, 10000)
    w.start_settle.setValue(150)
    w.start_settle.setSuffix(" ms")
    w.start_settle.valueChanged.connect(w.update_run_summary)
    form.addRow("Settle delay", w.start_settle)
    layout.addLayout(form)
    w.pick_position_btn = button("Pick position · 3 s", w.pick_position, glyph="target")
    layout.addWidget(w.pick_position_btn)
    w.pick_screen_btn = button("Choose on screen", w.pick_screen_point, glyph="select")
    layout.addWidget(w.pick_screen_btn)
    w.preview_start_btn = button(
        "Show starting point", w.preview_start_point, "ghost", glyph="target"
    )
    layout.addWidget(w.preview_start_btn)
    layout.addWidget(
        label(
            "The cursor moves first, settles, then the action sequence begins. Background mode uses window-relative coordinates and does not move your real cursor."
        )
    )
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
    actions.addWidget(button("Add folder…", w.add_library_folder, glyph="library"))
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
    layout.setSpacing(12)
    layout.addWidget(label("Input devices", "heading"))
    w.notice = label("Choose your keyboard and mouse. Your selection is remembered.", "body")
    layout.addWidget(w.notice)
    columns = QHBoxLayout()
    device_card, device = card("Record from", "Choose the physical inputs to use.")
    w.health = label("")
    device.addWidget(w.health)
    w.device_list = QListWidget()
    w.device_list.setAccessibleName("Physical input devices to monitor")
    w.device_list.setMinimumHeight(140)
    device.addWidget(w.device_list, 1)
    actions = QHBoxLayout()
    w.apply_devices_btn = button("Apply selection", w.refresh_devices, glyph="check")
    actions.addWidget(w.apply_devices_btn)
    actions.addWidget(button("Refresh", w.refresh_devices, "ghost", glyph="refresh"))
    actions.addWidget(button("Recommended", w.recommend_devices, "ghost"))
    device.addLayout(actions)
    columns.addWidget(device_card, 3)
    capture_card, capture = card("Capture", "Choose what goes into a recording.")
    w.capture_keys = QCheckBox("Keyboard")
    w.capture_buttons = QCheckBox("Mouse buttons and wheel")
    w.capture_motion = QCheckBox("Mouse movement")
    for widget in (w.capture_keys, w.capture_buttons, w.capture_motion):
        widget.setChecked(True)
        capture.addWidget(widget)
    w.append_recording = QCheckBox("Append to current workflow")
    capture.addSpacing(12)
    capture.addWidget(w.append_recording)
    capture.addWidget(
        label(
            "Recording adds to the end by default. To replace an action, select it and choose Re-record. Replacing the entire workflow asks first."
        )
    )
    capture.addStretch()
    capture.addWidget(label("F6 records or finishes. F7 runs. F8 pauses. F12 stops."))
    capture.addWidget(button("Input access help", w.show_help, "ghost", glyph="info"))
    capture.addWidget(button("Check compatibility", w.show_compatibility, "ghost", glyph="check"))
    columns.addWidget(capture_card, 2)
    layout.addLayout(columns, 1)
    details = QPushButton("Technical details")
    details.setObjectName("ghost")
    details.setCheckable(True)
    w.device_details = QTextEdit()
    w.device_details.setReadOnly(True)
    w.device_details.setMaximumHeight(130)
    w.device_details.hide()
    details.toggled.connect(w.device_details.setVisible)
    layout.addWidget(details, 0, Qt.AlignLeft)
    layout.addWidget(w.device_details)
    return scrollable(page)
