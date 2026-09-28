import os, sys, runpy
import fin2.extract.sce_sign_repair as ssr
orig = ssr._solve_block
def sb(cells, block, anchors, carried=None):
    o, mv, c = block
    ln = cells[o].line
    res = orig(cells, block, anchors, carried)
    if ln.basis == sys.argv[2] and ln.col_index == int(sys.argv[3]):
        print("BLOCK", cells[o].label_raw[:14], [(cells[i].line.row_order, cells[i].value) for i in [o, *mv, c]])
        print("   req", {cells[i].line.row_order: ssr._required_sign(cells[i], anchors, carried) for i in [o, *mv, c]}, "->", res)
    return res
ssr._solve_block = sb
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace_anchors_fixes.py"), run_name="__main__")
