version = [1, 0, 0]
VERSION = ".".join([str(num) for num in version])

from pathlib import Path
import atexit
from typing import Literal
import re
import json

def defaultDictKeys(keys: dict, **dictionary) -> dict:
    for key, default in keys.items():
        try:
            dictionary[key]
        except KeyError:
            dictionary[key] = default

    return dictionary

def flatten(l : list) -> list:
    newList : list = []
    for item in l:
        if not isinstance(item, list):
            newList.append(item)
        else:
            for extraItem in flatten(item):
                newList.append(extraItem)
    return newList

def fixedBytesLength(bytesObj: bytes, length: int, fill: bytes = bytes(b'\x00')) -> bytes:
    if len(bytesObj) < length:
        return bytesObj + fill*(length - len(bytesObj))
    elif len(bytesObj) == length:
        return bytesObj
    elif len(bytesObj) > length:
        return bytes(bytearray(bytesObj)[0:length])

class FilesystemFile:

    def __init__(self, byteData: bytes | None, filedata: dict | None, metadata: dict | None, streamData: dict | None) -> None:
        self.bytes = byteData
        self.files = filedata
        self.metadata = metadata
        self.streamdata = streamData

    def __repr__(self) -> str:
        return f'<Bytes: {self.bytes}, Files: {self.files}, Metadata: {self.metadata}, Stream Data: {self.streamdata}>'

class PortableFilesystem:

