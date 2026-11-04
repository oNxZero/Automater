from PySide6.QtCore import QDir
from PySide6.QtWidgets import QDialog, QFileDialog
from test_gui import clean, window

from moonlight_studio.models import Script, Step
from moonlight_studio.storage import load, save


def test_saved_tabs_use_filenames_without_changing_workflow_data(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    script = Script(steps=[Step(25)])
    save(script, first)
    save(script, second)
    win.open_path(first)
    assert win.document_tabs.tabText(win.document_tabs.currentIndex()) == "first"
    assert not win.dirty() and win.script().to_dict() == script.to_dict()
    win.open_path(second)
    assert win.document_tabs.tabText(win.document_tabs.currentIndex()) == "second"
    win.document_tabs.setCurrentIndex(1)
    assert win.document_tabs.tabText(1) == "first"
    assert not win.dirty()
    clean(win)


def test_open_and_save_as_share_folder_and_relative_save_stays_inside_it(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    folder = tmp_path / "my-workflows"
    original = folder / "original.json"
    save(Script(steps=[Step(25)]), original)
    win.open_path(original)
    calls = {}

    class Dialog:
        AcceptSave = QFileDialog.AcceptSave

        def __init__(self, parent, title, directory, file_filter):
            calls["save_folder"] = directory
            self.folder = directory

        def setAcceptMode(self, value):
            pass

        def setDefaultSuffix(self, value):
            pass

        def setDirectory(self, value):
            self.folder = value

        def selectFile(self, value):
            calls["suggested_filename"] = value

        def exec(self):
            return QDialog.Accepted

        def selectedFiles(self):
            return ["renamed.json"]

        def directory(self):
            return QDir(self.folder)

        @staticmethod
        def getOpenFileName(parent, title, directory, file_filter):
            calls["open_folder"] = directory
            return "", ""

    monkeypatch.setattr("moonlight_studio.window.QFileDialog", Dialog)
    assert win.save_as()
    assert win.path == folder / "renamed.json"
    assert load(win.path).steps == [Step(25)]
    assert calls["suggested_filename"] == "original.json"
    assert win.document_tabs.tabText(win.document_tabs.currentIndex()) == "renamed"
    win.open_script()
    assert calls["save_folder"] == calls["open_folder"] == str(folder)
    assert original.exists()
    clean(win)


def test_workflow_folder_exists_and_last_folder_survives_new_tabs_and_restart(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    assert win.script_dialog_directory() == tmp_path / "scripts"
    assert (tmp_path / "scripts").is_dir()
    folder = tmp_path / "chosen-folder"
    path = folder / "workflow.json"
    save(Script(steps=[Step(25)]), path)
    win.open_path(path)
    win.new_script()
    assert win.script_dialog_directory() == folder
    other = window(qtbot, tmp_path, monkeypatch)
    assert other.script_dialog_directory() == folder
    clean(win)
    clean(other)
