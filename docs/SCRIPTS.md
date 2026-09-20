# 脚本说明（scripts/）

根目录的脚本已按职责归类到 `scripts/` 下两类，本文件逐个说明它们的作用与用法。

```
scripts/
├── flow/       批处理 / 流程驱动（跑 GRT、跑评测、做前后对比测量）
└── analysis/   结果分析（把工具输出解析成可读报告）
```

## 通用约定

- 所有脚本用 `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"` 定位**仓库根**，
  因此 `input/`、`output/`、`reports/`、`logs/` 永远解析到仓库根——脚本可以从任意目录调用，不用先 `cd` 回根目录。
- 容器内仓库根固定挂载在 `/workspace/Open3DBench`（见根目录 `start_contest_docker.sh`），
  所以脚本里出现的 `/workspace/Open3DBench/...` 是**容器内路径**，在宿主机上不要照抄。
- 每个脚本启动即把 stdout/stderr 同时 `tee` 进 `logs/`，跑挂了先看日志。

## scripts/flow/ —— 批处理 / 流程驱动

| 脚本 | 作用 |
| --- | --- |
| `run_<case>.sh` | 单用例一键驱动：`contest run-grt` + `contest evaluate`，`LABEL=baseline` |
| `run_bp_fe_opt.sh` | `bp_fe` 的 HBT 优化版驱动，`LABEL=baseline_hbt_opt` |
| `run_all_cases.sh` | 串行跑完 8 个用例（每个都 run-grt + evaluate） |
| `run_grt_measure.sh` | HBT 重布局**前后**的线长 / 拥塞对比测量工具 |
| `generate.sh` | 重新生成上面那 8 个 `run_<case>.sh` 模板 |

### `run_<case>.sh`（`ariane133` `ariane136` `bp` `bp_be` `bp_fe` `bp_multi` `bp_quad` `swerv_wrapper`）

单个用例的基线跑法：读 `input/open3dbench_8cases_post_hbt_input_20260724`，跑 GRT 再跑评测。

- 产物：`output/<case>/baseline/`、`reports/<case>/baseline/metrics.json`
- 日志：`logs/run_<case>.log`
- 用法：`scripts/flow/run_bp_fe.sh`（容器里则是 `/workspace/Open3DBench/scripts/flow/run_bp_fe.sh`）

8 个脚本内容同构，只有 `CASE=` 一行不同；`generate.sh` 就是用来批量产出它们的。

### `run_bp_fe_opt.sh`

在 `bp_fe` 上挂载 HBT 优化算法再跑同一条流程，用来和 `run_bp_fe.sh` 的基线结果对比：

- `GRT_PREPARE_TCL` = `OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt/grt_prepare.tcl`（HBT 搬运 + 求解钩子）
- `RESULTS_DIR` = `<仓库根>/measure_run_bp_fe`（必须与 tcl 里的 `results_dir` 一致，否则搬运阶段读不到求解结果）
- `GRT_PREPARE_REUSE=0`：每次强制重算，不复用上一版 `best_hbt_locations.csv`
- 产物落在 `output/bp_fe/baseline_hbt_opt/` 与 `reports/bp_fe/baseline_hbt_opt/`

### `run_all_cases.sh`

串行遍历 8 个用例，每个都跑 `contest run-grt` + `contest evaluate`。

- 全局日志：`logs/run_all_<YYYYmmdd_HHMMSS>.log`；每用例另有 `logs/<case>.log`
- 适合跑全量回归，单用例调试请用对应的 `run_<case>.sh`

### `run_grt_measure.sh`

不进 `contest` 流程，直接调 `openroad` 跑 `grt_prepare.tcl`，测量 **HBT 重布局前后** 的线长与拥塞，输出对照数据。

- 依赖：`grt_prepare.tcl`（必须，找不到就报 FATAL）、`optimize_hbts.py`（可选，缺了就跳过求解、只跑基线）
- 默认输出目录：`<仓库根>/measure_run_<case>/`
- 常用参数：`-c` 用例（默认 `bp_fe`）、`-i` 输入包、`-o` 输出目录、`-r` openroad 路径、`-t` tcl 路径、`-y` 求解器路径、`-p` 平台（默认 `nangate45_3D`）、`-b` 只跑 before、`-h` 帮助
- 也可用环境变量：`CASE` / `OPEN3D_INPUT` / `OPENROAD_BIN` / `PLATFORM` / `PYTHON` / `GRT_TCL` / `GRT_PYOPT`

### `generate.sh`

按内置 `CASES` 列表重新生成 8 个 `run_<case>.sh`（写进 `scripts/flow/` 自身所在目录）。日常跑流程不需要它，只有在改模板或新增用例时才用。

## scripts/analysis/ —— 结果分析出报告

### `analyze_drc.py`

解析 OpenROAD 的 DRC 报告文本，产出两类统计文件（**落在当前工作目录**）：

- `drc_report_<prefix>.txt`：总违规数、按类型 × 层次的分布、Top-20 最常出错的 net
- `drc_details_<prefix>.csv`：逐条违规明细（`type, srcs, layer, bbox`）

用法：

```bash
python3 scripts/analysis/analyze_drc.py <drc_report.txt> [output_prefix]
```

## 仍在根目录的脚本

这两个是赛方/docker 入口，被 `README.md` 与官方流程按根路径引用，因此**不挪**：

- `start.sh`：校验并 `docker load` 赛方镜像（`docker/3dbench-contest_20260915.tar.gz`，带 sha256 校验），然后 `exec start_contest_docker.sh`
- `start_contest_docker.sh`：拉起比赛容器，把仓库根挂到容器内 `/workspace/Open3DBench`，把 `OpenROAD-GRT` 只读挂成 `OpenROAD-GRT-HBT`

## 目录产物对照

| 目录 | 内容 |
| --- | --- |
| `input/` | 赛方输入包（解包后 `open3dbench_8cases_post_hbt_input_20260724/`） |
| `output/` | `contest run-grt` 的结果，`<case>/<label>/` |
| `reports/` | `contest evaluate` 的评测报告，`<case>/<label>/metrics.json` |
| `logs/` | 各驱动脚本的运行日志 |
| `measure_run_<case>/` | `run_grt_measure.sh` 的前后对比测量产物、求解器输入导出 |
