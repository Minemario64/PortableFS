from __init__ import *
import macros as pfsm

with PortableFS.new("ssf2", ['G']) as fs:
    pfsm.copyDirToPFS(fs, Path(r"C:\Program Files (x86)\Super Smash Flash 2 Beta"), fs.Path("G:/"))
    fs.save(Path("ssf2.pfs"))