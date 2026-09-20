# ============================================================
#  grt_prepare.tcl —— HBT 重布局 + 运行前/后测量
#
#  用法 A（挂进官方流程，只做 HBT 搬运，不测量）：
#      GRT_PREPARE_TCL=<本文件> contest run-grt <case> <input> <label>
#
#  用法 B（本地 openroad 独立跑，做 before/after 测量）：
#      GRT_STANDALONE=1 GRT_PREPARE_MEASURE=1 \
#      GRT_MEASURE_TAG=before GRT_PREPARE_MOVE=0 \
#      GRT_INPUT_DIR=<输入包> CASE=bp_fe RESULTS_DIR=<输出> \
#      openroad -exit <本文件>
#
#  开关：
#    GRT_STANDALONE=1       自行读 LEF/DEF/SDC/LIB（本地 openroad 用）
#    GRT_PREPARE_MEASURE=1  执行测量块（默认关，避免污染官方流程）
#    GRT_PREPARE_MOVE=0     跳过 HBT 移动（跑 baseline 对照）
#    GRT_MEASURE_TAG        before / after，报告子目录名
#    GRT_INPUT_DIR / CASE / RESULTS_DIR  独立模式输入
# ============================================================

proc env_on {name {default 0}} {
  if {![info exists ::env($name)]} { return $default }
  set v [string tolower $::env($name)]
  return [expr {$v ne "" && $v ne "0" && $v ne "off" && $v ne "no" && $v ne "false"}]
}

set STANDALONE [env_on GRT_STANDALONE 0]
set MEASURE    [env_on GRT_PREPARE_MEASURE 0]
set DO_MOVE    [env_on GRT_PREPARE_MOVE 1]

if {[info exists ::env(GRT_MEASURE_TAG)] && $::env(GRT_MEASURE_TAG) ne ""} {
  set TAG $::env(GRT_MEASURE_TAG)
} else {
  set TAG "run"
}
if {[info exists ::env(RESULTS_DIR)] && $::env(RESULTS_DIR) ne ""} {
  set results_dir $::env(RESULTS_DIR)
} else {
  set results_dir [pwd]
}
file mkdir $results_dir

# ============================================================
# 0. 独立自举：本地 openroad 时自己把设计读进来
# ============================================================
if {$STANDALONE} {
  if {[info exists ::env(GRT_INPUT_DIR)]} {
    set input_dir $::env(GRT_INPUT_DIR)
  } else {
    set input_dir ""
  }
  if {[info exists ::env(CASE)] && $::env(CASE) ne ""} {
    set case $::env(CASE)
  } else {
    set case "bp_fe"
  }
  if {$input_dir eq ""} { error "GRT_INPUT_DIR not set" }

  if {[info exists ::env(GRT_PREPARE_PLATFORM)] && $::env(GRT_PREPARE_PLATFORM) ne ""} {
    set plat_name $::env(GRT_PREPARE_PLATFORM)
  } else {
    set plat_name "nangate45_3D"
  }
  set plat     "$input_dir/platforms/$plat_name"
  set case_dir "$input_dir/cases/$case"
  set ::env(PLATFORM_DIR) $plat
  set ::env(RESULTS_DIR)  $results_dir
  set ::env(DESIGN_NAME)  $case

  puts "\[BOOT\] input=$input_dir case=$case platform=$plat_name results=$results_dir"

  # 1) 技术 LEF 必须最先
  set tech_lefs [lsort [glob -nocomplain "$plat/lef/*tech*.lef"]]
  if {[llength $tech_lefs] == 0} { error "no tech LEF under $plat/lef" }
  read_lef [lindex $tech_lefs 0]

  # 2) 标准单元 + HBT master（bottom 先、upper 后）
  set std_read 0
  foreach f [list "$plat/lef_bottom/NangateOpenCellLibrary.macro.mod.bottom.lef" \
                  "$plat/lef_upper/NangateOpenCellLibrary.macro.mod.upper.lef"] {
    if {[file exists $f]} { read_lef $f; incr std_read } \
    else { puts "\[BOOT\]\[WARN\] missing $f" }
  }
  # 旧版布局（无 lef_bottom / lef_upper）时退回 lef/ 下的 macro LEF
  if {$std_read == 0} {
    foreach lef [lsort [glob -nocomplain "$plat/lef/*macro*.lef"]] { catch { read_lef $lef } }
  }

  # 3) 宏单元 LEF
  foreach pat [list "$plat/lef/fakeram*.lef" \
                    "$plat/lef_bottom/fakeram*.bottom.lef" \
                    "$plat/lef_upper/fakeram*.upper.lef"] {
    foreach lef [lsort [glob -nocomplain $pat]] { catch { read_lef $lef } }
  }

  # 4) DEF
  set def_file "$case_dir/grt_input/4_1_cts.def"
  if {![file exists $def_file]} {
    set cands [lsort [glob -nocomplain "$case_dir/grt_input/*.def"]]
    if {[llength $cands] == 0} { error "no DEF under $case_dir/grt_input" }
    set def_file [lindex $cands end]
  }
  puts "\[BOOT\] def=$def_file"
  read_def $def_file

  # 5) Liberty
  foreach lib [lsort [concat [glob -nocomplain "$plat/lib_bottom/*.bottom.lib"] \
                             [glob -nocomplain "$plat/lib_upper/*.upper.lib"] \
                             [glob -nocomplain "$plat/lib/*.lib"]]] {
    catch { read_liberty $lib }
  }

  # 6) SDC
  set sdc_file "$case_dir/grt_input/4_cts.sdc"
  if {![file exists $sdc_file]} {
    set cands [lsort [glob -nocomplain "$case_dir/grt_input/*.sdc"]]
    if {[llength $cands] > 0} { set sdc_file [lindex $cands end] }
  }
  if {[file exists $sdc_file]} { read_sdc $sdc_file; puts "\[BOOT\] sdc=$sdc_file" } \
  else { puts "\[BOOT\]\[WARN\] no SDC under $case_dir/grt_input" }

  catch { source "$plat/setRC.tcl" }
  catch { source "$plat/fastroute.tcl" }
  puts "\[BOOT\] design loaded."
}

