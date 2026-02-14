import json

def doThing(x:int)->int:
    return x+1

def main():
    v = doThing(3)
    print(json.dumps({"v": v}))

if __name__ == "__main__":
    main()
