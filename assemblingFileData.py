from __init__ import *
from flatteningStruct import *
from pathlib import Path
from typing import Iterator
import tester
import time

def indexOffset(data: list[bytes], startItemIdx: int) -> int:
    result: int = 0
    for i, item in enumerate(data):
        if i == startItemIdx:
            return result

        result += len(item)

    return result

def flattenStructRec(dirContents: dict[str, tuple[File, bytes] | tuple[Directory, dict]]) -> tuple[list[File], list[Directory], bytes]:
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
            recFiles, recDirs = flattenRec(val[1]) # pyright: ignore[reportArgumentType]
            files.extend(recFiles)
            dirs.extend(recDirs)
            continue

    for i, file in enumerate(files):
        file.offset = indexOffset(data, i)

    return files, dirs, b"".join(data)