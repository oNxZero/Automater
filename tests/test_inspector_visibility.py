import pytest
from PySide6.QtCore import Qt
from test_gui import clean, window


@pytest.mark.parametrize("width", [1000, 1240])
@pytest.mark.parametrize("layout", ["horizontal", "vertical", "grid"])
def test_opening_properties_keeps_clicked_action_visible(
    qtbot, tmp_path, monkeypatch, width, layout
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_controls_example()
    win.resize(width, 800)
    choice = win.workflow.layout_choice
    choice.setCurrentIndex(choice.findData(layout))
    canvas = win.workflow.canvas
    canvas.choose_indices(set())
    win.hide_inspector()
    qtbot.wait(20)
    canvas.resetTransform()
    target = 3 if layout == "grid" else 5
    node = canvas.nodes[target]
    canvas.ensureVisible(node, 12, 12)
    qtbot.wait(20)
    position = canvas.mapFromScene(node.sceneBoundingRect().center())
    assert canvas.viewport().rect().contains(position)
    before = list(win.model.steps)
    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, pos=position)
    qtbot.wait(30)
    assert win.inspector_panel.isVisible()
    visible = canvas.mapFromScene(node.sceneBoundingRect()).boundingRect()
    assert canvas.viewport().rect().contains(visible), (visible, canvas.viewport().rect())
    assert canvas.selected_indices == {target}
    assert canvas.transform().m11() == 1
    assert win.model.steps == before
    clean(win)


def test_properties_reveal_waits_until_mouse_release(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_controls_example()
    canvas = win.workflow.canvas
    win.hide_inspector()
    canvas.choose_indices(set())
    qtbot.wait(20)
    canvas.resetTransform()
    node = canvas.nodes[5]
    canvas.ensureVisible(node, 12, 12)
    position = canvas.mapFromScene(node.sceneBoundingRect().center())
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=position)
    qtbot.wait(20)
    assert canvas.pointer_interaction and canvas.reveal_requested
    horizontal = canvas.horizontalScrollBar().value()
    qtbot.wait(20)
    assert canvas.horizontalScrollBar().value() == horizontal
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=position)
    qtbot.waitUntil(lambda: not canvas.reveal_requested)
    assert (
        canvas.viewport()
        .rect()
        .contains(canvas.mapFromScene(node.sceneBoundingRect()).boundingRect())
    )
    clean(win)


def test_resizing_open_properties_reveals_selection_without_changing_zoom(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_controls_example()
    win.workflow.canvas.choose_indices({5})
    qtbot.wait(20)
    canvas = win.workflow.canvas
    zoom = canvas.transform().m11()
    before = list(win.model.steps)
    win.resize(1000, 680)
    qtbot.wait(30)
    node = canvas.nodes[5]
    assert (
        canvas.viewport()
        .rect()
        .contains(canvas.mapFromScene(node.sceneBoundingRect()).boundingRect())
    )
    assert canvas.transform().m11() == zoom and win.model.steps == before
    clean(win)
