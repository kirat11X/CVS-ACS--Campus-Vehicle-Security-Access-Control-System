"""
Opens a video's frames in AnyLabeling, with the Objects-list tick saved into the JSON.

    python3 scripts/anylabel.py 2                  # opens training/2/images
    python3 scripts/anylabel.py 2 --theme dark     # anything after the video number goes to AnyLabeling

Run it with the Python that has AnyLabeling installed (the conda one: `python3` here). It starts AnyLabeling exactly
like `anylabeling --nodata --autosave --labels license_plate training/2/images`, plus one change made while the app
runs (the installed package is not edited):

    untick an object in the Objects list  ->  that box gets  "excluded": true  in its JSON, and the file is saved
    tick it again                         ->  the key is removed

"excluded" means "do not train on this box": train_on_video.py leaves it out of the labels and blanks its pixels in
the training copy of the frame (so a real plate you excluded is not taught as background), and extract_plates.py
--refresh does not list it. Plain AnyLabeling only hides an unticked box on screen and saves nothing about it.

If a future AnyLabeling changes the internals this relies on, the script says so and starts unpatched.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LABEL = "license_plate"
KEY = "excluded"


def install_patch():
    """Make the Objects-list tick persistent. Returns True if the patch is active."""
    from PyQt6.QtCore import Qt
    from anylabeling.views.labeling.label_widget import LabelingWidget

    needed = ("label_item_changed", "add_label", "load_shapes", "set_dirty")
    missing = [n for n in needed if not hasattr(LabelingWidget, n)]
    if missing:
        print(f"WARNING: this AnyLabeling has no {missing}; the Objects tick will NOT be saved.", file=sys.stderr)
        return False

    original_changed, original_add, original_load = LabelingWidget.label_item_changed, LabelingWidget.add_label, LabelingWidget.load_shapes

    def label_item_changed(self, item):
        original_changed(self, item)  # AnyLabeling's own show / hide
        if getattr(self, "_adding_label", False):
            return  # items are added ticked and then renamed: that is loading, not you clicking
        shape = item.shape()
        unticked = item.checkState() != Qt.CheckState.Checked
        if bool(shape.other_data.get(KEY)) != unticked:
            if unticked:
                shape.other_data[KEY] = True
            else:
                shape.other_data.pop(KEY, None)
            self.set_dirty()  # autosaves (or marks the file as changed)

    def add_label(self, shape):
        excluded = bool(shape.other_data.get(KEY))
        self._adding_label = True
        try:
            original_add(self, shape)
            if excluded:  # a box saved as excluded comes back unticked
                item = self.label_list.find_item_by_shape(shape)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Unchecked)
        finally:
            self._adding_label = False

    def load_shapes(self, shapes, replace=True):
        original_load(self, shapes, replace)
        for shape in shapes:  # the canvas starts every shape visible: hide the excluded ones again
            if shape.other_data.get(KEY):
                self.canvas.set_shape_visible(shape, False)

    LabelingWidget.label_item_changed, LabelingWidget.add_label, LabelingWidget.load_shapes = label_item_changed, add_label, load_shapes
    return True


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    folder = PROJECT_ROOT / "training" / sys.argv[1] / "images"
    if not folder.is_dir():
        sys.exit(f"{folder} not found; run extract_plates.py {sys.argv[1]} first.")
    sys.argv = ["anylabeling", "--nodata", "--autosave", "--labels", LABEL, str(folder), *sys.argv[2:]]
    install_patch()
    from anylabeling.app import main as anylabeling_main

    anylabeling_main()


if __name__ == "__main__":
    main()
