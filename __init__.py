ver: list[str | int] = [2, 2, 0]

def Version(sep: str = "-") -> str:
    if len(ver) < 4:
        return sep.join([".".join([str(num) for num in ver[0:3]])])

    return sep.join([".".join([str(num) for num in ver[0:3]]), str(ver[3])])

def VerData(sep: str = " - ") -> str:
    return "\n".join([f"Python Interface Version: {Version(sep)}", f"Spec Versions: {", ".join([str(version) for version in PortableFS._VERSIONS])}"])

from pathlib import Path
from typing import BinaryIO, Any, Literal
from copy import deepcopy
from rich.traceback import install ; install()
from dataclasses import dataclass
import re as rgx
from math import ceil
from tqdm import tqdm
from io import BytesIO
import zstandard as zstd

def readBits(stream: BinaryIO, numBits: int, mode: int = 0) -> int:
    numBytes = (numBits + 7) // 8
    data = stream.read(numBytes)
    if len(data) != numBytes:
        raise EOFError(f"Not enough data to read the specified number of bits ({len(data) = }, {numBytes}, {data}, {stream.tell() - numBytes}, {stream.seek(0, 2)}, {stream.tell()})")

    # Mode 0 is for reading bits from the left
    if mode == 0:
        value = int.from_bytes(data, byteorder="big")
        return value >> (numBytes * 8 - numBits)

    # Mode 1 is for reading bits from the right
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
    system: bool

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

class PortableFSFileIOError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"PortableFS FileIO Error: {message}")