#    def killIfClosed(func):
#        def killCheck(instance, *args, **kwargs):
#            if instance.__closed__ == True:
#                instance = None
#                del instance
#                return None
#
#            return func(*args, **kwargs)
#
#        return killCheck

    registry: dict = {}

    def __init__(self, filepath: Path):
        self.__closed__ = False
        self.filepath = filepath
        PortableFilesystem.registry[str(filepath.absolute())] = self
        self.file = filepath.open("rb")
        self.version = int(self.file.read(1).hex(), 16) + 1
        self.compressionVer = int(self.file.read(1).hex(), 16)
        self.name = str(self.file.read(13), "ascii")
        self.file.seek(1, 1)

        def getDrives() -> tuple[dict[str:str], dict[str: int]]:
            drives = {}
            drivesAttributes = {}
            while True:
                driveID = self.file.read(1).hex()
                driveName = str(self.file.read(13).strip(b"\x00"), "ascii")
                driveAttributes = int(self.file.read(2).hex(), 16)
                drives[driveName] = driveID
                drivesAttributes[driveID] = driveAttributes
                if self.file.read(2) == b"\x00\x00":
                    break
                else:
                    self.file.seek(-2, 1)
            return (drives, drivesAttributes)

        self.driveLookup, self.driveAttributesLookup = getDrives()

        def getFile(start: int | None = None, end: int | None = None) -> tuple[str, bytes]:
            if start != None:
                self.file.seek(start)
            name = bytearray()
            while True:
                byte = self.file.read(1)
                if end != None and byte == b'\x9D':
                    continue
                if not byte or byte == b'\x00' or (end != None and self.file.tell() == end):
                    if not byte or (end != None and self.file.tell() == end):
                        return None
                    name = str(name, "ascii")
                    break
                name.append(int(byte.hex(), 16))

            attrStart = self.file.tell()

            def getFileAttributes() -> bytearray:
                text = bytearray()
                Escaped = False
                while True:
                    byte = self.file.read(1)
                    if byte == b"\x00":
                        if not Escaped:
                            break

                        else:
                            Escaped = False

                    elif byte == b'\x9D':
                        Escaped = True

                    elif Escaped:
                        Escaped = False

                    elif not byte or (end != None and self.file.tell() == end):
                        break

                    text.append(int(byte.hex(), 16))
                return text

            def parseFileAttributes(attributes: bytearray) -> dict:
                attrEnd = self.file.tell()
                parsedAttributes: dict[str: bytearray] = {}
                InAttr = False
                curAttr = ''
                Escaped = False
                isNum = False
                num = 0
                for idx, byte in enumerate([bytes([num]) for num in attributes]):
                    if not isNum:
                        if not InAttr:
                            if b'\x62\x6D\x66\x3B'.__contains__(byte):
                                if byte == b'\x66':
                                    startIdx = idx
                                    dirStart = attrStart + (idx + 1) + 1
                                    isNum = True
                                curAttr = str(byte, "ascii")

                            elif byte == b'\xFF' and curAttr != '':
                                InAttr = True
                        else:
                            if byte == b'\xAF':
                                if not Escaped:
                                    InAttr = False
                                    continue
                                else:
                                    Escaped = False
                            elif byte == b'\x9D':
                                Escaped = True

                            elif Escaped:
                                try:
                                    parsedAttributes[curAttr]
                                except KeyError:
                                    parsedAttributes[curAttr] = bytearray()
                                parsedAttributes[curAttr].append(int(byte.hex(), 16))
                                Escaped = False

                            try:
                                parsedAttributes[curAttr]
                            except KeyError:
                                parsedAttributes[curAttr] = bytearray()
                            parsedAttributes[curAttr].append(int(byte.hex(), 16))
                    else:
                        if byte == b'\x9D':
                            dirStart += idx - (startIdx + 1)
                            isNum = False
                            continue

                        num += int(byte.hex(), 16)

                if parsedAttributes.__contains__('b') and parsedAttributes.__contains__('f'):
                    raise ValueError("PortableFilesystemError: a file cannot be both a normal file and a directory")

                if parsedAttributes.__contains__('b'): parsedAttributes['b'] = bytes(parsedAttributes["b"])
                if parsedAttributes.__contains__('m'): parsedAttributes["m"] = json.loads(str(parsedAttributes["m"], 'ascii'))

                if num != 0:
                    self.file.seek(dirStart)
                    parsedAttributes['f'] = {}
                    while True:
                        file = getFile(None, dirStart + num)
                        if file == None:
                            break
                        parsedAttributes['f'][file[0]] = file[1]
                    parsedAttributes['b'] = None
                    parsedAttributes['f'] = {k:v for k,v in parsedAttributes['f'].items() if k != ''}
                    self.file.seek(attrEnd)

                return parsedAttributes

            fileAttributes = defaultDictKeys({'b': None, "m": None, ';': None, 'f': None}, **parseFileAttributes(getFileAttributes()))
            return (name, FilesystemFile(fileAttributes['b'], fileAttributes['f'], fileAttributes['m'], fileAttributes[';']))

        self._fileSystemLookup = {drive: {} for drive in self.driveLookup.values()}

        curDrive = list(self.driveLookup.values())[0]
        while True:
            file = getFile()
            if file == None:
                break
            self._fileSystemLookup[curDrive][file[0]] = file[1]
            red = self.file.read(1)
            if red == b'\x00':
                curDrive = list(self.driveLookup.values())[list(self.driveLookup.values()).index(curDrive) + 1]
            else:
                self.file.seek(-1, 1)

        class FSFileIOError(Exception):

            def __init__(self, message: str) -> None:
                super().__init__(f'FilesystemFileIOError: {message}')

        class FSFileIO:

            def __init__(self, file: FilesystemFile, mode: str = 'r', encoding: Literal['ascii', 'utf-8', 'utf-16'] = 'ascii') -> None:
                if not isinstance(file, FilesystemFile):
                    raise FSFileIOError(f"File object is not a FilesystemFile object")

                modePattern = re.compile(r"^[rbw]*$")
                if not modePattern.match(mode):
                    raise FSFileIOError(f"Mode '{mode}' is invalid")

                encodings = ['ascii', 'utf-8', 'utf-16']
                if not encodings.__contains__(encoding.lower()):
                    raise FSFileIOError(f"Encoding '{encoding}' is invalid")

                self._pos = 0
                self._mode = mode
                self._file = file
                self._value = file.bytes
                self._encoding = encoding

            def close(self) -> None:
                self.flush()
                self = 0
                del self

            def readable(self) -> bool:
                return self._mode.__contains__("r")

            def writable(self) -> bool:
                return self._mode.__contains__("w")

            def write(self, data: str | bytes, flush: bool = False) -> None:
                if not self.writable():
                    raise FSFileIOError("Does not have permissions to write to this file")

                if self._mode.__contains__('b') and not isinstance(data, bytes):
                    raise ValueError('Cannot write to a file in bytes mode with a non-bytes object')

                if (not self._mode.__contains__('b')) and not isinstance(data, str):
                    raise ValueError("Cannot write to a file in text mode with a non-str object")

                match self._mode.__contains__('b'):
                    case True:
                        self._value = data

                    case False:
                        self._value = bytes(data, self._encoding)

                if flush: self.flush()

            def flush(self) -> None:
                self._file.bytes = self._value

            def read(self, size: int | None = None) -> bytes | str | None:
                if not self.readable():
                    raise FSFileIOError("Does not have permission to read from this file")

                if size == None:
                    return self._file.bytes if self._mode.__contains__('b') else str(self._file.bytes, self._encoding)

                try:
                    return bytes(bytearray(self._file.bytes)[self._pos:self._pos + size]) if self._mode.__contains__('b') else str(bytes(bytearray(self._file.bytes)[self._pos:self._pos + size]), self._encoding)
                except Exception:
                    return None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.close()

        class FSPathError(Exception):

            def __init__(self, message: str) -> None:
                super().__init__(f"FilesystemPathError: {message}")

        def changePathToID(path: str) -> str:
                parts = path.split('/', 1)
                if self.driveLookup.get(parts[0].removesuffix(':')) != None:
                    parts[0] = self.driveLookup[parts[0].removesuffix(":")] + ':'
                else:
                    validDriveParts = flatten([[name, ID] for name, ID in self.driveLookup.items()])
                    if not validDriveParts.__contains__(parts[0].removesuffix(":")):
                        raise FSPathError(f"There is no drive or drive ID of '{parts[0].removesuffix(':')}'")
                return '/'.join(parts)

        def changePathToName(path: str) -> str:
                parts = path.split('/', 1)
                if list(self.driveLookup.values()).__contains__(parts[0].removesuffix(':')):
                    parts[0] = list(self.driveLookup.keys())[list(self.driveLookup.values()).index(parts[0].removesuffix(':'))] + ':'
                return '/'.join(parts)

        class FSPath:
            pwd = f'{list(self.driveLookup.keys())[0]}:/'

            def __init__(self, *pathArgs: str, absolute: bool = False) -> None:
                absPattern = re.compile(r'^[a-zA-Z0123456789]*:/')
                if absPattern.match('/'.join(pathArgs)):
                    absolute = True

                if absolute:
                    self.path = changePathToID('/'.join(pathArgs))

                else:
                    self.path = changePathToID(FSPath.pwd + '/'.join(pathArgs))

                def parsePath(path: str):
                    result = path.split("/")
                    result[0] = result[0].removesuffix(':')
                    if result[-1] == '':
                        result = result[0:-1]
                    return result

                self._parsedPath = parsePath(self.path)

                self.driveName = changePathToName(self.path).split('/', 1)[0].removesuffix(':')
                self.driveID = self.path.split('/', 1)[0].removesuffix(':')

                self.name = self.path.split("/")[-1]
                self.suffix = f'.{self.name.split('.')[-1]}'
                self.suffixes = [f".{suffix}" for suffix in self.name.split('.')[1::]]
                self.stem = self.name.split('.', 1)[0]

            @property
            def parent(self):
                return FSPath(self.path.removesuffix(f"/{self.name}"), absolute=True)

            @staticmethod
            def cwd():
                return FSPath()

            def exists(pself) -> bool:
                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"

                try:
                    eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup})
                    return True
                except KeyError:
                    return False

            def is_file(pself) -> bool:
                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"
                checkStr += '.bytes != None'

                try:
                    return eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup})
                except KeyError:
                    return False

            def is_dir(pself) -> bool:
                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"

                try:
                    obj = eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup})
                    if isinstance(obj, dict):
                        return True

                    return obj.files != None
                except KeyError:
                    return False

            def iterdir(pself):
                if not pself.is_dir():
                    raise FSPathError('Cannot iterate a file or a path that does not exist')

                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"

                obj = eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup})
                if isinstance(obj, FilesystemFile):
                    obj = obj.files

                for filename in obj.keys():
                    yield pself.joinpath(filename)

            def joinpath(self, *pathArgs: str):
                return FSPath(self.path + ("/" if not self.path.endswith('/') else '') + "/".join(pathArgs), absolute=True)

            def chcwd(self) -> None:
                if (not self.exists()) or self.is_file():
                    raise FSPathError('Cannot change current working directory to a file or a path that does not exist')
                FSPath.pwd = self.path

            def touch(pself) -> None:
                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"
                checkStr += ' = File(bytes(), None, None, None)'

                exec(checkStr, {"__builtins__": {'bytes': bytes, 'None': None}, 'File': FilesystemFile, 'lookup': self._fileSystemLookup})

            def mkdir(pself) -> None:
                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"
                checkStr += ' = File(None, {}, None, None)'

                exec(checkStr, {"__builtins__": {'bytes': bytes, 'None': None}, 'File': FilesystemFile, 'lookup': self._fileSystemLookup})

            def open(pself, mode: str = 'r', encoding: str = 'utf-8') -> FSFileIO:
                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"
                return FSFileIO(eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup}), mode, encoding)

            def remove(pself) -> None:
                if not pself.exists():
                    raise FSPathError("Cannot remove a file that doesn't exist")

                checkStr = 'lookup'
                for idx, pathPart in enumerate(pself.parent._parsedPath):
                    if idx >= 1 and len(pself._parsedPath) - 1 != idx:
                        checkStr += f"['{pathPart}'].files"
                    elif idx < 1 or len(pself._parsedPath) - 1 == idx:
                        checkStr += f"['{pathPart}']"

                obj = eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup})
                if isinstance(obj, dict):
                    obj.pop(pself.name)

                elif isinstance(obj, FilesystemFile):
                    obj.files.pop(pself.name)

            def rename(pself, newPath) -> None:
                if not pself.exists():
                    raise FSPathError("Cannot rename a file that doesn't exist")

                if not isinstance(newPath, FSPath):
                    raise FSPathError("newPath has to be a Filesystem Path object")

                with pself.open('rb') as file:
                    content = file.read()

                pself.remove()
                newPath.touch()
                with newPath.open("wb") as file:
                    file.write(content)

            def __str__(self) -> str:
                return changePathToName(self.path)

        self.Path = FSPath

    def __repr__(self) -> str:
        return f"< PortableFilesystem | Name: {self.name}, Filepath: {self.filepath} >"

    def __str__(self) -> str:
        return self.name

    def save(self, filepath: Path | None = None) -> None:

        def splitInt(num: int) -> list[int]:
            parts: list[int] = []
            while num > 0xFF:
                parts.append(0xFF)
                num -= 0xFF
            parts.append(num)
            return parts

        header = bytes([self.version - 1, self.compressionVer]) + fixedBytesLength(bytes(self.name, 'ascii'), 13)
        drives = b''.join([bytes([int(driveID, 16)]) + fixedBytesLength(bytes(driveName, 'ascii'), 13) + self.driveAttributesLookup[driveID].to_bytes(2, byteorder='big') for driveName, driveID in self.driveLookup.items()])

        def FileAttrsToBytes(obj: FilesystemFile) -> bytes:
            result = bytes()
            for attr, attrData in {attributeName:attribute for attributeName, attribute in (('bytes', obj.bytes), ('files', obj.files), ('metadata', obj.metadata), ('streamdata', obj.streamdata)) if attribute != None}.items():
                if attr == 'bytes':
                    result += bytes('b', 'ascii') + b'\xFF' + attrData + b'\xAF'

                if attr == 'metadata':
                    result += bytes("m", "ascii") + b'\xFF' + bytes(json.dumps(attrData), "ascii") + b'\xAF'

                if attr == 'files':
                    dirBytes = (b'\x00'.join((b'\x00'.join([bytes(name, 'ascii'), FileAttrsToBytes(saveData)]) for name, saveData in obj.files.items()))).replace(b'\x00', b'\x9D\x00')
                    result += bytes('f', 'ascii') + b'\xFF' + bytes(splitInt(len(dirBytes))) + b'\x9D' + dirBytes + b'\xAF'

            return result

        def convertFileToBytes(filepath) -> bytes:
            if not isinstance(filepath, self.Path):
                raise TypeError("")
            if not filepath.exists():
                raise ValueError("")
            checkStr = 'lookup'
            for idx, pathPart in enumerate(filepath._parsedPath):
                if idx >= 1 and len(filepath._parsedPath) - 1 != idx:
                    checkStr += f"['{pathPart}'].files"
                elif idx < 1 or len(filepath._parsedPath) - 1 == idx:
                    checkStr += f"['{pathPart}']"

            obj = eval(checkStr, {'__builtins__': None, 'lookup': self._fileSystemLookup})

            if isinstance(obj, dict):
                result = b'\x00'.join([convertFileToBytes(filepath.joinpath(filename)) for filename in obj.keys()])

            elif isinstance(obj, FilesystemFile):
                result = b'\x00'.join((bytes(filepath._parsedPath[-1], 'ascii'), FileAttrsToBytes(obj)))

            return result

        filedata = b'\x00\x00'.join((convertFileToBytes(self.Path(f'{drive}:/')) for drive in self.driveLookup.values()))
        path = filepath if filepath != None else self.filepath
        with path.open('wb') as file:
            file.write(header + b'\x00' + drives + b'\x00\x00' + filedata)

    def extract(self, fspath, folderpath: Path) -> None:
        if not isinstance(fspath, self.Path):
            raise ValueError(f"Cannot extract if the directory to extract from is type '{type(path)}'.")

        if not fspath.is_dir():
            raise ValueError("Cannot extract if the directory to extract from is a file or does not exist.")

        if not folderpath.is_dir():
            raise ValueError("Cannot extract if the path to extract to is a file or does not exist.")

        for path in fspath.iterdir():
            if path.is_file():
                ospath = folderpath.joinpath(path.name)
                ospath.touch()
                with path.open("rb") as file:
                    content = file.read()

                with ospath.open("wb") as file:
                    file.write(content)

                continue

            if path.is_dir():
                ospath = folderpath.joinpath(path.name)
                ospath.mkdir(exist_ok=True)
                self.extract(path, ospath)

    def copy(self, dirpath: Path, fsdir) -> None:
        if not isinstance(fsdir, self.Path):
            raise ValueError(f"Cannot copy if the directory to copy to is type '{type(path)}'.")

        if not fsdir.is_dir():
            raise ValueError("Cannot copy if the directory to copy to is a file or does not exist.")

        if not dirpath.is_dir():
            raise ValueError("Cannot copy if the path to copy from is a file or does not exist.")

        for path in dirpath.iterdir():
            if path.is_file():
                fspath = fsdir.joinpath(path.name)
                fspath.touch()
                with path.open("rb") as file:
                    content = file.read()

                with fspath.open("wb") as file:
                    file.write(content)

                continue

            if path.is_dir():
                fspath = fsdir.joinpath(path.name)
                fspath.mkdir()
                self.copy(path, fspath)

    @staticmethod
    def new(filepath: Path, name: str, drives: list[str]):
        root = bytes([0, 0]) + fixedBytesLength(bytes(name, 'ascii'), 13)
        drivesHeader = b""
        for i, drive in enumerate(drives):
            drivesHeader += bytes([i]) + fixedBytesLength(bytes(drive, 'ascii'), 13) + b"\x00\x00"

        header = b"\x00".join([root, drivesHeader])

        if not filepath.exists():
            filepath.touch()

        with filepath.open("wb") as file:
            file.write(header + (b"\x00"*2))

        return PortableFilesystem(filepath)

    @atexit.register
    @staticmethod
    def closeAll() -> None:
        for instance in PortableFilesystem.registry.values():
            instance.__closed__ = True
            instance.file.close()
            instance = None
            del instance

        PortableFilesystem.registry.clear()

if __name__ == "__main__":
    path = Path("new.pfs")
    if not path.exists():
        fs = PortableFilesystem.new(path, "Launcher", ["T", "L"])

    else:
        fs = PortableFilesystem(path)

    fs.Path("test.txt").touch()
    with fs.Path("test.txt").open('w') as file:
        file.write("Hi, I am a secret file...\nOh No! You see me :(")

    fs.copy(Path("C:\\Users\\Charl\\OneDrive\\Documents\\Code_Projects\\python\\Languages"), fs.Path('L:/'))

    Path("tst/").mkdir()
    fs.extract(fs.Path('L:/'), Path("tst/"))