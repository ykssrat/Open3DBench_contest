# 2026 EDA 精英挑战赛：时序驱动与 HB 布局协同的面对面键合 3D-IC 三维全局布线

本仓库提供"2026 中国研究生创芯大赛·EDA 精英挑战赛"的公开代码、基准测试接口与基线方案。

赛题中文名称：**时序驱动与 HB 布局协同的面对面键合 3D-IC 三维全局布线方法**

English title: **Timing-Driven 3D Global Routing with Hybrid Bonding Co-Optimization for Face-to-Face-Bonded 3D-IC**

## 1. 赛题说明

参赛者需要联合优化：金属层共享（Metal Layer Sharing）的线网选择与子网分配、HBT 增量布局、以及时序驱动的三维全局布线。提交的算法必须产出一个布线完成的 OpenDB 数据库，其中包含最终的全局布线 guide、HBT 布局以及线网/子网连接关系。

## 2. 快速开始

拉取比赛镜像并克隆 `EDA_contest` 分支：

```bash
docker pull gaocr/3dbench-contest:20260914

git clone --branch EDA_contest --single-branch \
  https://github.com/lamda-bbo/Open3DBench.git
cd Open3DBench
```

解压第 4 节给出的发布包，将其中的输入压缩包放入本仓库的 `input/` 目录并解包：

```bash
mkdir -p input
tar -xzf \
  input/open3dbench_8cases_post_hbt_input_20260724.tar.gz \
  -C input
```

从仓库根目录启动比赛容器：

```bash
./start_contest_docker.sh
```

后续所有命令都在该容器内执行。用 32 个并行编译任务编译 GRT 基线，然后跑 `bp_fe`：

```bash
contest build 32

INPUT=/workspace/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724
contest run-grt bp_fe "$INPUT" baseline
```

运行固定的 DRT / DRC / 时序评测器：

```bash
contest evaluate \
  bp_fe \
  "$INPUT" \
  /workspace/Open3DBench/output/bp_fe/baseline \
  /workspace/Open3DBench/reports/bp_fe/baseline
cat reports/bp_fe/baseline/metrics.json
```

替换 `bp_fe` 与 `baseline` 即可运行其他用例或保留多组实验输出。GRT 结果存放在 `output/`，评测报告存放在 `reports/`。

批量跑流程与出报告的脚本已收进 `scripts/`，逐个说明见 [docs/SCRIPTS.md](docs/SCRIPTS.md)。

## 3. 仓库与基线

```text
Open3DBench/
├── OpenROAD-GRT/       # 加入 3D GRT 基线的 OpenROAD 修改版
│   ├── openroad_src/   # OpenROAD src/grt 源码
│   └── flow_scripts/   # GRT 与布线后 HBT 转换脚本
├── OpenROAD-3D/        # 基于 OpenROAD 的 3D 后端流程
├── Place-MoL/
└── Place-LoL/
```

所提供的基线是可复现的开发起点：它对输入设计中已有的 HBT 实例与 _BOT/_TOP 子网布线，不引入额外的金属层共享线网。
### 3.1 受限的 die-by-die GRT 基线

提供的 OpenROAD 源码为 `GlobalRouter` 增加了按线网设置的布线层范围，并将其传入 FastRoute。允许的层范围在拓扑生成、资源统计、迷宫扩展与布线重构阶段都会被强制执行，因此 die 内的线网不能把对侧 die 的金属层当作拥塞兜底。HBT 引脚作为布线端点保留，可被布线器自然处理。

### 3.2 多趟运行

1. 将输入线网划分为下 die 与上 die 子网。
2. 在相互隔离的 OpenROAD 进程中，对下 die 子网用 `metal2-metal10`、上 die 子网用 `metal11-metal20` 布线。
3. 合并两份标准 guide 结果并导入最终的 `5_1_grt.odb`。

### 3.3 HBT 与子网命名

已有 HBT 实例保留以 `HBT_` 开头的名字。金属层共享新增的 HBT 实例必须命名为 `LS_HBT_<id>`，其中 `<id>` 唯一标识每个 HBT。由原线网派生的子网必须命名为 `<original_net>__MLS__S<id>__BOT` 或 `<original_net>__MLS__S<id>__TOP`；`<original_net>` 为原线网的准确名字，`S<id>` 唯一标识由它派生的每个子网。

## 4. 输入与输出文件