class PortableFS:
    _VERSIONS: list[int] = [1,2]
    _DRIVE_CHARS: list[str] = list("ABCDEFGHIJKLMNOP")
    autoSave: bool = False
    chunkSize: int = 80000

    def __init__(self, fspath: Path | BytesIO) -> None:
        if isinstance(fspath, Path):
            self.fspath: Path = fspath
            self.file: BinaryIO = fspath.open("r+b")

        elif isinstance(fspath, BytesIO):
            self.fspath = None # type: ignore
            self.file: BinaryIO = fspath

        self.newfs: bool = False
        self.__closed: bool = False
        if self.file.read(4) != b"pfs0":
            raise ValueError("Not a PortableFS file")

        self.version: int = self.file.read(1)[0]

        if not self.version + 1 in self._VERSIONS:
            raise ValueError(f"Unsupported PortableFS version: Versions {", ".join([str(version) for version in PortableFS._VERSIONS])} only")

        self.compression: bool = False
        self.compressionLevel: int = 0
        if self.version == 1:
            self.compression = readBits(self.file, 1) == 1
            self.file.seek(-1, 1)
            self.compressionLevel = readBits(self.file, 7, 1)

        self.name: str = self.file.read(13).decode("utf-8").rstrip("\x00")
        self.numDrives: int = readBits(self.file, 4, 1)
        self.drives: list[Drive] = []
        for _ in range(self.numDrives):
            drive_name = self._DRIVE_CHARS[readBits(self.file, 4, 0)]
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
            attributesInt = readBits(self.file, 1, 0)
            attrs = (attributesInt & 1,)
            hightDir = int.from_bytes(self.file.read(2), byteorder="big")
            self.dirs.append(Directory(dir_id, dirname, DirAttrs(bool(attrs[0])), hightDir))


        self.numFiles: int = int.from_bytes(self.file.read(3), byteorder="big")
        self.files: list[File] = []
        for _ in range(self.numFiles):
            filename = self.file.read(int(self.file.read(1).hex(), 16)).decode("utf-8")
            attributesInt = readBits(self.file, 3, 0)
            attributes = (attributesInt >> 2, attributesInt >> 1, attributesInt & 1)
            highDir = int.from_bytes(self.file.read(2), byteorder="big")
            offset = int.from_bytes(self.file.read(8), byteorder="big")
            size = int.from_bytes(self.file.read(8), byteorder="big")
            self.files.append(File(filename, FileAttrs(*[bool(attr) for attr in attributes]), highDir, offset, size))

        self.__dataStart: int = self.file.tell()

        if isinstance(self.fspath, Path):
            self.__dataLen: int = self.fspath.stat().st_size - self.__dataStart

        elif self.fspath is None:
            self.__dataLen: int = len(self.file.getbuffer()) - self.__dataStart # type: ignore

        fileData: bytes = self.file.read(self.__dataLen)
        if self.compression and len(fileData) > 0:
            decompressor: zstd.ZstdDecompressor = zstd.ZstdDecompressor()
            fileData: bytes = decompressor.decompress(self.file.read(self.__dataLen))

        class DictStructPath(dict):
            def traversalSet(self, path: str, value: Any, *, mode: int = 0) -> None:
                parts: list[str] = [part for part in path.split("/") if part != ""]
                strCode: str = f"self[{int(parts[0]) if mode == 1 else repr(parts[0])}]"
                for part in parts[1:-1]:
                    strCode += f"['{part}'][1]"

                strCode += f"['{parts[-1]}'] = val"
                exec(strCode, {"__builtins__": None, "self": self, "val": value})

            def traversalGet(self, path: str, *, mode: int = 0) -> dict | tuple[File, bytes] | tuple[Directory, dict]:
                parts: list[str] = [part for part in path.split("/") if part != ""]
                strCode: str = f"self[{int(parts[0]) if mode == 1 else repr(parts[0])}]"
                for part in parts[1:-1]:
                    strCode += f"['{part}'][1]"

                if len(parts) > 1:
                    strCode += f"['{parts[-1]}']"

                return eval(strCode, {"__builtins__": None, "self": self})

            def traversalGetType(self, type: type) -> list:
                def getTypesRec(path: str) -> list:
                    results: list = []
                    struct = self.traversalGet(path)
                    if isinstance(struct, tuple):
                        d = struct[1]

                    else:
                        d = struct

                    if not isinstance(d, dict):
                        raise ValueError("Bad Path")

                    for val in d.values():
                        if isinstance(val[0], type):
                            results.append(val[0])

                        if isinstance(val[0], Directory):
                            results.extend(getTypesRec("/".join([path, val[0].name])))

                    return results

                results: list = []
                for name, item in self.items():
                    idk = getTypesRec(name)
                    results.extend(idk)

                return results

        self.__strCls = DictStructPath
        def sortModeHighDir(obj: File | Directory):
            return obj.highDir

        self.files.sort(key=sortModeHighDir)
        self.dirs.sort(key=sortModeHighDir)

        struct: DictStructPath = DictStructPath({})
        HighDirTable: dict[int, list[File | Directory]] = {}
        dirPathTable: dict[int, str] = {}

        for drive in self.drives:
            struct[drive.id] = {}

        for file in self.files:
            if file.highDir <= 0x0F:
                struct[file.highDir][file.name] = (file, fileData[file.offset:file.offset + file.size])
                continue

            if not file.highDir in HighDirTable.keys():
                HighDirTable[file.highDir] = [file]

            else:
                HighDirTable[file.highDir].append(file)


        for directory in self.dirs:
            if directory.highDir <= 0x0F:
                struct[directory.highDir][directory.name] = (directory, {})
                dirPathTable[directory.id] = f"{directory.highDir}/{directory.name}"
                if directory.id in HighDirTable.keys():
                    for item in HighDirTable[directory.id]:
                        if isinstance(item, File):
                            struct.traversalSet(f"{dirPathTable[directory.id]}/{item.name}", (item, fileData[item.offset:item.offset + item.size]), mode=1)
                            continue

                        if isinstance(item, Directory):
                            struct.traversalSet(f"{dirPathTable[directory.id]}/{item.name}", (item, {}), mode=1)
                            continue

                    HighDirTable.pop(directory.id)

                continue

            if directory.highDir in dirPathTable.keys():
                struct.traversalSet(f"{dirPathTable[directory.highDir]}/{directory.name}", (directory, {}), mode=1)
                dirPathTable[directory.id] = f"{dirPathTable[directory.highDir]}/{directory.name}"
                if directory.id in HighDirTable.keys():
                    for item in HighDirTable[directory.id]:
                        if isinstance(item, File):
                            struct.traversalSet(f"{dirPathTable[directory.id]}/{item.name}", (item, fileData[item.offset:item.offset + item.size]), mode=1)
                            continue

                        if isinstance(item, Directory):
                            struct.traversalSet(f"{dirPathTable[directory.id]}/{item.name}", (item, {}), mode=1)
                            continue

                    HighDirTable.pop(directory.id)

                continue

            if not directory.highDir in HighDirTable.keys():
                HighDirTable[directory.highDir] = [directory]

            else:
                HighDirTable[directory.highDir].append(directory)

        lastLen: int = 0
        lenCount: int = 0
        while len(HighDirTable) > 0:
            if len(HighDirTable) != lastLen:
                lastLen = len(HighDirTable)
                lenCount = 0

            else:
                lenCount += 1

            if lenCount > 50:
                print("\n" + str(list(HighDirTable.keys())))
                print(list(set([[dir for dir in self.dirs if item.highDir == dir.id][0].highDir for waiting in HighDirTable.values() for item in waiting])))
                raise PortableFSEncodingError("PassingCantPlace")

            popQueue: list[int] = []
            for dirID, items in HighDirTable.items():
                if isinstance(items, str):
                    continue

                if dirID in dirPathTable.keys():
                    for item in items:
                        if isinstance(item, File):
                            struct.traversalSet(f"{dirPathTable[dirID]}/{item.name}", (item, fileData[item.offset:item.offset + item.size]), mode=1)
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
        self.file.close()
        del HighDirTable
        del dirPathTable

        class FSFileIO:
            defaultLineSequence: Literal['CR', 'CRLF']
            ENCODINGS: list[str | None] = [None, 'ascii', 'utf-8', 'utf-16']

            @staticmethod
            def is_mode(mode: str) -> bool:
                modeRgx = rgx.compile(r'^[rwb+ta]*$')
                return bool(modeRgx.match(mode))

            def __init__(fself, pathStr: str, mode: str = "rt", encoding: Literal[None, 'ascii', 'utf-8', 'utf-16'] = 'utf-8') -> None: # pyright: ignore[reportSelfClsParameterName]
                if not FSFileIO.is_mode(mode):
                    raise PortableFSFileIOError("Invalid Mode")

                if not encoding in FSFileIO.ENCODINGS:
                    raise PortableFSFileIOError("Invalid Encoding")

                fself.__pos: int = 0
                fself.__mode: str = mode
                fself.__path: str = pathStr
                fself.__data: bytes = self._struct.traversalGet(pathStr)[1] # pyright: ignore[reportAttributeAccessIssue]
                fself.__obj: File = self._struct.traversalGet(pathStr)[0] # pyright: ignore[reportAttributeAccessIssue]
                fself.__enc: Literal[None, 'ascii', 'utf-8', 'utf-16'] = encoding
                fself.__closed: bool = False
                if not isinstance(fself.__data, bytes):
                    raise PortableFSFileIOError("Invalid path")

            def truncate(self) -> None:
                self.__data = bytes()

            def __check_closed(self) -> None:
                if self.__closed:
                    raise ValueError("File I/O operation was done on a closed file")

            def close(self) -> None:
                self.flush()
                self.__closed = True

            def flush(fself) -> None: # pyright: ignore[reportSelfClsParameterName]
                fself.__check_closed()
                if not fself.__obj.attributes.readOnly:
                    raise PortableFSFileIOError("Cannot write to a read-only file")

                if fself.__obj.attributes.system:
                    raise PortableFSFileIOError("Cannot write to a system file")

                self._struct.traversalSet(fself.__path, (self._struct.traversalGet(fself.__path)[0], fself.__data))

            def readable(self) -> bool:
                self.__check_closed()
                return "r" in self.__mode or "+" in self.__mode

            def writable(self) -> bool:
                self.__check_closed()
                return "w" in self.__mode or "+" in self.__mode or "a" in self.__mode

            def write(self, data: str | bytes) -> None:
                self.__check_closed()
                if not self.writable():
                    raise PortableFSFileIOError("Cannot write to a file when not in write mode")

                if not self.__obj.attributes.readOnly:
                    raise PortableFSFileIOError("Cannot write to a read-only file")

                if self.__obj.attributes.system:
                    raise PortableFSFileIOError("Cannot write to a system file")

                binMode: bool = 'b' in self.__mode

                if binMode and isinstance(data, str):
                    raise PortableFSFileIOError("Cannot write a string in bytes mode")

                if not binMode and isinstance(data, bytes):
                    raise PortableFSFileIOError("Cannot write bytes in text mode")

                if binMode:
                    if "a" in self.__mode:
                        self.__data += data # pyright: ignore[reportOperatorIssue]
                        return

                    self.__data = data # pyright: ignore[reportAttributeAccessIssue]
                    return

                if "a" in self.__mode:
                    self.__data += bytes(data, self.__enc) # pyright: ignore[reportArgumentType]
                    return

                self.__data += bytes(data, self.__enc) # pyright: ignore[reportArgumentType]

            def read(self, num: int = -1) -> str | bytes:
                self.__check_closed()
                if not self.readable():
                    raise PortableFSFileIOError("Cannot read a file when not in read mode")

                if 'b' in self.__mode:
                    if num > 0:
                        pos: int = self.__pos
                        self.__pos += num
                        return self.__data[pos:min(num, len(self.__data))]

                if 'b' in self.__mode:
                    if num > 0:
                        pos: int = self.__pos
                        self.__pos += num
                        return self.__data[pos:min(num, len(self.__data))]

                    return self.__data[self.__pos:]

                enc: str | None = self.__enc
                if enc is None:
                    self.__mode += 'b'
                    if num > 0:
                        pos: int = self.__pos
                        self.__pos += num
                        return self.__data[pos:min(num, len(self.__data))]

                    return self.__data[self.__pos:]

                if num > 0:
                    pos: int = self.__pos
                    self.__pos += num
                    return self.__data[self.__pos:min(num, len(self.__data))].decode(enc)

                return self.__data[self.__pos:].decode(enc)

            def tell(self) -> int:
                self.__check_closed()
                return self.__pos

            def seek(self, num: int, mode: int = 0) -> None:
                self.__check_closed()
                match mode:
                    case 0:
                        self.__pos = num

                    case 1:
                        self.__pos += num

                    case 2:
                        self.__pos = len(self.__data) - (1 + num)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb) -> None:
                self.close()

        class FSPath:
            _cwd = f"{self.drives[0].name}:/" if len(self.drives) > 0 else None

            def __init__(pself, *strPath: str) -> None: # pyright: ignore[reportSelfClsParameterName]
                self._check_closed()
                pself.path: str = ((FSPath._cwd or "") if strPath[0].split("/")[0].removesuffix(":") in [drive.name for drive in self.drives] else "") + "/".join(strPath)
                pself.name: str = [part for part in pself.path.split("/") if part != ""][-1]
                pself.drive: str = pself.path.split("/")[0].removesuffix(":")
                pself.suffix: str = "." + pself.name.split(".")[-1] if "." in pself.name else ""
                pself.stem: str = pself.name[: -len(pself.suffix)] if pself.suffix else pself.name
                pself.suffixes: list[str] = [f".{ext}" for ext in pself.name.split(".")[1:]] if "." in pself.name else []

            @property
            def cwd(self) -> "FSPath":
                if FSPath._cwd is None:
                    raise PortableFSPathError("No current working directory, as there are no drives in this filesystem")

                return FSPath()

            def chdir(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if not pself.is_dir():
                    raise PortableFSPathError("Current working directory can only be set to a directory")

                FSPath._cwd = pself.resolve().path

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
                        checkStr += f"['{part.removesuffix(':')}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}'][0]"

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
                        checkStr += f"['{part.removesuffix(':')}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}']"

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
                        checkStr += f"['{part.removesuffix(':')}']"

                    elif i < len(parts) - 1:
                        checkStr += f"['{part}'][1]"

                    else:
                        checkStr += f"['{part}'][0]"

                try:
                    eval(checkStr, {"__builtins__": None, "struct": self._struct})
                    return True

                except KeyError:
                    return False

            @property
            def readonly(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                obj: File | Directory | Drive = pself.__Obj()
                if isinstance(obj, Drive):
                    raise PortableFSPathError("Drive paths do not have a read-only attribute")

                elif isinstance(obj, Directory):
                    raise PortableFSPathError("Directory paths do not have a read-only attribute")

                elif isinstance(obj, File):
                    return obj.attributes.readOnly

            @readonly.setter
            def readonly(pself, value: bool) -> None: # pyright: ignore
                obj: File | Directory | Drive = pself.__Obj()
                if isinstance(obj, Drive):
                    raise PortableFSPathError("Drive paths do not have a read-only attribute")

                elif isinstance(obj, Directory):
                    raise PortableFSPathError("Directory paths do not have a read-only attribute")

                elif isinstance(obj, File):
                    obj.attributes.readOnly = value

            @property
            def hidden(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                obj: File | Directory | Drive = pself.__Obj()
                if isinstance(obj, Drive):
                    raise PortableFSPathError("Drive paths do not have a hidden attribute")

                elif isinstance(obj, Directory):
                    return obj.attributes.hidden

                elif isinstance(obj, File):
                    return obj.attributes.hidden

            @hidden.setter
            def hidden(pself, value: bool) -> None: # pyright: ignore
                obj: File | Directory | Drive = pself.__Obj()
                if isinstance(obj, Drive):
                    raise PortableFSPathError("Drive paths do not have a hidden attribute")

                elif isinstance(obj, Directory):
                    obj.attributes.hidden = value

                elif isinstance(obj, File):
                    obj.attributes.hidden = value

            @property
            def system(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                obj: File | Directory | Drive = pself.__Obj()
                if isinstance(obj, Drive):
                    raise PortableFSPathError("Drive paths do not have a system attribute")

                elif isinstance(obj, Directory):
                    raise PortableFSPathError("Directory paths do not have a system attribute")

                elif isinstance(obj, File):
                    return obj.attributes.system


            def is_absolute(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                for part in pself.path.split("/"):
                    if part == "..":
                        return False

                else:
                    return True

            def is_drive(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                drivePattern = rgx.compile(r"^[ABCDEFGHIJKLMNOP]:/?$")
                return bool(drivePattern.match(pself.path))

            def is_file(pself) -> bool: # pyright: ignore[reportSelfClsParameterName]
                checkStr: str = "struct"
                parts: list[str] = [part for part in pself.path.split("/") if part != ""]
                for i, part in enumerate(parts):
                    if i == 0:
                        checkStr += f"['{part.removesuffix(':')}']"

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
                        checkStr += f"['{part.removesuffix(':')}']"

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
                        checkStr += f"['{part.removesuffix(':')}']"

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

            def resolve(pself): # pyright: ignore[reportSelfClsParameterName]
                if not pself.is_drive():
                    raise PortableFSPathError("Cannot resolve a path that is not a drive root.")

                resParts: list[str] = []
                for part in pself.path.split("/"):
                    match part:
                        case "" | ".":
                            continue

                        case "..":
                            if len(resParts) <= 1:
                                raise PortableFSPathError("Cannot resolve a path that goes above the root")

                            resParts.pop()

                        case _:
                            resParts.append(part)

                return FSPath("/".join(resParts))

            def touch(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if not pself.parent.exists():
                    raise PortableFSPathError("Cannot touch a file if its parent does not exist.")

                path = "/".join([pself.drive] + [part for i, part in enumerate(pself.path.split("/")) if i != 0])

                # For some reason, python mangles 'self.__dataLen' wrong
                self._struct.traversalSet(path, (File(pself.name, FileAttrs(False, False, False), pself.parent.__Obj().id, self._PortableFS__dataLen, 0), b"")) # pyright: ignore[reportAttributeAccessIssue]

            def mkdir(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if not pself.parent.exists():
                    raise PortableFSPathError("Cannot make a directory if its parent does not exist.")

                path = "/".join([pself.drive] + [part for i, part in enumerate(pself.path.split("/")) if i != 0])

                self._struct.traversalSet(path, (Directory(max([Dir.id for Dir in self._struct.traversalGetType(Directory)] + [15]) + 1, pself.name, DirAttrs(False), pself.parent.__Obj().id), {})) # pyright: ignore[reportAttributeAccessIssue]

            def unlink(pself) -> None: # pyright: ignore[reportSelfClsParameterName]
                if pself.is_drive():
                    raise PortableFSPathError("Cannot unlink a drive")

                if not pself.exists():
                    raise PortableFSPathError("Cannot unlink a file or directory that does not exist")

                if pself.is_file() and pself.system:
                    raise PortableFSPathError("Cannot unlink a system file")

                d: bytes | dict = pself.parent.__StructData()[1]
                if isinstance(d, dict):
                    d.pop(pself.name)

            def open(pself, mode: str = 'rt', encoding: Literal['ascii', 'utf-8', 'utf-16'] = 'utf-8', newline: Literal['CRLF', 'LF'] = 'LF') -> FSFileIO: # pyright: ignore[reportSelfClsParameterName]
                if not FSFileIO.is_mode(mode):
                    raise PortableFSFileIOError(f"'{mode}' is not a valid mode.")

                if not encoding in FSFileIO.ENCODINGS:
                    raise PortableFSFileIOError(f"'{encoding}' is not a valid encoding, can be 'ascii', 'utf-8', or 'utf-16'.")

                return FSFileIO("/".join([part.removesuffix(":") if i == 0 else part for i, part in enumerate(pself.path.split("/"))]), mode, encoding)

            def __str__(self) -> str:
                return self.path

            def __repr__(pself) -> str: # pyright: ignore[reportSelfClsParameterName]
                return f"{self.name}: FSPath('{pself.path}')"

        self.Path = FSPath

    def addDrive(self, name: str) -> None:
        if len(name) != 1 or not name in self._DRIVE_CHARS:
            raise ValueError("Drive name must be a single character from A to P")

        if name in [drive.name for drive in self.drives]:
            raise ValueError(f"Drive '{name}' already exists")

        newID: int = 0
        for drive in self.drives:
            if drive.id > newID:
                newID = drive.id

        newID += 1
        if newID >= 16:
            raise ValueError("Cannot have more than 16 drives in a PortableFS")

        self.drives.append(Drive(name, newID))
        self._struct[name] = {}

    def removeDrive(self, name: str) -> None:
        if name not in [drive.name for drive in self.drives]:
            raise ValueError(f"Drive '{name}' does not exist")

        for i, drive in enumerate(self.drives):
            if drive.name == name:
                self.drives.pop(i)
                self._struct.pop(name)
                return

    def __repr__(self) -> str:
        return f"PortableFS< name: '{self.name} path: '{self.fspath} >"

    def close(self) -> None:
        if PortableFS.autoSave and not self.newfs:
            self.save()

        self.__closed = True
        self._struct = self.__strCls({})

    def _check_closed(self) -> None:
        if self.__closed:
            raise ValueError("Cannot interact with a closed file")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def save(self, path: Path | None = None, retIO: bool = False, compression: bool | int | None = None, log: bool = True, logChunkCompilation: bool = True) -> None | BytesIO:
        if (path is None and self.fspath is None) and (not retIO):
            raise ValueError("Cannot save a PortableFS with no path specified when it was initialized from a BytesIO")

        def fixedBytesLength(bytesObj: bytes, length: int, fill: bytes = b'\x00') -> bytes:
            if len(bytesObj) < length:
                return bytesObj + fill*(length - len(bytesObj))

            elif len(bytesObj) == length:
                return bytesObj

            elif len(bytesObj) > length:
                return bytes(bytearray(bytesObj)[0:length])

            else:
                raise ValueError()

        def indexOffset(data: list[bytes], startItemIdx: int) -> int:
            result: int = 0
            for i, item in enumerate(data):
                if i == startItemIdx:
                    return result

                result += len(item)

            return result

        def flattenStructRec(dirContents: dict[str, tuple[File, bytes] | tuple[Directory, dict]], *, recursing: bool = False) -> tuple[list[File], list[Directory], list[bytes]]:
            files, dirs, data = [], [], []
            for name, val in dirContents.items():
                if isinstance(val[0], File):
                    if log: print(f"\r\x1b[90mSaving file '{name}'\x1b[0m", end="", flush=True)
                    file: File = val[0]
                    file.name = name
                    file.size = len(val[1])
                    data.append(val[1])
                    files.append(file)
                    continue

                if isinstance(val[0], Directory):
                    folder: Directory = val[0]
                    folder.name = name
                    dirs.append(folder)
                    recFiles, recDirs, recData = flattenStructRec(val[1], recursing=False) # type: ignore
                    files.extend(recFiles)
                    dirs.extend(recDirs)
                    data.extend(recData)
                    continue

            # Remove the offset setting here
            return files, dirs, data

        if len(self.name) > 13:
            raise PortableFSEncodingError("Cannot save a pfs for spec v1 with a name of greater that 13 chars.")

        data: bytearray = bytearray(b"pfs0")
        compressing: bool = compression if isinstance(compression, bool) else True if isinstance(compression, int) else self.compression
        compressionLevel: int = 0 if not compressing else compression if isinstance(compression, int) else 10 if isinstance(compression, bool) else self.compressionLevel
        data.extend(bytes([self.version if not compressing else 1]) + bytes([(int(compressing) << 7) | compressionLevel]) + fixedBytesLength(self.name.encode(), 13) + bytes([len(self.drives)]))
        files: list[File] = []
        dirs: list[Directory] = []
        data_list: list[bytes] = []
        for drive in self.drives:
            data.extend(bytes([(PortableFS._DRIVE_CHARS.index(drive.name) << 4) + drive.id]))
            if log: print(f"\r\x1b[90mSaving Files From drive '{drive.name}'\x1b[0m", end="", flush=True)
            dfiles, ddirs, ddata = flattenStructRec(self._struct[drive.name], recursing=False)
            files.extend(dfiles)
            dirs.extend(ddirs)
            data_list.extend(ddata)

        # Set offsets globally
        for i, file in enumerate(files):
            file.offset = indexOffset(data_list, i)

        fileData = bytearray().join(data_list)

        if len(dirs).bit_length() > 15:
            PortableFSEncodingError("Cannot save a pfs for spec v1 with the total amount of directories larger than 2^15")

        if len(files).bit_length() > 24:
            PortableFSEncodingError("Cannot save a pfs for spec v1 with the total amount of files larger than 2^24")

        data.extend(len(dirs).to_bytes(2, byteorder="big"))
        for directory in dirs:
            if directory.id.bit_length() > 15:
                PortableFSEncodingError("Cannot save a pfs for spec v1 with a directory ID larger than 2^15")

            if log: print(f"\r\x1b[90mSaving dir '{directory.name}'\x1b[0m", end="", flush=True)
            data.extend(directory.id.to_bytes(2, byteorder="big"))
            data.extend(len(directory.name).to_bytes(byteorder="big"))
            data.extend(bytes(directory.name, 'utf-8'))
            data.extend(bytes([(int(directory.attributes.hidden) << 7)]))
            data.extend(directory.highDir.to_bytes(2, byteorder="big"))

        data.extend(len(files).to_bytes(3, byteorder="big"))
        for file in files:
            if log: print(f"\r\x1b[90mSaving filedata of file {file.name}\x1b[0m", end="", flush=True)
            data.extend(len(file.name).to_bytes(byteorder="big"))
            data.extend(bytes(file.name, "utf-8"))
            data.extend(bytes([(int(file.attributes.readOnly) << 7) | (int(file.attributes.hidden) << 6) | (int(file.attributes.system) << 5)]))
            data.extend(file.highDir.to_bytes(2, byteorder="big"))
            data.extend(file.offset.to_bytes(8, byteorder="big"))
            data.extend(file.size.to_bytes(8, byteorder="big"))

        if log: print(f"\r\x1b[90mCompiling data\x1b[0m", end="", flush=True)

        if compressing:
            compressor = zstd.ZstdCompressor(level=compressionLevel)
            fileData = compressor.compress(fileData)

        if not len(fileData) > PortableFS.chunkSize:
            if log: print(f"\r\x1b[90mSaving data\x1b[0m", end="", flush=True)
            data.extend(fileData)

        else:
            if log: print(f"\r\x1b[90mSaving data as chunks\x1b[0m", end="", flush=True)
            dataChunks: list[bytes] = [fileData[0 + (i * PortableFS.chunkSize):PortableFS.chunkSize + (i * PortableFS.chunkSize)] for i in range(ceil(len(fileData) / PortableFS.chunkSize))]
            cachedLen: int = len(dataChunks)
            if log: print(f"\r\x1b[90mSaving {cachedLen} chunks\x1b[0m", end="", flush=True)
            if logChunkCompilation:
                for chunk in tqdm(dataChunks, desc="Compiling chunks"):
                    data.extend(chunk)

            else:
                for chunk in dataChunks:
                    data.extend(chunk)

        if log: print(f"\r\x1b[90mCompiled Data\x1b[0m")
        if retIO:
            return BytesIO(data)

        else:
            svpath = self.fspath if path is None else path
            if not svpath.exists():
                svpath.touch()

            with svpath.open("wb") as file:
                file.write(data)

    @staticmethod
    def new(name: str, drives: list[str]):
        if len(name) > 13:
            raise ValueError("Name cannot be greater than 13 characters")

        if len(drives) > 16:
            raise ValueError("Can only have 16 drives")

        for drive in drives:
            if not drive in PortableFS._DRIVE_CHARS:
                raise ValueError("Drives can only be named A-P")

            if drives.count(drive) >= 2:
                raise ValueError("Drive names must be unique")

        def fixedBytesLength(bytesObj: bytes, length: int, fill: bytes = b'\x00') -> bytes:
            if len(bytesObj) < length:
                return bytesObj + fill*(length - len(bytesObj))

            elif len(bytesObj) == length:
                return bytesObj

            elif len(bytesObj) > length:
                return bytes(bytearray(bytesObj)[0:length])

            else:
                raise ValueError()

        import os
        if os.name == "nt":
            tmpPath: Path = Path.home().joinpath("Appdata/Local/Temp/pfsntmplte")

            if not tmpPath.exists():
                tmpPath.touch()

            driveData: bytes = bytes([len(drives)])
            for i, drive in enumerate(drives):
                driveData += bytes([(PortableFS._DRIVE_CHARS.index(drive) << 4) | i])

            with tmpPath.open("wb") as file:
                file.write(bytes("pfs0", "utf-8") + bytes([1,137]) + fixedBytesLength(bytes(name, "utf-8"), 13) + driveData + bytes([0, 0, 0, 0, 0]))

            pfs: PortableFS = PortableFS(tmpPath)
            pfs.newfs = True
            tmpPath.unlink()
            return pfs

        elif os.name == "posix":
            tmpPath: Path = Path.cwd().joinpath(".new.pfs")

            if not tmpPath.exists():
                tmpPath.touch()

            driveData: bytes = bytes([len(drives)])
            for i, drive in enumerate(drives):
                driveData += bytes([(PortableFS._DRIVE_CHARS.index(drive) << 4) | i])

            with tmpPath.open("wb") as file:
                file.write(bytes("pfs0", "utf-8") + bytes([1,137]) + fixedBytesLength(bytes(name, "utf-8"), 13) + driveData + bytes([0, 0, 0, 0, 0]))

            pfs: PortableFS = PortableFS(tmpPath)
            pfs.newfs = True
            tmpPath.unlink()
            return pfs