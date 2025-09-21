from pathlib import Path
from typing import BinaryIO, Any
from copy import deepcopy
from dataclasses import dataclass
import re as rgx

def readBits(stream: BinaryIO, numBits: int, mode: int = 0) -> int:
    numBytes = (numBits + 7) // 8
    data = stream.read(numBytes)
    if len(data) != numBytes:
        raise EOFError("Not enough data to read the specified number of bits")
    if mode == 0:
        value = int.from_bytes(data, byteorder="big")
        return value >> (numBytes * 8 - numBits)

    elif mode == 1:
        value = int.from_bytes(data, byteorder="big")
        return value & ((1 << numBits) - 1)

    else:
        raise ValueError("Invalid mode.")

@dataclass
class Drive:
    name: str
    id: int

    def __repr__(self) -> str:
        return f"Drive(name='{self.name}', id={hex(self.id)})"

@dataclass
class FileAttrs:
    readOnly: bool
    hidden: bool

@dataclass
class DirAttrs:
    hidden: bool

@dataclass
class File:
    name: str
    attributes: FileAttrs
    highDir: int
    offset: int
    size: int

@dataclass
class Directory:
    id: int
    name: str
    attributes: DirAttrs
    highDir: int

class PortableFSEncodingError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"PortableFS Encoding Error: {message}")

class PortableFSPathError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"PortableFS Path Error: {message}")

class PortableFSFileNotFoundError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"PortableFS File Not Found Error: {message}")