# ============================================================
# 1. 通用工具：依次尝试候选命令，第一个成功的写进 rpt，全失败只告警
# ============================================================
set MEASURE_DIR "$results_dir/measure/$TAG"
file mkdir $MEASURE_DIR

proc prep_step {name cmds} {
  global MEASURE_DIR
  set log  "$MEASURE_DIR/$name.rpt"
  set out  ""
  set used ""
  set notes {}
  foreach c $cmds {
    if {![catch {uplevel 1 $c} o]} { set used $c; set out $o; break }
    lappend notes "[lindex $c 0] :: $o"
  }
  set f [open $log w]
  puts $f "### $name"
  puts $f "### command: $used"
  puts $f $out
  if {$used eq ""} { foreach n $notes { puts $f "### FAILED $n" } }
  close $f
  if {$used eq ""} { puts "\[MEASURE\]\[WARN\] $name 全部候选不可用 -> $log" } \
  else             { puts "\[MEASURE\] $name -> $log" }
}

# 不依赖任何 report 命令的自算 HPWL（半周长线长，单位 um）——可移植保底指标
# 注意：dbNet **没有** getBBox（本版本的 dbNet 方法表里就没有），
#       必须从 ITerm / BTerm 的 bbox 聚合，否则报 "Invalid method"
proc _hpwl_terms_bbox { net xs_var ys_var } {
  upvar 1 $xs_var xs $ys_var ys
  set n 0
  foreach t [concat [$net getITerms] [$net getBTerms]] {
    if {[catch { set b [$t getBBox] }]} { continue }
    if {$b eq "NULL" || $b eq ""} { continue }
    lappend xs [$b xMin] [$b xMax]
    lappend ys [$b yMin] [$b yMax]
    incr n
  }
  return $n
}

proc _hpwl_span { vals } {
  set mn [lindex $vals 0]
  set mx $mn
  foreach v $vals { if {$v < $mn} { set mn $v }; if {$v > $mx} { set mx $v } }
  return [expr {$mx - $mn}]
}

proc self_hpwl_um {} {
  set block [[[::ord::get_db] getChip] getBlock]
  set dbu 1000
  catch { set dbu [expr {int([$block getDbUnitsPerMicron])}] }
  if {$dbu <= 0} { set dbu 1000 }
  set total 0.0
  set cnt 0
  foreach net [$block getNets] {
    if {[catch { set st [$net getSigType] }]} { continue }
    if {$st eq "POWER" || $st eq "GROUND"} { continue }
    set xs {}
    set ys {}
    if {[_hpwl_terms_bbox $net xs ys] < 2} { continue }
    set total [expr {$total + [_hpwl_span $xs] + [_hpwl_span $ys]}]
    incr cnt
  }
  if {$cnt == 0} { error "no net bbox collected: ITerm/BTerm getBBox unavailable" }
  return "HPWL_UM=[format %.4f [expr {$total / double($dbu)}]]\nNETS=$cnt\nDBU_PER_UM=$dbu"
}

