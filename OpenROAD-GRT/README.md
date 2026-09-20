# OpenROAD 3D GRT 基线方案

本目录包含可修改的 OpenROAD 全局布线（GRT）基线方案，是修改 3D GRT 算法、开发金属层共享策略的主要开发区域。

## 1. OpenROAD 源文件

以下文件均相对于 `openroad_src/`。

| 文件 | 在全局布线中的作用 |
|---|---|
| `src/grt/include/grt/GlobalRouter.h` | 声明顶层全局路由器，包括其配置、布线状态、guide 输入输出、增量布线、拥塞与报告接口。 |
| `src/grt/src/GlobalRouter.cpp` | 实现 GRT 主流程：基于 OpenDB 构建布线网格与容量，创建线网与引脚模型，调用布线引擎，并将结果转换为布线 guide。 |
| `src/grt/src/GlobalRouter.{i,tcl}` | 定义 Tcl/SWIG 命令接口、参数检查，以及用于配置和运行全局布线的用户封装命令。 |
| `src/grt/src/Pin.h` | 定义布线端点模型，包括引脚几何形状、布线层、物理位置与网格位置，以及用于选择访问点的属性。 |
| `src/grt/src/fastroute/include/DataType.h` | 定义 FastRoute 的核心数据结构：线网、网格边、布线树、线段与迷宫布线路径。 |
| `src/grt/src/fastroute/include/FastRoute.h` | 声明 FastRoute 布线引擎及其 API，涵盖网格构建、拓扑生成、拥塞优化、层分配与布线结果提取。 |
| `src/grt/src/fastroute/src/{FastRoute.cpp,utility.cpp}` | 实现 FastRoute 流水线，包括线网初始化、布线资源统计、Steiner 拓扑处理、拥塞驱动的拆线重布、层分配与线段生成。 |

源码层面的主要扩展是：

```tcl
set_net_routing_layers <net_name> <min_layer> <max_layer>
```

这是一条硬性按线网约束。受限制的线网不能把另一个裸片（die）的金属层当作拥塞兜底资源使用。

基线方案可选择性地先运行 `GRT_PREPARE_TCL` 来更新 HBT 布局或子网连接关系，然后把选定的输入设计划分为下裸片（bottom die）和上裸片（upper die）的线网清单。它在两个相互隔离的 OpenROAD 进程中分别布线这两套金属叠层：下裸片线网使用 `metal2-metal10`，上裸片线网使用 `metal11-metal20`。两份 guide 文件会被合并为 `route.guide` 并载入 `5_1_grt.odb`；最终检查会校验层归属、端点覆盖与 guide 连通性，且不会修改布线结果。

## 3. GRT 超参数

以下环境变量用于控制基线方案。默认值定义在 `flow_scripts/scripts_3D/global_route_die_by_die.tcl`。

| 变量 | 默认值 | 含义 |
|---|---:|---|
| `BOTTOM_DIE_MIN_LAYER` | `metal2` | 下裸片布线过程中的最低信号布线层。 |
| `BOTTOM_DIE_MAX_LAYER` | `metal10` | 下裸片布线过程中的最高信号布线层。 |
| `UPPER_DIE_MIN_LAYER` | `metal11` | 上裸片布线过程中的最低信号布线层。 |
| `UPPER_DIE_MAX_LAYER` | `metal20` | 上裸片布线过程中的最高信号布线层。 |
| `GLOBAL_ROUTING_LAYER_ADJUSTMENT` | `0.5` | 作用于当前生效层区间的容量调整系数。 |
| `GLOBAL_ROUTE_ARGS` | `-congestion_iterations 2 -congestion_report_iter_step 5 -verbose` | 每次调用 `global_route` 时传入的参数。 |
| `MACRO_EXTENSION` | platform setting | 可选的宏单元阻塞扩展量，单位为 GCell。 |
| `VALIDATE_DIE_GUIDES` | `1` | 仅当需要跳过合并 guide 校验时才设为 `0`。 |
| `DIE_GUIDE_MAX_CC_RECTS` | `5000` | 严格连通性诊断使用的矩形数量上限。 |
| `OPENROAD_EXE` | `openroad` | 用于隔离执行上裸片布线与收尾流程的 OpenROAD 可执行文件。 |
| `GRT_PREPARE_TCL` | unset | 可选的一次性 HBT 布局与网表准备脚本。 |

