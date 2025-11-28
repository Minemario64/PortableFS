from __init__ import *
from pathlib import Path

recTestPath: Path = Path("recTst.pfs")
recOutPath: Path = Path("recOutTst.pfs")

if not recTestPath.exists():
    with PortableFS.new("recursionTst") as fs:
        pth = fs.Path("A:/rec.pfs")
        pth.touch()

        with Path("filesysMock2.bin").open("rb") as file:
            content: bytes = file.read()

        with pth.open("wb") as file:
            file.write(content)

        fs.save(recTestPath)

pfs = PortableFS(recTestPath)
with pfs.Path("A:/rec.pfs").open("rb") as file:
    recOut: bytes = file.read() # pyright: ignore[reportAssignmentType]

if not recOutPath.exists():
    recOutPath.touch()

with recOutPath.open("wb") as file:
    file.write(recOut)

pfs.close()

pfs = PortableFS(recOutPath)
pfs.close()