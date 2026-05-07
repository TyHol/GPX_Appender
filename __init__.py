def classFactory(iface):
    from .gpx_appender import GPXAppender
    return GPXAppender(iface)
