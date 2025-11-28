from __init__ import *
from pathlib import Path
import tkinter.filedialog as fd

with PortableFS.new("AppTst") as fs:
    PFSPath = fs.Path
    pth: PFSPath = fs.Path("A:/app.exe")
    pth.touch()
    with open(fd.askopenfilename(defaultextension="*.exe", filetypes=(("Program Files", "*.exe"),)), "rb") as file:
        appContent: bytes = file.read()


    with pth.open("wb") as file:
        file.write(appContent)

    fs.save(Path("appTst.pfs"))

pfs: PortableFS = PortableFS(Path("appTst.pfs"))
pfs.close()