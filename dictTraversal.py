import tester
from typing import Any
import time

class DictStructPath(dict):
    def tsd(self, path: str, value: Any) -> None:
        parts: list[str] = path.split("/")
        strCode: str = f"self[{int(parts[0])}]"
        for part in parts[1:-1]:
            strCode += f"['{part}'][1]"

        strCode += f"['{parts[-1]}'] = val"
        exec(strCode, {"__builtins__": None, "self": self, "val": value})


tester.GLOBALS |= {"Dsp": DictStructPath, "time": time}

tester.describe("Set a Value in a dict using a traversal string", '''
it("traverses to path 0/secrets/secrets.txt", """
    d: Dsp = Dsp({0: {"secrets": (1, {})}})
    d.tsd("0/secrets/secrets.txt", (1, 10))
    print(d)
    time.sleep(2)
    passed(d == {0: {"secrets": (1, {"secrets.txt": (1, 10)})}})
""")
''')