# 备选：部分版本 dbNet 自带 getTermBBox
proc self_hpwl_um2 {} {
  set block [[[::ord::get_db] getChip] getBlock]
  set dbu 1000
  catch { set dbu [expr {int([$block getDbUnitsPerMicron])}] }
  if {$dbu <= 0} { set dbu 1000 }
  set total 0.0
  set cnt 0
  foreach net [$block getNets] {
    if {[catch { set st [$net getSigType] }]} { continue }
    if {$st eq "POWER" || $st eq "GROUND"} { continue }
    if {[catch { set b [$net getTermBBox] }]} { continue }
    if {$b eq "NULL" || $b eq ""} { continue }
    set total [expr {$total + ([$b xMax] - [$b xMin] + [$b yMax] - [$b yMin]) / double($dbu)}]
    incr cnt
  }
  if {$cnt == 0} { error "getTermBBox unavailable" }
  return "HPWL_UM=[format %.4f $total]\nNETS=$cnt\nDBU_PER_UM=$dbu"
}

# ============================================================
# 2. 提取芯片边界 / 时序特征 / HBT 拓扑 / 宏障碍
# ============================================================
puts "\[INFO\] 启动带边界限制与时序特征的全栈 HBT 优化流程..."
set db    [::ord::get_db]
set block [[$db getChip] getBlock]

set die_area [$block getDieArea]
set f_bounds [open "$results_dir/die_bounds.txt" w]
puts $f_bounds "[$die_area xMin],[$die_area yMin],[$die_area xMax],[$die_area yMax]"
close $f_bounds

proc get_net_pin_coords { net } {
    if {$net eq "NULL"} { return "NONE" }
    set coords {}
    foreach iterm [$net getITerms] {
        set inst [$iterm getInst]
        set inst_name [$inst getName]
        if {![string match "HBT_*" $inst_name] && ![string match "LS_HBT_*" $inst_name]} {
            lassign [$inst getLocation] px py
            set slack 999.0
            set mterm_name [[$iterm getMTerm] getName]
            catch {
                set pin_obj [get_pins -quiet "${inst_name}/${mterm_name}"]
                if {$pin_obj ne ""} {
                    set s [get_property $pin_obj slack_max]
                    if {$s ne ""} { set slack $s }
                }
            }
            lappend coords "${px}_${py}_${slack}"
        }
    }
    if {[llength $coords] == 0} { return "NONE" }
    return [join $coords "|"]
}

set topo_file "$results_dir/export_hbt_topology.csv"
set f [open $topo_file w]
puts $f "InstName,Bot_Coords,Top_Coords"
foreach inst [$block getInsts] {
    set name [$inst getName]
    if {[string match "HBT_*" $name] || [string match "LS_HBT_*" $name]} {
        set bot_net "NULL"
        set top_net "NULL"
        foreach iterm [$inst getITerms] {
            set pin [[$iterm getMTerm] getName]
            set net [$iterm getNet]
            if {$net ne "NULL"} {
                if {$pin eq "BOT"} { set bot_net $net }
                if {$pin eq "TOP"} { set top_net $net }
            }
        }
        puts $f "$name,[get_net_pin_coords $bot_net],[get_net_pin_coords $top_net]"
    }
}
close $f

set f_macro [open "$results_dir/export_macro_obstacles.csv" w]
puts $f_macro "MacroName,X_Min,Y_Min,X_Max,Y_Max"
foreach inst [$block getInsts] {
    if { [[$inst getMaster] isBlock] } {
        set bbox [$inst getBBox]
        puts $f_macro "[$inst getName],[$bbox xMin],[$bbox yMin],[$bbox xMax],[$bbox yMax]"
    }
}
close $f_macro
puts "\[INFO\] 边界/拓扑/宏障碍已导出至 $results_dir"

