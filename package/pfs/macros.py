from .__init__ import PortableFS
from pathlib import Path

def copyFileToPFS(pfs: PortableFS, realpath: Path, pfspath) -> None:
    if not isinstance(pfspath, pfs.Path):
        raise TypeError("pfspath must be a Path of the passed PortableFS")

    if pfspath.is_drive():
        raise ValueError("Cannot copy a file to replace a drive")

    if pfspath.is_dir():
        raise ValueError("Cannot copy a directory, use 'copyDirToPFS' for copying directories and their contents")

    if not realpath.is_file():
        raise ValueError("Cannot copy a directory or a path that does not exist to a file")

    with realpath.open("rb") as ogfile:
        content: bytes = ogfile.read()

    if not pfspath.exists():
        pfspath.touch()

    with pfspath.open("wb") as dupfile:
        dupfile.write(content)

def copyDirToPFS(pfs: PortableFS, realpath: Path, pfspath) -> None:
    if not isinstance(pfspath, pfs.Path):
        raise TypeError("pfspath must be a Path of the passed PortableFS")

    if pfspath.is_file():
        raise ValueError("Cannot copy a file, use 'copyFileToPFS' for copying files")

    if not realpath.is_dir():
        raise ValueError("Cannot copy a file or a path that does not exist to a directory")

    if not pfspath.exists():
        pfspath.mkdir()

    for path in realpath.iterdir():
        if path.is_file():
            print(f"Copying File {path}")
            pth = pfspath.joinpath(path.name)
            copyFileToPFS(pfs, path, pth)

        if path.is_dir():
            print(f"Copying Dir from {realpath}")
            pth = pfspath.joinpath(path.name)
            copyDirToPFS(pfs, path, pth)

def copyFileToRealFS(pfs: PortableFS, realpath: Path, pfspath) -> None:
    if not isinstance(pfspath, pfs.Path):
        raise TypeError("pfspath must be a Path of the passed PortableFS")

    if not pfspath.is_file():
        raise ValueError("Cannot copy a directory or a path that does not exist. Use 'copyDirToRealFS' for copying directories")

    if realpath.is_dir():
        raise ValueError("Cannot copy a file to replace a directory")

    if not realpath.exists():
        realpath.touch()

    with pfspath.open("rb") as ogfile:
        content: bytes = ogfile.read() # pyright: ignore[reportAssignmentType]

    with realpath.open("wb") as dupfile:
        dupfile.write(content)

def copyDirToRealFS(pfs: PortableFS, realpath: Path, pfspath) -> None:
    if not isinstance(pfspath, pfs.Path):
        raise TypeError("pfspath must be a Path of the passed PortableFS")

    if not pfspath.is_dir():
        raise ValueError("Cannot copy a file or a path that does not exist. Use 'copyFileToRealFS' for copying directories")

    if realpath.is_file():
        raise ValueError("Cannot copy a directory to replace a file")

    if not realpath.exists():
        realpath.mkdir()

    for path in pfspath.iterdir():
        if path.is_file():
            pth: Path = realpath.joinpath(path.name)
            copyFileToRealFS(pfs, pth, path)

        if path.is_dir():
            pth: Path = realpath.joinpath(path.name)
            copyDirToRealFS(pfs, pth, path)