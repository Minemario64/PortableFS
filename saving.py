from __init__ import *
from pathlib import Path
import tester
import time

def indexOffset(data: list[bytes], startItemIdx: int) -> int:
    result: int = 0
    for i, item in enumerate(data):
        if i == startItemIdx:
            return result

        result += len(item)

    return result

def flattenStructRec(dirContents: dict[str, tuple[File, bytes] | tuple[Directory, dict]], *, recursing: bool = True) -> tuple[list[File], list[Directory], bytes | list[bytes]]:
    files, dirs, data = [], [], []
    for name, val in dirContents.items():
        if isinstance(val[0], File):
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
            recFiles, recDirs, recData = flattenStructRec(val[1], recursing=False) # pyright: ignore[reportArgumentType]
            files.extend(recFiles)
            dirs.extend(recDirs)
            data.extend(recData)
            continue

    for i, file in enumerate(files):
        file.offset = indexOffset(data, i)

    return files, dirs, b"".join(data) if recursing else data

def fixedBytesLength(bytesObj: bytes, length: int, fill: bytes = b'\x00') -> bytes:
    if len(bytesObj) < length:
        return bytesObj + fill*(length - len(bytesObj))
    elif len(bytesObj) == length:
        return bytesObj
    elif len(bytesObj) > length:
        return bytes(bytearray(bytesObj)[0:length])

    else:
        raise ValueError()

def save(self: PortableFS) -> bytes:
    if len(self.name) > 13:
        raise PortableFSEncodingError("Cannot save a pfs for spec v1 with a name of greater that 13 chars.")

    data: bytes = b"pfs0"
    data += bytes([self.version]) + fixedBytesLength(self.name.encode(), 13) + bytes([len(self.drives)])
    files: list[File] = []
    dirs: list[Directory] = []
    fileData: bytes = bytes()
    for drive in self.drives:
        data += bytes([(PortableFS.DRIVE_CHARS.index(drive.name) << 4) + drive.id])
        dfiles, ddirs, ddata = flattenStructRec(self._struct[drive.name])
        files.extend(dfiles)
        dirs.extend(ddirs)
        fileData += ddata # pyright: ignore[reportOperatorIssue]

    if len(dirs).bit_length() > 15:
        PortableFSEncodingError("Cannot save a pfs for spec v1 with the total amount of directories larger than 2^15")

    if len(files).bit_length() > 24:
        PortableFSEncodingError("Cannot save a pfs for spec v1 with the total amount of files larger than 2^24")

    data += len(dirs).to_bytes(2, byteorder="big")
    for directory in dirs:
        if directory.id.bit_length() > 15:
            PortableFSEncodingError("Cannot save a pfs for spec v1 with a directory ID larger than 2^15")

        data += directory.id.to_bytes(2, byteorder="big")
        data += len(directory.name).to_bytes(byteorder="big")
        data += bytes(directory.name, 'utf-8')
        data += bytes([(int(directory.attributes.hidden) << 7)])
        data += directory.highDir.to_bytes(2, byteorder="big")

    data += len(files).to_bytes(3, byteorder="big")
    for file in files:
        data += len(file.name).to_bytes(byteorder="big")
        data += bytes(file.name, "utf-8")
        data += bytes([(int(file.attributes.readOnly) << 7) | (int(file.attributes.hidden) << 6)])
        data += file.highDir.to_bytes(2, byteorder="big")
        data += file.offset.to_bytes(8, byteorder="big")
        data += file.size.to_bytes(8, byteorder="big")

    data += fileData

    return data

def wf(path: Path, data: bytes) -> None:
    if path.exists():
        path.unlink()

    with path.open("xb") as file:
        file.write(data)

tester.GLOBALS |= {"save": save, "Path": Path, 'PortableFS': PortableFS, 'time': time, "wf": wf}


with Path("filesysMock2.bin").open("rb") as file:
    tester.GLOBALS['M2'] = file.read()

tester.describe("PortableFS Saving", '''
it("filesysMock1 mirror", """
    pfs = PortableFS(Path("filesysMock1.bin"))
    result: bytes = save(pfs)
    wf(Path("tmp.pfs"), result)
    test = PortableFS(Path("tmp.pfs"))
    print(pfs._struct, test._struct, sep="\\\\n----------\\\\n")
    input()
    passed(test._struct == pfs._struct)
""")
it("filesysMock2 mirror", """
    pfs = PortableFS(Path("filesysMock2.bin"))
    result: bytes = save(pfs)
    wf(Path("tmp.pfs"), result)
    tst = PortableFS(Path("tmp.pfs"))
    print(pfs._struct, tst._struct, sep="\\\\n----------\\\\n")
    input()
    passed(pfs._struct == tst._struct)
""")
''')