# ============================================================

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
# 3. HBT 搬运（GRT_PREPARE_MOVE=0 时跳过，用于跑 baseline 对照）
# ============================================================
if {$DO_MOVE} {
    set RUNPY [env_on GRT_PREPARE_RUNPY 1]
    set best_loc_file "$results_dir/best_hbt_locations.csv"

    # 已有求解结果时没必要重跑求解器
    if {$RUNPY && [file exists $best_loc_file]} {
        puts "\[INFO\] 复用已有 $best_loc_file，跳过求解器"
        set RUNPY 0
    }

    if {$RUNPY} {
        if {[info exists ::env(GRT_PREPARE_PY)] && $::env(GRT_PREPARE_PY) ne ""} {
          set py_script $::env(GRT_PREPARE_PY)
        } else {
          set py_script "[file dirname [info script]]/optimize_hbts.py"
        }
        if {![file exists $py_script]} {
            puts "\[WARN\] 求解器不存在: $py_script —— 跳过 HBT 搬运（本次结果等同 baseline）"
            set RUNPY 0
        }
    }

    if {$RUNPY} {
        puts "\[INFO\] 调用 Python 求解器: $py_script"
        if {[catch {exec python3 $py_script} py_out]} {
            puts "\[ERROR\] optimize_hbts.py 失败: $py_out"
            error "optimize_hbts.py failed"
        }
        puts $py_out
    }

    set best_loc_file "$results_dir/best_hbt_locations.csv"
    if {[file exists $best_loc_file]} {
        set f [open $best_loc_file r]
        gets $f
        set count 0
        while {[gets $f line] >= 0} {
            lassign [split $line ","] inst_name bx by
            set inst [$block findInst $inst_name]
            if {$inst ne "NULL"} {
                set status [$inst getPlacementStatus]
                $inst setPlacementStatus UNPLACED
                $inst setLocation [expr {int($bx)}] [expr {int($by)}]
                $inst setPlacementStatus $status
                incr count
            }
        }
        close $f
        puts "\[INFO\] 已移动 HBT: $count"
    } else {
        puts "\[WARN\] 未找到 $best_loc_file，未移动任何 HBT"
    }
} else {
    puts "\[INFO\] GRT_PREPARE_MOVE=0，跳过 HBT 移动（baseline 对照）"
}

# ============================================================
# 4. 测量块（仅 GRT_PREPARE_MEASURE=1 执行）
#    注意：本块会跑 global_route 并把 guide 写进测量目录，
#    官方评分跑必须关掉，否则 guide 会被固化进 4_grt_input.odb
# ============================================================
if {$MEASURE} {
    # 0) 自算 HPWL 保底（任何 OpenROAD 版本都能出数，供 before/after 对比）
    prep_step 00_hpwl_selfcheck { self_hpwl_um self_hpwl_um2 }

    # 1) estimate_parasitics -placement   —— 必须在 report_wirelength 之前
    #    候选必须写成嵌套 list：写成 { estimate_parasitics -placement } 会被
    #    foreach 拆成 "estimate_parasitics" 和 "-placement" 两条候选
    prep_step 01_estimate_parasitics { {estimate_parasitics -placement} }

    # 2) report_wirelength               —— 线长报告
    prep_step 02_wirelength {
        report_wirelength
        {grt::report_net_wire_length -global_route}
        {report_layer_wire_lengths 1 0}
    }

    # 3) report_design_metrics
    prep_step 03_design_metrics {
        report_design_metrics
        {report_design_area}
        {report_cell_usage}
    }

    # 4) check_design_rules
    prep_step 04_check_design_rules {
        check_design_rules
        {check_placement -verbose}
        {check_placement}
    }

    # 5) global_route                    —— report_congestion 的前置
    catch { set_congestion_report_file "$MEASURE_DIR/congestion_grt.rpt" }
    prep_step 05_global_route {
        {global_route -allow_congestion -verbose -congestion_iterations 2 -guide_file $MEASURE_DIR/$TAG.guide}
        global_route
    }

    # 6) report_congestion               —— 拥塞报告
    #    本 openroad 构建没有 report_congestion 命令；真正的拥塞数字由
    #    global_route -verbose 打到 stdout（GRT-0096 表），
    #    由 run_grt_measure.sh 直接解析 before.log / after.log
    prep_step 06_congestion {
        report_congestion
        {report_congestion -verbose}
    }

    # 7) report_routing_violations
    #    注意 fields 里不能写 nets（本版本 STA-0168 不认这个字段）
    prep_step 07_routing_violations {
        report_routing_violations
        {check_route}
        {report_checks -path_delay max -fields {slew cap input fanout}}
    }

    puts "\[MEASURE\] 全部报告 -> $MEASURE_DIR"
}

# ============================================================
# 5. 独立模式：自己落盘（官方模式下由 flow 负责 write_db/write_def）
# ============================================================
if {$STANDALONE} {
    write_def "$results_dir/${TAG}_final.def"
    write_db  "$results_dir/${TAG}_final.odb"
    puts "\[BOOT\] 写出 $results_dir/${TAG}_final.{def,odb}"
}

puts "\[PREPARE\] 执行完毕，控制权交还基线流程..."
