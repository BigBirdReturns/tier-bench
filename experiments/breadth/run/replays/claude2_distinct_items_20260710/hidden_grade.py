#!/usr/bin/env python3
"""Grade a replay candidate against mechanically derived hidden vectors."""
import importlib.util, json, sys, pathlib
item_dir = pathlib.Path(sys.argv[1]); cand = pathlib.Path(sys.argv[2])
vec = json.loads((item_dir/"hidden_vectors.json").read_text())
spec = importlib.util.spec_from_file_location("cand", cand)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fn = getattr(m, item_dir.name.split("_",1)[1])  # dispatch by item, never by candidate attrs
ok=0; fails=[]
if fn.__name__=="validate_patterns":
    for v in vec:
        try: g=fn([v["pattern"]])[0]
        except Exception as e: g=f"raised {type(e).__name__}"
        if isinstance(g,bool) and g==v["wellformed"]: ok+=1
        else: fails.append((v["pattern"],g,v["wellformed"]))
else:
    for v in vec:
        args = (v["cls"],v["chars"]) if "cls" in v else (v["pattern"],v["words"])
        try:
            got = fn(*args); res={"result":got}
        except ValueError: res={"error":"ValueError"}
        except Exception as e: res={"error":type(e).__name__}
        want = {k:v[k] for k in ("result","error") if k in v}
        if res==want: ok+=1
        else: fails.append((args[0],res,want))
print(f"SCORE {ok}/{len(vec)}")
for f in fails[:6]: print("  FAIL",f)
sys.exit(0 if ok==len(vec) else 1)
