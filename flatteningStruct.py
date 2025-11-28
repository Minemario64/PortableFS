from __init__ import *
from pathlib import Path
import tester
import time

def flattenRec(dirContents: dict[str, tuple[File, bytes] | tuple[Directory, dict]]) -> tuple[list[File], list[Directory]]:
    files, dirs = [], []
    for name, val in dirContents.items():
        if isinstance(val[0], File):
            file: File = val[0]
            file.name = name
            file.size = len(val[1])
            files.append(file)
            continue

        if isinstance(val[0], Directory):
            folder: Directory = val[0]
            folder.name = name
            dirs.append(folder)
            recFiles, recDirs = flattenRec(val[1]) # pyright: ignore[reportArgumentType]
            files.extend(recFiles)
            dirs.extend(recDirs)
            continue

    return files, dirs

def flattenStruct(self: PortableFS) -> tuple[list[File], list[Directory]]:
    files: list[File] = []
    dirs: list[Directory] = []
    for drive in self.drives:
        driveFiles, driveDirs = flattenRec(self._struct.traversalGet(drive.name)) # pyright: ignore[reportArgumentType]
        files.extend(driveFiles)
        dirs.extend(driveDirs)

    return files, dirs

def sortModeHighDir(obj: File | Directory):
    return obj.highDir

if __name__ == "__main__":
    tester.GLOBALS |= {"flstruct": flattenStruct, "Path": Path, 'PortableFS': PortableFS, 'time': time, "sortModeHighDir": sortModeHighDir}

    tester.describe("Flattening PortableFS Struct", r'''
    it("filesysMock1 flattening", """
        pfs = PortableFS(Path("filesysMock1.bin"))
        files, dirs = flstruct(pfs)
        print(files, dirs, sep="\\\n\\\n")
        time.sleep(15)
        passed((files == pfs.files) and (dirs == pfs.dirs))
    """)
    it("filesysMock2 flattening", """
        pfs = PortableFS(Path("filesysMock2.bin"))
        files, dirs = flstruct(pfs)
        print(files, dirs, sep="\\\n\\\n")

        pfs.files.sort(key=sortModeHighDir)
        print(pfs.files, pfs.dirs, sep="\\\n\\\n")
        time.sleep(15)
        passed((files == pfs.files) and (dirs == pfs.dirs))
    """)
    ''')