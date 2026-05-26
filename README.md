# SMaRC Mission Control Plugin for QGIS

[WARA-PS API](https://api-docs.waraps.org/#/) compliant mission planning in the open-source GIS software [QGIS](https://qgis.org/).

## Installation instructions
Supported QGIS version: v3.44 LTR  
Supported Ubuntu version(s): 22.04 (Python 3.10)

1. Install QGIS v3.44 LTR from [qgis.org](https://qgis.org/download)

2. Install the SMaRC Mission Control Plugin
   - Option 1: Clone the repository into the QGIS Python library folder:
     - Windows: `C:\Users\<user>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins`
     - Ubuntu: `.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
       - `.../plugins` might not exist if this is the very first one you are creating. Create the folder if that is the case.
   - Option 2: Download the repository as a zip file and load it via the plugin manager: *Plugins* -> *Manage and install plugins ...* -> *Install from ZIP*
   - Option 3: Pull the submoudle in smarc2 and symlink it to QGIS Python library folder (see Option 1 above)
     - `cd smarc2`
     - `git submodule update --remote --init ./external_equipment/qgis/smarc_qgis_misison_control`
     - `cd .local/share/QGIS/QGIS3/profiles/default/python/plugins/`
     - `sudo ln -s /path/to/smarc2/external_equipment/qgis/smarc_qgis_misison_control`
   - **Enable the plugin** : Plugins -> Installed -> Chcek the box for smarc
  
3. Install other useful plugins via the plugin manager, for example
   -  Plugin Reloader
   -  Basemaps
   -  Cruise Tools
  
4. Add a base layer either via the *Basemaps* plugin or via
   - *Layer* -> *Add Layer ...* -> *Add XYZ Layer ...*
     - OpenStreetMaps: `https://tile.openstreetmap.org/{z}/{x}/{y}.png`
     - Google Maps (Satellite): `https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}`
     - Google Maps (Hybrid): `https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}`
     - Google Maps (Roadmap): `https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}`
   - *Layer* -> *Add Layer ...* -> *Add WMS/WMTS Layer ...*

5. Start betatesting the plugin :-)

## Developer instructions

### UI design
0. Install PyQt5 via `pip install PyQt5` (or any other way)
1. Develop UI layout in QtDesigner to generate *.ui files
2. Produce python files from *.ui files using the PyQt5 command: `pyuic5 --from-imports -o <output.py> <input.ui>`
3. If you want to add custom icons, place them in src/ui/qtdesigner/custom_icons and run `pyrcc5 src/ui/qtdesigner/resources.qrc -o src/ui/generated/resources_rc.py
`
