import re, json, sys
src = open("part_js.html", encoding="utf-8").read()
# parse S( calls: first arg string literal "..." or template `...`
out = []; tmpl = []
i = 0
while True:
    j = src.find("S(", i)
    if j < 0: break
    # ensure it's the S function, not e.g. "TERMS(" or "JS(" -> check preceding char
    pre = src[j-1] if j > 0 else ""
    if pre.isalnum() or pre in "_$.": i = j + 2; continue
    k = j + 2
    if src[k] == '"':
        # parse string literal
        m = k + 1; s = ""
        while True:
            c = src[m]
            if c == "\\": s += src[m:m+2]; m += 2; continue
            if c == '"': break
            s += c; m += 1
        line = src.count("\n", 0, j) + 1
        out.append((s, line))
        i = m + 1
    elif src[k] == "`":
        m = k + 1; depth = 0
        while not (src[m] == "`" and src[m-1] != "\\"): m += 1
        line = src.count("\n", 0, j) + 1
        tmpl.append((src[k:m+1], line))
        i = m + 1
    else:
        line = src.count("\n", 0, j) + 1
        tmpl.append(("OTHER: " + src[j:j+60].replace("\n"," "), line))
        i = k
uniq = {}
for s, line in out:
    uniq.setdefault(s, []).append(line)
print("literal calls:", len(out), "unique:", len(uniq), "template/other:", len(tmpl))
json.dump({"literal": [[s, l] for s, l in uniq.items()], "template": tmpl}, open("en/s_strings.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for s, l in tmpl: print(l, s[:110])