class PortableFS:
    VERSION: int = 1
    DRIVE_CHARS: list[str] = list("ABCDEFGHIJKLMNOP")

    def __init__(self, fspath: Path) -> None:
        self.fspath: Path = fspath
        self.file: BinaryIO = fspath.open("r+b")
        if self.file.read(4) != b"pfs0":
            raise ValueError("Not a PortableFS file")

        if self.file.read(1) != bytes([self.VERSION - 1]):
            raise ValueError("Unsupported PortableFS version: Version 1 only")

        self.name: str = self.file.read(13).decode("utf-8").rstrip("\x00")
        self.numDrives: int = readBits(self.file, 4, 1)
        self.drives: list[Drive] = []
        for _ in range(self.numDrives):
            drive_name = self.DRIVE_CHARS[readBits(self.file, 4, 0)]
            self.file.seek(-1, 1)
            drive_id = readBits(self.file, 4, 1)
            self.drives.append(Drive(drive_name, drive_id))

        self.numDirs: int = int.from_bytes(self.file.read(2), byteorder="big")
        self.dirs: list[Directory] = []
        for _ in range(self.numDirs):
            dir_id = int.from_bytes(self.file.read(2), byteorder="big")
            if dir_id <= 0x0F:
                raise PortableFSEncodingError("Directory ID must be greater than 0x0F")

            if dir_id >= 0x8000:
                raise PortableFSEncodingError("Directory ID must be less than 0x8000")
            dirname = self.file.read(int(self.file.read(1).hex(), 16)).decode("utf-8")
            attributesInt = readBits(self.file, 2, 0)
            attrs = (attributesInt >> 1, attributesInt & 1)
            hightDir = int.from_bytes(self.file.read(2), byteorder="big")
            self.dirs.append(Directory(dir_id, dirname, DirAttrs(bool(attrs[0])), hightDir))


        self.numFiles: int = int.from_bytes(self.file.read(3), byteorder="big")
        self.files: list[File] = []
        for _ in range(self.numFiles):
            filename = self.file.read(int(self.file.read(1).hex(), 16)).decode("utf-8")
            attributesInt = readBits(self.file, 2, 0)
            attributes = (attributesInt >> 1, attributesInt & 1)
            highDir = int.from_bytes(self.file.read(2), byteorder="big")
            offset = int.from_bytes(self.file.read(8), byteorder="big")
            size = int.from_bytes(self.file.read(8), byteorder="big")
            self.files.append(File(filename, FileAttrs(*[bool(attr) for attr in attributes]), highDir, offset, size))

        self.__dataStart: int = self.file.tell()
        self.__dataLen: int = self.fspath.stat().st_size - self.__dataStart

        class DictStructPath(dict):
            def traversalSet(self, path: str, value: Any, *, mode: int = 0) -> None:
                parts: list[str] = [part for part in path.split("/") if part != ""]
                strCode: str = f"self[{int(parts[0]) if mode == 1 else repr(parts[0])}]"
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
                self.file.seek(self.__dataStart + file.offset)
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
                struct.traversalSet(f"{dirPathTable[directory.highDir]}/{directory.name}", (directory, {}), mode=1)
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
                            self.file.seek(self.__dataStart + item.offset)
                            struct.traversalSet(f"{dirPathTable[dirID]}/{item.name}", (item, self.file.read(item.size)), mode=1)
                            continue

                        if isinstance(item, Directory):
                            struct.traversalSet(f"{dirPathTable[dirID]}/{item.name}", (item, {}), mode=1)
                            continue

                    popQueue.append(dirID)

            for dirID in popQueue:
                HighDirTable.pop(dirID)

        for drive in self.drives:
            struct[drive.name] = struct[drive.id]
            struct.pop(drive.id)

        self._struct = deepcopy(struct)
        del struct
        del HighDirTable
        del dirPathTable

        class FSPath:
            def __init__(self, *strPath) -> None:
                self.path: str = "/".join(strPath)
                self.name: str = [part for part in self.path.split("/") if part != ""][-1]
                self.drive: str = self.path.split("/")[0].removesuffix(":")
                self.suffix: str = "." + self.name.split(".")[-1] if "." in self.name else ""
                self.stem: str = self.name[: -len(self.suffix)] if self.suffix else self.name
                self.suffixes: list[str] = [f".{ext}" for ext in self.name.split(".")[1:]] if "." in self.name else []

            def __Obj(pself) -> File | Directory | Drive: # pyright: ignore[reportSelfClsParameterName]
                if pself.is_drive():
                    for drive in self.drives:
                        if drive.name == pself.drive:
                            return drive

                    raise PortableFSPathError("Drive does not exist")

                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(":")}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}'][0]"

                print(checkStr)
                try:
                    result: File | Directory = eval(checkStr, {"__builtins__": None, "struct": self._struct})
                    return result

                except KeyError:
                    raise PortableFSFileNotFoundError(f"path '{pself.path}'")

            def __StructData(pself) -> tuple[File | Directory, bytes | dict] | dict: # pyright: ignore[reportSelfClsParameterName]
                if pself.is_drive():
                    return self._struct[pself.drive]

                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(":")}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}']"

                print(checkStr)
                try:
                    result: tuple[File, bytes] | tuple[Directory, dict] = eval(checkStr, {"__builtins__": None, "struct": self._struct})
                    return result

                except KeyError:
                    raise PortableFSFileNotFoundError(f"path '{pself.path}'")

            def exists(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                if pself.is_drive():
                    return True

                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(":")}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}'][0]"

                print(checkStr)
                try:
                    eval(checkStr, {"__builtins__": None, "struct": self._struct})
                    return True

                except KeyError:
                    return False

            def is_drive(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                drivePattern = rgx.compile(r"^[ABCDEFGHIJKLMNOP]:/?$")
                return bool(drivePattern.match(pself.path))


            def is_file(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(":")}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}'][0]"

                try:
                    result: File | Directory = eval(checkStr, {"__builtins__": None, "struct": self._struct})
                    if isinstance(result, File):
                        return True

                    return False

                except KeyError:
                    return False

            def is_dir(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                if pself.is_drive():
                    return True

                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(":")}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}'][0]"

                try:
                    result: File | Directory = eval(checkStr, {"__builtins__": None, "struct": self._struct})
                    if isinstance(result, Directory):
                        return True

                    return False

                except KeyError:
                    return False

            def iterdir(pself): # pyright: ignore[reportSelfClsParameterName]
                if not pself.is_dir():
                    raise PortableFSPathError("Cannot iterate the contents of a file, or a directory that does not exist.")

                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(":")}']"

                    else:
                        checkStr += f"['{part}'][1]"

                d: dict = eval(checkStr, {"__builtins__": None, "struct": self._struct})
                for filename in d:
                    yield pself.joinpath(filename)

            @property
            def parent(pself): # pyright: ignore[reportSelfClsParameterName]
                dirs: list[str] = [part for part in pself.path.split("/") if part != ""]
                if len(dirs) == 1:
                    raise PortableFSPathError("A Drive Root path has no parent")

                path: str = "/".join(dirs[:-1])
                if not "/" in path:
                    path += "/"

                return FSPath(path)

            def joinpath(pself, *strPath): # pyright: ignore[reportSelfClsParameterName]
                return FSPath(pself.path.removesuffix("/"), *strPath)

            def touch(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if not pself.parent.exists():
                    raise PortableFSPathError("Cannot touch a file if its parent does not exist.")

                path = "/".join([pself.drive] + [part for i, part in enumerate(pself.path.split("/")) if i != 0])

                # For some reason, python mangles 'self.__dataLen' wrong
                self._struct.traversalSet(path, (File(pself.name, FileAttrs(False, False), pself.parent.__Obj().id, self._PortableFS__dataLen, 0), b"")) # pyright: ignore[reportAttributeAccessIssue]

            def mkdir(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if not pself.parent.exists():
                    raise PortableFSPathError("Cannot make a directory if its parent does not exist.")

                path = "/".join([pself.drive] + [part for i, part in enumerate(pself.path.split("/")) if i != 0])

                self._struct.traversalSet(path, (Directory(max([Dir.id for Dir in self.dirs]), pself.name, DirAttrs(False), pself.parent.__Obj().id), {})) # pyright: ignore[reportAttributeAccessIssue]

            def unlink(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if pself.is_drive():
                    raise PortableFSPathError("Cannot unlink a drive")

                if not pself.exists():
                    raise PortableFSPathError("Cannot unlink a file or directory that does not exist")

                d: bytes | dict = pself.parent.__StructData()[1]
                if isinstance(d, dict):
                    d.pop(pself.name)

            def __str__(self) -> str:
                return self.path

            def __repr__(pself) -> str: # pyright: ignore[reportSelfClsParameterName]
                return f"{self.name}: FSPath('{pself.path}')"

        self.Path = FSPath

        def __repr__(self) -> str:
            return f"PortableFS< name: '{self.name} path: '{self.fspath} >"


if __name__ == "__main__":
    pfs = PortableFS(Path("filesysMock2.bin"))
    path = pfs.Path("A:/secrets/secrets.txt")
    print(pfs._struct['A']['secrets'][1]['secrets.txt'])
    print(path.exists())
    print(path.is_file())
    print(path.is_dir())
    print(pfs.Path("A:/").is_dir())
    pfs.Path("A:/hi/").mkdir()
    pfs.Path("A:/hi/index.html").touch()
    for path in pfs.Path("A:/").iterdir():
        print(path)

    print(*[path for path in pfs.Path("A:/hi/").iterdir()], sep="\n")