"""Join wrapped '## ' heading continuation lines in docs/PARSING_RULES.md (plan step A, content unchanged)."""
import re
import sys

PATH = "docs/PARSING_RULES.md"
KEEP = re.compile(r"## (R\d|부록|0\.)")


def main(write: bool) -> None:
    lines = open(PATH, encoding="utf-8").read().split("\n")
    out: list[str] = []
    head_idx = -1  # index in out of the latest '## R' heading
    joined = 0
    for line in lines:
        if line.startswith("## ") and KEEP.match(line):
            head_idx = len(out)
            out.append(line)
        elif line.startswith("##") and not line.startswith("###") and head_idx >= 0:
            out[head_idx] = out[head_idx].rstrip() + " " + line[2:].strip()
            joined += 1
        else:
            out.append(line)
    print("joined continuation lines:", joined)
    if write:
        open(PATH, "w", encoding="utf-8").write("\n".join(out))


if __name__ == "__main__":
    main("--write" in sys.argv)
