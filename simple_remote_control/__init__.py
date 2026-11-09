def classFactory(iface):
    from .simple_remote_control import SimpleRemoteControlPlugin

    return SimpleRemoteControlPlugin(iface)
