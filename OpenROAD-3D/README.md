# OpenROAD-3D 评估流程

本目录包含以下 3D 后端评估流程：

- `lol`：logic-on-logic（LoL）集成，布局由 ICCAD 2022/2023 大赛二进制提供
- `mol-analytical`：memory-on-logic（MoL）集成，布局由我们提出的 mol-analytical 布局方法提供
- `mol-tiling`：memory-on-logic（MoL）集成，布局由我们提出的 mol-tiling 布局方法提供

以下命令均应在 `OpenROAD-3D/flow` 目录下执行。

## Docker

拉取评估镜像：

```bash
docker pull shiyunqi/open3dbench:eval
```

从 [start_docker_eval.sh](./start_docker_eval.sh) 启动评估容器：

```bash
cd OpenROAD-3D
./start_docker_eval.sh
```

该脚本是 LoL 与 MoL 共用的评估入口。它分别挂载 `OpenROAD-3D` 与 `Place-LoL`，并在容器内导出 `PLACE_LOL_ROOT=/workspace/Place-LoL`，使 LoL 配置可以从 `Place-LoL/binaries/converted_output/...` 读取 DEF。

## 目录结构

```text
OpenROAD-3D/
└── flow/
    ├── run_lol_iccad2022.sh              # 对 ICCAD 2022 布局器跑 OpenROAD + HotSpot 的 LoL 评估流程
    ├── run_lol_iccad2023.sh              # 对 ICCAD 2023 布局器跑 OpenROAD + HotSpot 的 LoL 评估流程
    ├── run_mol_analytical.sh              # mol-analytical 的完整后端实现 + HotSpot 流程
    ├── run_mol_tiling.sh                  # mol-tiling 的完整后端实现 + HotSpot 流程
    ├── export_mol_defs_from_place_mol.sh  # 将 Place-MoL 生成的 DEF 拷贝到单独的评估包目录
    ├── evaluation_pack/                   # 复现论文原始结果的标准 DEF 输入
    └── evaluation_pack_custom/            # 从 Place-MoL 导出的可选自定义 DEF 输入
```

## LoL 评估

`OpenROAD-3D` 直接从 `Place-LoL` 读取 LoL DEF。LoL 设计配置使用：

```text
Place-LoL/binaries/converted_output/<variant>/<method>/*.def
```

其中：

- `variant` 为 `default` 或 `inflated`
- `method` 为所选布局器名称，如 `cadb1021`、`cadb1038`、`tcad25`

如果直接使用 `Place-LoL` 中已包含的预生成产物，无需复现 LoL 布局流程即可直接评估。

典型命令：

```bash
cd OpenROAD-3D/flow
./run_lol_iccad2022.sh <default|inflated> <method>
./run_lol_iccad2023.sh <default|inflated> <method>
```

使用 `tcad25` 布局器的示例：

```bash
cd OpenROAD-3D/flow
./run_lol_iccad2023.sh default tcad25
```

如果要自行复现完整 LoL 流水线，请先按 `Place-LoL` 中的步骤：

1. 在 `Place-LoL` 中生成 LoL 输入
2. 在 `Place-LoL/binaries/` 中运行某个 LoL 布局器
3. 在 `Place-LoL` 中把布局器输出转换为 DEF
4. 在 `OpenROAD-3D` 中评估所得 DEF

### LoL 输出

LoL 评估的最终实验日志归档在：

- `logs/nangate45_3D/<design>/<method>_<variant>/`

中间工作目录创建在：

- `logs/nangate45_3D/<design>/lol/`
- `results/nangate45_3D/<design>/lol/`

归档目录包含运行日志与拷贝出来的评估产物（如生成的 PNG 和 HotSpot 输出，若存在）。
## MoL 评估

MoL 实验有两种提供 DEF 的方式。

### 方式一：使用打包好的评估 DEF

如需复现论文报告的结果，先从 [Google Drive](https://drive.google.com/file/d/19ypJmK_8yvWz7MN-qbyokmuoW0faEekm/view?usp=sharing) 下载 `evaluation_pack.tar.gz`，解压到 `OpenROAD-3D/flow` 下作为 `evaluation_pack/`：

```bash
cd OpenROAD-3D/flow
wget -O evaluation_pack.tar.gz 'https://drive.google.com/uc?export=download&id=19ypJmK_8yvWz7MN-qbyokmuoW0faEekm'
tar -xzf evaluation_pack.tar.gz
```

运行脚本从以下位置读取 DEF：

- `evaluation_pack/mol-analytical/*.def`
- `evaluation_pack/mol-tiling/*.def`

如需复现论文报告的结果，无需额外步骤即可直接运行：

```bash
cd OpenROAD-3D/flow
./run_mol_analytical.sh
./run_mol_tiling.sh
```

两个脚本默认均指向 `evaluation_pack`。

### 方式二：使用 Place-MoL 生成的 DEF

`Place-MoL` 可在以下位置生成最终 DEF：

- `Place-MoL/results/mol-analytical/mol_final/<design>_suffixed.def`
- `Place-MoL/results/mol-tiling/mol_final/<design>_suffixed.def`

OpenROAD 的 mol 脚本不直接读取这些文件，而是从磁盘上的某个包根目录读取。默认包根是 `evaluation_pack/`，也可以指向单独的自定义包（如 `evaluation_pack_custom/`）。

如果走自定义 DEF 流程，则无需下载 `evaluation_pack.tar.gz`。

为避免覆盖标准的可复现输入，导出脚本默认写入 `evaluation_pack_custom/`。因此推荐流程为：

1. 按 `Place-MoL` 的说明生成自定义 MoL DEF。
2. 将生成的 DEF 导出到 `OpenROAD-3D/flow/evaluation_pack_custom/<method>/`。
3. 以 `evaluation_pack_custom` 为包根运行 OpenROAD 评估流程。

示例：

```bash
cd OpenROAD-3D/flow
./export_mol_defs_from_place_mol.sh mol-analytical
./run_mol_analytical.sh evaluation_pack_custom
```

```bash
cd OpenROAD-3D/flow
./export_mol_defs_from_place_mol.sh mol-tiling
./run_mol_tiling.sh evaluation_pack_custom
```

### MoL 输出

MoL 评估的最终实验日志归档在：

- `logs/nangate45_3D/<design>/mol-analytical/`
- `logs/nangate45_3D/<design>/mol-tiling/`

中间工作目录创建在：

- `logs/nangate45_3D/<design>/mol/`
- `results/nangate45_3D/<design>/mol/`

归档目录包含运行日志与拷贝出来的评估产物（如生成的 PNG 和 HotSpot 输出，若存在）。