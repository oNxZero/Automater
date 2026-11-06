from PySide6.QtCore import QPointF
from test_batch_recording import feed, setup_recording
from test_gui import clean, window

from automater.camera import CameraFollower
from automater.dialogs import SaveChangesDialog
from automater.models import Script, Step
from automater.storage import load, save


def test_short_workflow_fits_after_layout_without_tiny_initial_text(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.resize(1000, 680)
    win.hide_inspector()
    canvas = win.workflow.canvas
    qtbot.wait(30)  # Let the first document and deferred widget layout settle.
    qtbot.waitUntil(lambda: not canvas.fit_pending)
    assert canvas.transform().m11() >= 0.9
    canvas.zoom(0.6)
    zoom = canvas.transform().m11()
    win.navigate(1)
    win.navigate(0)
    qtbot.wait(30)
    assert canvas.transform().m11() == zoom
    clean(win)


def test_grid_columns_follow_viewport_width_zoom_and_inspector(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=[Step(20, standalone=True) for _ in range(348)]))
    win.workflow.layout_choice.setCurrentIndex(2)
    win.hide_inspector()
    win.resize(1000, 800)
    qtbot.wait(30)
    canvas = win.workflow.canvas
    small = canvas.grid_columns
    win.resize(3440, 1440)
    qtbot.wait(30)
    large = canvas.grid_columns
    assert large > small and large > 4
    assert canvas.node_position(large).x() == canvas.node_position(0).x()
    assert canvas.node_position(large).y() > canvas.node_position(0).y()
    win.show_inspector(0)
    qtbot.wait(30)
    assert canvas.grid_columns < large
    canvas.zoom(0.75)
    qtbot.wait(30)
    assert canvas.grid_columns > small
    assert len(win.model.steps) == 348
    clean(win)


def test_camera_retarget_keeps_velocity_and_moves_continuously(qtbot):
    camera = CameraFollower()
    camera.move_to(QPointF(0, 0), QPointF(800, 0))
    camera.advance(0.08)
    point, velocity = QPointF(camera.position), QPointF(camera.velocity)
    camera.move_to(camera.position, QPointF(1200, 600))
    assert camera.position == point and camera.velocity == velocity
    camera.advance(0.01)
    assert point.x() < camera.position.x() < 1200
    assert 0 < camera.position.y() < 600
    for _ in range(100):
        camera.advance(0.01)
    assert (camera.position - QPointF(1200, 600)).manhattanLength() < 1
    camera.stop()


def test_library_discovers_external_saved_json_and_searches_names(qtbot, tmp_path, monkeypatch):
    folder = tmp_path / "saved-elsewhere"
    save(Script("Actual routine", steps=[Step(20)]), folder / "mining.json")
    (folder / "settings.json").write_text('{"preferences": true}')
    win = window(qtbot, tmp_path / "config", monkeypatch)
    win.preferences.library_folders = [str(folder)]
    win.save_preferences()
    win.refresh_library()
    qtbot.waitUntil(lambda: not win.library_scan_pending, timeout=3000)
    assert win.library.count() == 1
    assert "mining" in win.library.item(0).text()
    win.library_search.setText("actual routine")
    assert not win.library.item(0).isHidden()
    win.library_search.setText("mining")
    assert not win.library.item(0).isHidden()
    other = window(qtbot, tmp_path / "config", monkeypatch)
    qtbot.waitUntil(lambda: not other.library_scan_pending, timeout=3000)
    assert other.library.count() == 1
    clean(win)
    clean(other)


def test_tab_rename_moves_saved_file_without_overwriting_or_losing_edits(
    qtbot, tmp_path, monkeypatch
):
    first = tmp_path / "first.json"
    save(Script(steps=[Step(20)]), first)
    win = window(qtbot, tmp_path / "config", monkeypatch)
    win.open_path(first)
    win.model.commit([Step(40)], "Unsaved change")
    win.rename_document(win.document_tabs.currentIndex(), "renamed")
    assert not first.exists() and win.path == tmp_path / "renamed.json"
    assert load(win.path).steps == [Step(20)]
    assert win.model.steps == [Step(40)] and win.dirty()
    save(Script(), tmp_path / "taken.json")
    win.rename_document(win.document_tabs.currentIndex(), "taken")
    assert win.path == tmp_path / "renamed.json"
    assert "already exists" in win.status.text()
    assert win.save_script() and load(win.path).steps == [Step(40)]
    clean(win)


