STL-Dateien für den Grundriss-Tab gehören hier hinein (z.B. `wohnung.stl`).

Dieser Ordner wird per `.gitignore` von Git ausgeschlossen (private Wohnungsdaten,
Repo ist öffentlich) – die STL-Datei muss daher nach jedem frischen Clone bzw.
auf dem Raspberry Pi einmalig manuell hierher kopiert werden (z.B. per `scp`),
sie wird nicht automatisch vom Auto-Update-Timer mitgezogen.
