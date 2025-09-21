from __init__ import *
self = PortableFS(Path("filesysMock2.bin"))

def sortModeHighDir(obj: File | Directory):
    return obj.highDir

self.files.sort(key=sortModeHighDir)
print(self.files)