def test_live_preview_shows_inputs_before_appending_and_discard_keeps_work(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    setup_recording(win, monkeypatch)
    before = list(win.model.steps)
    win.begin_recording()
    feed(win)
    win.capture_tick()
    assert win.record_preview.isVisible()
    assert win.record_preview.count == 2
    assert win.record_preview.displayed_blocks[0].kind == "key"
    assert win.model.steps == before
    win.stop(discard_recording=True)
    assert not win.record_preview.isVisible() and win.model.steps == before
    clean(win)


def test_custom_save_dialog_has_safe_cancel_and_explicit_choices(qtbot):
    dialog = SaveChangesDialog(None, "My workflow", count=12)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.reject()
    assert dialog.choice == "cancel"
    dialog.show()
    dialog.save.click()
    assert dialog.choice == "save"
    other = SaveChangesDialog(None, "Other workflow")
    qtbot.addWidget(other)
    other.discard.click()
    assert other.choice == "discard"


def test_cancelled_save_does_not_close_dirty_workflow(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.add_step()
    before = list(win.model.steps)
    monkeypatch.setattr(SaveChangesDialog, "ask", lambda *args: "save")
    monkeypatch.setattr(win, "save_script", lambda: False)
    win.close_document(0)
    assert win.model.steps == before and win.document_tabs.count() == 1
    monkeypatch.setattr(SaveChangesDialog, "ask", lambda *args: "discard")
    clean(win)


def test_generated_activation_script_activates_only_the_exact_window(qapp):
    import json

    from PySide6.QtQml import QJSEngine

    from automater.open_windows import DesktopWindow, activation_script

    target = DesktopWindow('window-"ID', "Game", 123, ('app-"PID',))
    engine = QJSEngine()
    data = {
        "internalId": target.id,
        "pid": target.pid,
        "resourceClass": target.wm_class[0],
        "minimized": True,
        "desktops": ["desk2"],
    }
    engine.evaluate(
        "var chosen = "
        + json.dumps(data)
        + "; var workspace = {activeWindow: null, currentDesktop: 'desk1', windowList: () => [chosen]};"
    )
    result = engine.evaluate(activation_script(target))
    assert not result.isError(), result.toString()
    assert engine.evaluate(
        "workspace.activeWindow === chosen && !chosen.minimized && workspace.currentDesktop === 'desk2'"
    ).toBool()
    engine.evaluate("workspace.activeWindow = null")
    wrong = DesktopWindow(target.id, target.title, 999, target.wm_class)
    assert engine.evaluate(activation_script(wrong)).isError()
    assert engine.evaluate("workspace.activeWindow === null").toBool()


def test_selected_window_is_activated_after_countdown_before_inputs(qtbot, tmp_path, monkeypatch):
    from test_engine import Backend
    from test_window_picker import seed_windows

    win = window(qtbot, tmp_path, monkeypatch)
    native, _ = seed_windows(win)
    win.target.setCurrentIndex(win.target_index(native))
    with win.window_observer.lock:
        win.window_observer.active_id = "other-window"
    backend = Backend()
    sequence = []

    def activate(target):
        sequence.append("activate")
        with win.window_observer.lock:
            win.window_observer.active_id = target.id

    original_send = backend.send

    def send(step):
        sequence.append(step.action)
        original_send(step)

    backend.send = send

    def factory():
        return backend

    factory.startup_delay = 0
    monkeypatch.setattr("automater.window.UInputBackend", factory)
    monkeypatch.setattr(win.window_observer, "activate", activate)
    win.test_mode.setChecked(False)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    qtbot.waitUntil(lambda: not win.busy, timeout=3000)
    assert sequence[0] == "activate"
    assert any(action == "key_down" for action in sequence)
    assert not win.playback_error and backend.closed
    clean(win)
