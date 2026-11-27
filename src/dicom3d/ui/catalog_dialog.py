"""Fereastra bazei de date: seriile CT din catalog, cu cautare, filtre si sursa fiecarei serii.

De aici se deschide o serie (dublu clic sau Enter), se adauga foldere proprii in catalog
sau se descarca seriile reale din colectiile publice TCIA.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from dicom3d.catalog import Catalog, SeriesRow
from dicom3d.catalog import download as dl
from dicom3d.catalog.indexer import index_folder
from dicom3d.ui import icons, theme
from dicom3d.ui.widgets import ElidedLabel, fmt_int, fmt_num, label, separator, value_label
from dicom3d.ui.worker import Worker

COLUMNS = ("Colecție", "Pacient", "Sex", "Vârstă", "Regiune", "Descriere", "Felii",
           "Grosime", "Aparat")
NUMERIC = {3, 6, 7}
REGION_LABELS = {"torace": "Torace", "abdomen": "Abdomen"}


class _Progress(QObject):
    """Mesajele de progres din firul de lucru ajung in interfata printr-un semnal."""

    message = Signal(str)


class CatalogDialog(QDialog):
    def __init__(self, catalog: Catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.pool = QThreadPool.globalInstance()
        self.selected_uid: str | None = None
        self._rows: list[SeriesRow] = []
        self._busy = False
        self.setWindowTitle("Bază de date – DICOM3D")
        self.resize(1080, 640)
        self.setMinimumSize(760, 460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(label("Bază de date", "brand"))
        self.stats_label = value_label("", 13)
        head.addWidget(self.stats_label, 1)
        lay.addLayout(head)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Caută pacient, descriere, colecție sau aparat")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.region_combo = QComboBox()
        self.collection_combo = QComboBox()
        for combo in (self.region_combo, self.collection_combo):
            combo.setMinimumWidth(170)
            combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.region_combo)
        filters.addWidget(self.collection_combo)
        lay.addLayout(filters)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("catalogTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i in range(len(COLUMNS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.itemDoubleClicked.connect(lambda _item: self._open())
        lay.addWidget(self.table, 1)

        # sursa seriei alese: licenta si citarea obligatorie (trebuie trecute in lucrare)
        self.source = QFrame()
        self.source.setObjectName("catalogSource")
        s = QVBoxLayout(self.source)
        s.setContentsMargins(12, 10, 12, 10)
        s.setSpacing(4)
        self.source_title = label("", "h")
        self.source_detail = ElidedLabel("", "muted")
        self.source_detail.setFont(theme.num_font(12))
        self.source_cite = label("", "hint", wrap=True)
        self.source_cite.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for w in (self.source_title, self.source_detail, self.source_cite):
            s.addWidget(w)
        lay.addWidget(self.source)

        lay.addWidget(separator())
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.add_btn = QPushButton(" Adaugă folder…")
        self.add_btn.setIcon(icons.icon("folder"))
        self.add_btn.setToolTip("Adaugă în bază seriile DICOM dintr-un folder propriu")
        self.add_btn.clicked.connect(self._add_folder)
        self.download_btn = QPushButton(" Descarcă seriile TCIA")
        self.download_btn.setIcon(icons.icon("download"))
        self.download_btn.clicked.connect(self._download)
        self.progress_label = ElidedLabel("", "muted")
        self.close_btn = QPushButton("Închide")
        self.close_btn.clicked.connect(self.reject)
        self.open_btn = QPushButton("Deschide seria")
        self.open_btn.setProperty("variant", "primary")
        self.open_btn.setMinimumWidth(160)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self._open)
        for b in (self.add_btn, self.download_btn, self.close_btn, self.open_btn):
            b.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.add_btn)
        foot.addWidget(self.download_btn)
        foot.addWidget(self.progress_label, 1)
        foot.addWidget(self.close_btn)
        foot.addWidget(self.open_btn)
        lay.addLayout(foot)

        self._manifest = dl.load_manifest()
        dl.register_collections(self.catalog, self._manifest)
        self._fill_filters()
        self.refresh()

    # ---------- continut ----------

    def _fill_filters(self):
        for combo, first, items in (
            (self.region_combo, "Toate regiunile",
             [(REGION_LABELS.get(r, r.capitalize()), r) for r in self.catalog.regions()]),
            (self.collection_combo, "Toate colecțiile",
             [(c["name"], c["id"]) for c in self.catalog.collections() if c["series"]]),
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first, "")
            for text, data in items:
                combo.addItem(text, data)
            idx = combo.findData(current)
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)

    def refresh(self):
        self._rows = self.catalog.series(self.search.text(), self.region_combo.currentData() or "",
                                         self.collection_combo.currentData() or "")
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            values = (
                r.collection_name, r.patient_key, r.sex or "–",
                r.age_years if r.age_years is not None else None,
                REGION_LABELS.get(r.region, r.region.capitalize()) or "–", r.title, r.num_instances,
                r.slice_thickness_mm or r.slice_spacing_mm, " ".join(x for x in (r.manufacturer, r.model) if x) or "–",
            )
            for j, v in enumerate(values):
                item = _Item(v, j)
                item.setData(Qt.UserRole, r.series_uid)
                if j in NUMERIC:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setFont(theme.num_font(13))
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)
        if self._rows:
            self.table.selectRow(0)
        else:
            self._on_selection()

        st = self.catalog.stats()
        pending = len([s for s in self._manifest["serii"]
                       if self.catalog.get(s["serie_uid"]) is None])
        self.stats_label.setText(
            f"{st['patients']} pacienți  ·  {st['series']} serii  ·  "
            f"{fmt_int(st['instances'])} felii  ·  {fmt_num(st['size_bytes'] / 1024**3, 2)} GB")
        mb = sum(s["mb"] for s in self._manifest["serii"] if self.catalog.get(s["serie_uid"]) is None)
        self.download_btn.setVisible(pending > 0)
        self.download_btn.setText(f" Descarcă seriile TCIA ({pending}, ~{fmt_num(mb / 1024, 1)} GB)")
        self.download_btn.setToolTip(
            "Serii CT reale, anonimizate, din colecțiile publice The Cancer Imaging Archive "
            "(prin NCI Imaging Data Commons). Nu e nevoie de cont.")
        if not st["series"] and not self._busy:
            self.progress_label.setText("Baza e goală: descarcă seriile TCIA sau adaugă un folder.")

    def _on_selection(self):
        items = self.table.selectedItems()
        self.selected_uid = items[0].data(Qt.UserRole) if items else None
        self.open_btn.setEnabled(self.selected_uid is not None and not self._busy)
        row = next((r for r in self._rows if r.series_uid == self.selected_uid), None)
        self.source.setVisible(row is not None)
        if row is None:
            return
        coll = next((c for c in self.catalog.collections() if c["id"] == row.collection_id), {})
        self.source_title.setText(f"{row.patient_key}  ·  {row.collection_name}")
        parts = [
            f"{row.columns} × {row.rows} × {row.num_instances}" if row.rows else "",
            f"pixel {fmt_num(row.pixel_spacing_mm, 2)} mm" if row.pixel_spacing_mm else "",
            f"pas {fmt_num(row.slice_spacing_mm, 2)} mm" if row.slice_spacing_mm else "",
            f"acoperire {fmt_num(row.extent_mm / 10, 1)} cm" if row.extent_mm else "",
            f"filtru {row.convolution_kernel}" if row.convolution_kernel else "",
            "cu contrast" if row.contrast_agent else "",
            f"{fmt_num(row.size_bytes / 1024**2, 0)} MB",
        ]
        self.source_detail.setText("  ·  ".join(p for p in parts if p))
        self.source_detail.setToolTip(row.folder)
        if coll.get("citation"):
            self.source_cite.setText(f"Licență {coll['license']}. Citare: {coll['citation']}")
        else:
            self.source_cite.setText("Serie proprie, adăugată din " + row.folder)

    # ---------- actiuni ----------

    def _open(self):
        if self.selected_uid and not self._busy:
            self.accept()

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Alege folderul cu serii DICOM")
        if folder:
            self._start(index_folder, (self.catalog, folder),
                        {"known": dl.known_series(self._manifest)},
                        f"Indexez {folder}…", "Seriile din folder au fost adăugate.")

    def _download(self):
        pending = [s for s in self._manifest["serii"] if self.catalog.get(s["serie_uid"]) is None]
        mb = sum(s["mb"] for s in pending)
        home = self.catalog.path.parent
        free = dl.free_space_gb(home)
        if free < mb / 1024 * 1.1:
            QMessageBox.warning(self, "DICOM3D", f"Nu e destul spațiu pe disc: trebuie "
                                f"~{fmt_num(mb / 1024, 1)} GB, sunt liberi {fmt_num(free, 1)} GB.")
            return
        ok = QMessageBox.question(
            self, "Descarcă seriile TCIA",
            f"Descarc {len(pending)} serii CT reale (~{fmt_num(mb / 1024, 1)} GB) în\n{home / 'date'}\n\n"
            "Datele sunt anonimizate de The Cancer Imaging Archive. Licențele (CC BY / CC BY-NC) "
            "cer citarea colecției; citarea apare sub tabel pentru fiecare serie.")
        if ok == QMessageBox.Yes:
            self._start(dl.download, (home, self.catalog), {},
                        "Pornesc descărcarea…", "Descărcare terminată.")

    def _start(self, fn, args, kwargs, message: str, done: str):
        progress = _Progress(self)
        progress.message.connect(self.progress_label.setText)
        worker = Worker(fn, *args, progress=progress.message.emit, **kwargs)
        worker.signals.finished.connect(lambda _r: self._finish(done))
        worker.signals.failed.connect(lambda m: self._finish("Eroare: " + m, error=True))
        self._set_busy(True)
        self.progress_label.setText(message)
        self.pool.start(worker)

    def _finish(self, message: str, error: bool = False):
        self._set_busy(False)
        self.progress_label.setText(message)
        self._fill_filters()
        self.refresh()
        if error:
            QMessageBox.critical(self, "DICOM3D", message)

    def _set_busy(self, busy: bool):
        self._busy = busy
        for b in (self.add_btn, self.download_btn):
            b.setEnabled(not busy)
        self.open_btn.setEnabled(not busy and self.selected_uid is not None)

    def reject(self):
        if self._busy:  # descarcarea continua in fundal; fereastra nu se inchide sub ea
            QMessageBox.information(self, "DICOM3D", "Așteaptă să se termine operația în curs.")
            return
        super().reject()


class _Item(QTableWidgetItem):
    """Celula care se sorteaza dupa valoare (numerele ca numere, golurile la final)."""

    def __init__(self, value, column: int):
        if value is None:
            text = "–"
        elif column == 7:
            text = f"{fmt_num(value, 1 if value % 1 else 0)} mm"
        else:
            text = str(value)
        super().__init__(text)
        self._key = (value is None, value if value is not None else 0)

    def __lt__(self, other):
        if isinstance(other, _Item):
            try:
                return self._key < other._key
            except TypeError:
                return str(self._key[1]) < str(other._key[1])
        return super().__lt__(other)