`GRT_PASS_NET_LIST`、`GRT_PASS_GUIDE_OUT`、`GRT_PASS_MIN_LAYER` 和 `GRT_PASS_MAX_LAYER` 是由主 Tcl 脚本设置的内部过程变量，不属于常规的调参项。

覆盖示例：

```bash
export GLOBAL_ROUTING_LAYER_ADJUSTMENT=0.5
export GLOBAL_ROUTE_ARGS="-congestion_iterations 4 -congestion_report_iter_step 2 -verbose"
```

## 4. 构建与运行

以下命令均在仓库根目录下执行。容器环境搭建与输入数据下载参见顶层 `README.md`。

启动环境：

```bash
./start_contest_docker.sh
```

其余命令都在容器内执行。使用 32 个构建任务编译 OpenROAD GRT overlay：

```bash
contest build 32
```

在 `bp_fe` 上运行基线方案：

```bash
INPUT=/workspace/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724
contest run-grt bp_fe "$INPUT" baseline
```

如需保留多份配置，可修改运行标签（例如改为 `baseline_c4`）。`openroad_src/` 下的 C++ 改动需要重新执行 `contest build`；Tcl 与 Python 流程改动会在下一次准备好的运行中直接生效。

固定评估器可按如下方式消费 GRT 输出：

```bash
contest evaluate \
  bp_fe \
  "$INPUT" \
  /workspace/Open3DBench/output/bp_fe/baseline \
  /workspace/Open3DBench/reports/bp_fe/baseline
```

## 5. 脚本执行顺序

| 顺序 | 脚本 | 用途 |
|---:|---|---|
| 1 | `flow_scripts/scripts/global_route_die_by_die.tcl` | 与流程兼容的入口脚本。 |
| 2 | `scripts_3D/global_route_die_by_die.tcl` | 载入设计、导出线网清单，并运行两次裸片布线。 |
| 3 | `scripts_3D/global_route_single_pass.tcl` | 运行隔离的上裸片布线过程。 |
| 4 | `scripts_3D/merge_route_guides.py` | 直接拼接两套标准 guide，不改动任何矩形。 |
| 5 | `scripts_3D/check_2d_net_guide_layers.py` | 校验各裸片内部的层归属。 |
| 6 | `scripts_3D/diagnose_guide_connectivity.py` | 检查严格的 guide 与端点连通性。 |
| 7 | `scripts_3D/finalize_die_by_die_grt.tcl` | 读取合并后的 guide 并写出已布线的 ODB。 |

## 6. 原始输出

| 输出 | 说明 |
|---|---|
| `die_net_lists/{bottom_2d,upper_2d,special}.txt` | 两次布线过程使用的线网分类结果。 |
| `4_grt_input.{odb,def}` | 可选的共享快照，仅在设置了 `GRT_PREPARE_TCL` 时生成。 |
| `route_bottom.guide` | 下裸片的原始 guide 文件。 |
| `route_upper.guide` | 上裸片的原始 guide 文件。 |
| `route.guide` | 提交给下一布线阶段的合并 guide。 |
| `5_1_grt.odb` | 包含合并后全局布线 guide 的 OpenDB 数据库。 |
| `congestion_{bottom,upper}.rpt` | 下裸片与上裸片布线过程各自的拥塞报告。 |
| `grt_pass_upper.log`, `grt_finalize.log` | 隔离布线过程与收尾流程的日志。 |
