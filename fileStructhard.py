from __init__ import *
from typing import Any
self = PortableFS(Path("filesysMock2.bin"))

class DictStructPath(dict):
    def traversalSet(self, path: str, value: Any) -> None:
        parts: list[str] = path.split("/")
        strCode: str = f"self[{int(parts[0])}]"
        for part in parts[1:-1]:
            strCode += f"['{part}'][1]"

        strCode += f"['{parts[-1]}'] = val"
        exec(strCode, {"__builtins__": None, "self": self, "val": value})

struct: DictStructPath = DictStructPath({})
HighDirTable: dict[int, list[File | Directory]] = {}
dirPathTable: dict[int, str] = {}

for drive in self.drives:
    struct[drive.id] = {}

for file in self.files:
    if file.highDir <= 0x0F:
        self.file.seek(self._PortableFS__dataStart + file.offset)
        struct[file.highDir][file.name] = (file, self.file.read(file.size))
        continue

    if not file.highDir in HighDirTable.keys():
        HighDirTable[file.highDir] = [file]

    else:
        HighDirTable[file.highDir].append(file)


for directory in self.dirs:
    if directory.highDir <= 0x0F:
        struct[directory.highDir][directory.name] = (directory, {})
        dirPathTable[directory.id] = f"{directory.highDir}/{directory.name}"
        continue

    if (not directory.highDir in HighDirTable.keys()) and directory.id in HighDirTable.keys():
        struct.traversalSet(f"{dirPathTable[directory.highDir]}/{directory.name}", (directory, {}))
        dirPathTable[directory.id] = f"{dirPathTable[directory.highDir]}/{directory.name}"

    if not directory.highDir in HighDirTable.keys():
        HighDirTable[directory.highDir] = [directory]

    else:
        HighDirTable[directory.highDir].append(directory)

while len(HighDirTable) > 0:
    popQueue: list[int] = []
    for dirID, items in HighDirTable.items():
        if isinstance(items, str):
            continue

        if dirID in dirPathTable.keys():
            for item in items:
                if isinstance(item, File):
                    self.file.seek(self._PortableFS__dataStart + item.offset)
                    struct.traversalSet(f"{dirPathTable[dirID]}/{item.name}", (item, self.file.read(item.size)))
                    continue

                if isinstance(item, Directory):
                    struct.traversalSet(f"{dirPathTable[dirID]}/{item.name}", (item, {}))
                    continue

            popQueue.append(dirID)

    for dirID in popQueue:
        HighDirTable.pop(dirID)

for drive in self.drives:
    struct[drive.name] = struct[drive.id]
    struct.pop(drive.id)

print(struct, HighDirTable, dirPathTable, sep="\n")