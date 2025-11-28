from package import *
from package.macros import *

TMP: Path = Path.home().joinpath("Appdata/Local/Programs/Common/Tst")
if not TMP.exists():
    TMP.mkdir(parents=True)

pfs = PortableFS(Path("aptst"))
copyDirToRealFS(pfs, TMP.joinpath("Silksong"), pfs.Path("A:/"))
pfs.close()