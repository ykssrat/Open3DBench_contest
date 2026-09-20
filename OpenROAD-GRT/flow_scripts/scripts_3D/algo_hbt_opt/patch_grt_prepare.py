#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_grt_prepare.py -- 在 grt_prepare.tcl 中插入 [AGENT_EXPORT_V1] 导出块.

不改动任何原有逻辑(不修改 HBT 搬运、不修改已有 CSV 结构), 只在
"3. HBT 搬运" 之前插入一段纯读取/导出代码, 新增三个文件:
  export_hbt_current.csv : InstName,CurX,CurY     (HBT 当前坐标)
  export_free_sites.csv  : X,Y                    (合法空闲键合格点)
  export_meta.txt        : DBU/ORIGIN/PITCH/HBT_W/HBT_H/DIE
幂等: 检测 MARK 已存在则直接退出. 首次执行会备份为 *.orig.
"""
import re
import shutil
import sys

DEFAULT = "/workspace/Open3DBench/OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt/grt_prepare.tcl"
MARK = "AGENT_EXPORT_V1"

BLOCK = r"""
# ============================================================
# 2b. [AGENT_EXPORT_V1] 为全局指派求解器补充导出
#   仅做读取与写出, 不改动任何元件布局.
# ============================================================
if {![info exists ::env(RESULTS_DIR)]} {
    set ::env(RESULTS_DIR) "/workspace/Open3DBench/measure_run_bp_fe"
}
set __rd $::env(RESULTS_DIR)
file mkdir $__rd

set __dbu [expr {int([$block getDbUnitsPerMicron])}]
set __HBT_PITCH 12800
set __HBT_OX 11990
set __HBT_OY 11940

# HBT 主单元尺寸(用于 footprint 越界/重叠判断)
set __HBT_W 0
set __HBT_H 0
foreach __inst [$block getInsts] {
    set __nm [$__inst getName]
    if {[string match "HBT_*" $__nm] || [string match "LS_HBT_*" $__nm]} {
        set __bb [$__inst getBBox]
        set __HBT_W [expr {[$__bb xMax] - [$__bb xMin]}]
        set __HBT_H [expr {[$__bb yMax] - [$__bb yMin]}]
        break
    }
}

set __fx0 [$die_area xMin]
set __fy0 [$die_area yMin]
set __fx1 [$die_area xMax]
set __fy1 [$die_area yMax]

set __fm [open "$__rd/export_meta.txt" w]
puts $__fm "DBU=$__dbu"
puts $__fm "ORIGIN_X=$__HBT_OX"
puts $__fm "ORIGIN_Y=$__HBT_OY"
puts $__fm "PITCH=$__HBT_PITCH"
puts $__fm "HBT_W=$__HBT_W"
puts $__fm "HBT_H=$__HBT_H"
puts $__fm "DIE=$__fx0,$__fy0,$__fx1,$__fy1"
close $__fm

# 1) HBT 当前坐标
set __fc [open "$__rd/export_hbt_current.csv" w]
puts $__fc "InstName,CurX,CurY"
foreach __inst [$block getInsts] {
    set __nm [$__inst getName]
    if {[string match "HBT_*" $__nm] || [string match "LS_HBT_*" $__nm]} {
        lassign [$__inst getLocation] __ix __iy
        puts $__fc "$__nm,$__ix,$__iy"
    }
}
close $__fc

