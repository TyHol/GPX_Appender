def classFactory(iface):
    from .gpx_importer import GPXImporter
    return GPXImporter(iface)