从 [Google Drive 发布包](https://drive.google.com/file/d/1BvkJXGITgEXt2EHV_bVx3Fz9HOedyWXk/view?usp=sharing)下载，其中包含输入、基线源码与 Docker 镜像。解压 `Open3DBench-offline-20260915.tar.gz` 后，输入压缩包位于：

```text
Open3DBench-offline-20260915/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724.tar.gz
```

输入使用 6.4 um 的 HBT pitch、3.0 欧姆 HBT 串联电阻、0.6 fF 的 HBT 总电容。

输入压缩包 SHA-256：
`d27c12edb98bbda2c250f879b46361bce5d1d574f69b9bb2aec68c6049f6af2b`

```text
open3dbench_8cases_post_hbt_input_20260724/
├── README.txt
├── MANIFEST.sha256
├── cases/<case>/
│   ├── grt_input/
│   └── flow_design/
└── platforms/nangate45_3D/
```

### 4.1 每用例输入

| 文件 | 描述的信息 |
|---|---|
| `cases/<case>/grt_input/4_1_cts.def` | die 区域、row 与 track、布局、引脚与线网 |
| `cases/<case>/grt_input/4_cts.sdc` | 时钟、时钟不确定度、I/O 延迟、时序例外及其他与 CTS 设计相关的时序约束 |
| `cases/<case>/flow_design/config*.mk` | 用例的设计名、平台选择、源文件路径、布线层、利用率目标与流程参数 |
| `cases/<case>/flow_design/*.sdc` | 原始时钟与时序约束 |
| `cases/<case>/flow_design/*.v` 与 `*.sv2v.v` | Verilog 模块 |
| `cases/<case>/flow_design/fastroute.tcl` | 全局布线设置 |

### 4.2 平台输入

| 文件 | 描述的信息 |
|---|---|
| `platforms/nangate45_3D/config.mk` | 平台文件位置、布线层定义、RC 设置与默认物理设计参数 |
| `platforms/nangate45_3D/lef*/**.lef` | 制造网格、布线层与 cut 层、track、via、设计规则、标准单元/宏单元几何与引脚形状 |
| `platforms/nangate45_3D/lib*/**.lib` | 单元与宏单元的时序弧、延迟、约束、电容、转换与功耗模型 |
| `platforms/nangate45_3D/setRC.tcl` 与 `nangate45_3D.rules` | 用于时序评估的线/via 阻容设置与提取规则 |
| `platforms/nangate45_3D/fastroute.tcl`、`make_tracks.tcl`、`grid_strategy*.tcl` | 默认布线层调整、布线 track 定义与电源网格设置 |
| `platforms/nangate45_3D/gds/`、`cdl/`、`drc/` | 版图几何、晶体管级连接与物理验证规则文件 |

输入 DEF 定义了可复现的基线设计状态。比赛算法可以在协同优化中修改 HBT 布局与子网连接，但所有非 HBT 元件的布局必须保持不变。

评测器将每个 HBT 建模为 3.0 欧姆串联电阻加 0.6 fF 总对地电容。该电容在提取出的 HBT 电阻的 metal10 与 metal11 两个端子上均分。

### 4.3 必需输出

| 文件 | 包含的信息 |
|---|---|
| `5_1_grt.odb` | 最终 OpenDB 数据库，包含元件布局、优化后的 HBT 布局、线网/子网连接与全局布线 guide |

DRT 之前，评测器会从 `5_1_grt.odb` 重新生成规范化 DEF 与布线 guide，然后检查：

- 所有非 HBT 元件布局与封装引脚是否保持不变；

- 折叠 HBT 连接后逻辑网表是否等价；

- HBT 合法性；

- 全局布线 guide 合法性（不得跨 die）。

## 5. 基线结果

下表为现有八个用例的基线布线结果，由 3D GRT 基线加两轮详细布线优化（`droute_end_iter=2`）产生。TNS 与 WNS 为用所提供的评测器与时序约束在这些布线数据库上重新评估的 setup 时序指标。所有用例均使用 6.4 um HBT pitch、3.0 欧姆电阻与 0.6 fF 总电容。

| 用例 | HBT 数 / 30% 容量 | DRT-WL (um) | DRC | TNS (ns) | WNS (ns) |
|---|---:|---:|---:|---:|---:|
| `ariane133` | 4,025 / 7,300 | 5,678,764.46 | 15,276 | -21,178.44 | -4.57280 |
| `ariane136` | 4,046 / 7,300 | 5,667,695.84 | 15,964 | -6,130,643.00 | -381.76276 |
| `black_parrot` (`bp`) | 3,847 / 5,880 | 7,813,311.28 | 18,874 | -186,047.55 | -20.44161 |
| `bp_fe` | 1,149 / 1,729 | 1,378,685.12 | 4,257 | -8,828.74 | -4.00944 |
| `bp_be` | 1,105 / 2,176 | 2,368,525.41 | 8,099 | -6,886.91 | -4.32408 |
| `bp_multi` | 3,072 / 4,687 | 3,883,744.71 | 13,778 | -90,280.86 | -15.93247 |
| `swerv_wrapper` | 1,278 / 4,087 | 3,723,936.61 | 15,382 | -1,873.56 | -1.55317 |
| `bp_quad` | 27,835 / 45,630 | 41,694,313.23 | 23,862 | -1,716,879.50 | -113.96867 |