# 2) 被非 HBT 元件 footprint 覆盖的格点
array unset __blocked
array set __blocked {}
foreach __inst [$block getInsts] {
    set __nm [$__inst getName]
    if {[string match "HBT_*" $__nm] || [string match "LS_HBT_*" $__nm]} { continue }
    set __bb [$__inst getBBox]
    set __x0 [$__bb xMin]
    set __y0 [$__bb yMin]
    set __x1 [$__bb xMax]
    set __y1 [$__bb yMax]
    set __i0 [expr {int(ceil(($__x0 - $__HBT_W - $__HBT_OX) / double($__HBT_PITCH)))}]
    set __i1 [expr {int(floor(($__x1 - $__HBT_OX) / double($__HBT_PITCH)))}]
    set __j0 [expr {int(ceil(($__y0 - $__HBT_H - $__HBT_OY) / double($__HBT_PITCH)))}]
    set __j1 [expr {int(floor(($__y1 - $__HBT_OY) / double($__HBT_PITCH)))}]
    for {set __i $__i0} {$__i <= $__i1} {incr __i} {
        set __gx [expr {$__HBT_OX + $__i * $__HBT_PITCH}]
        for {set __j $__j0} {$__j <= $__j1} {incr __j} {
            set __gy [expr {$__HBT_OY + $__j * $__HBT_PITCH}]
            set __blocked($__gx,$__gy) 1
        }
    }
}

# 3) 空闲且 footprint 完全在 die 内的格点
set __fs [open "$__rd/export_free_sites.csv" w]
puts $__fs "X,Y"
set __i0 [expr {int(ceil(($__fx0 - $__HBT_OX) / double($__HBT_PITCH)))}]
set __i1 [expr {int(floor(($__fx1 - $__HBT_W - $__HBT_OX) / double($__HBT_PITCH)))}]
set __j0 [expr {int(ceil(($__fy0 - $__HBT_OY) / double($__HBT_PITCH)))}]
set __j1 [expr {int(floor(($__fy1 - $__HBT_H - $__HBT_OY) / double($__HBT_PITCH)))}]
set __nfree 0
for {set __i $__i0} {$__i <= $__i1} {incr __i} {
    set __gx [expr {$__HBT_OX + $__i * $__HBT_PITCH}]
    for {set __j $__j0} {$__j <= $__j1} {incr __j} {
        set __gy [expr {$__HBT_OY + $__j * $__HBT_PITCH}]
        if {[info exists __blocked($__gx,$__gy)]} { continue }
        puts $__fs "$__gx,$__gy"
        incr __nfree
    }
}
close $__fs
puts "\[INFO\] \[AGENT_EXPORT_V1\] HBT footprint=${__HBT_W}x${__HBT_H} 空闲格点=$__nfree"

# 4) 就地调用全局指派求解器, 生成 best_hbt_locations.csv
#    (GRT_PREPARE_MOVE=0 时跳过, 与下游第 3 节的搬运开关保持一致)
if {[info exists ::env(GRT_PREPARE_MOVE)] && $::env(GRT_PREPARE_MOVE) eq "0"} {
    puts "\[INFO\] \[AGENT_EXPORT_V1\] GRT_PREPARE_MOVE=0 -> 跳过求解器"
} else {
    set __py "/workspace/Open3DBench/OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt/optimize_hbts.py"
    if {[file exists $__py]} {
        set __rc [catch {exec python3 $__py} __out]
        puts "\[INFO\] \[AGENT_EXPORT_V1\] solver rc=$__rc"
        puts $__out
    } else {
        puts "\[WARN\] \[AGENT_EXPORT_V1\] 求解器缺失: $__py"
    }
}
# ============================================================
"""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    txt = open(src, encoding="utf-8", errors="ignore").read()
    if MARK in txt:
        print("already patched:", src)
        return 0
    bak = src + ".orig"
    if not os.path.exists(bak):
        shutil.copy(src, bak)
    lines = txt.split("\n")
    idx = None
    for i, ln in enumerate(lines):
        if re.search(r"^\s*#\s*3\.\s*HBT", ln):
            idx = i
            break
    if idx is None:
        new = txt.rstrip("\n") + "\n" + BLOCK
        print("anchor not found -> appended at EOF")
    else:
        new = "\n".join(lines[:idx]) + "\n" + BLOCK + "\n".join(lines[idx:])
        print("inserted before line %d: %s" % (idx + 1, lines[idx].strip()))
    open(src, "w", encoding="utf-8").write(new)
    print("patched:", src, "(backup:", bak + ")")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
