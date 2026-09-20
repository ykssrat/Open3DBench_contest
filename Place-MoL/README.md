# Place-MoL

Open3DBench 中的 memory-on-logic（MoL）布局流程。本仓库覆盖面对面 3D 集成中 MoL 流程的布局部分：下 die 主要放逻辑，上 die 放存储宏单元。它读入基准用例，产出可随后在 `OpenROAD-3D` 中评估的 MoL 布局结果。

主流程支持：

- **划分（Partition）**：用 `GNN`、`min-cut` 或 `max-cut` 把宏单元划分到上、下两个 die
- **宏布局**：要么用以线长优先的解析式伪 3D 方法，要么用以规整性优先的平铺（tiling）方法
- **合法化**：连续或贪心布局之后做基于网格的宏合法化
- **单元布局**：基于 DREAMPlace 的下 die 单元布局，上 die 宏单元投影为固定障碍

方法命名：

- `mol-analytical` 对应解析式伪 3D 宏布局策略
- `mol-tiling` 对应基于平铺的宏布局策略

## 目录结构

```text
Place-MoL/
├── benchmarks/              # 3D 流程运行所需的基准数据
│   ├── nangate45/           # LEF/LIB 及相关工艺文件
│   └── or_3D/               # 3D 基准用例输入
├── config/                  # 3D JSON 配置
├── scripts/                 # 入口脚本
├── src/                     # 3D 布局代码
├── DREAMPlace/              # DREAMPlace 子模块 / 构建树
└── start_docker_place.sh    # Docker 启动脚本
```

## 安装

### 1. 获取 Docker 镜像

（与 Place-LoL 共用，如果在 Place-LoL 已拉取过则无需重复）

```bash
docker pull shiyunqi/open3dbench:place
```

### 2. 获取基准数据

从 [Google Drive](https://drive.google.com/file/d/1RXBa9W5b28w_sv0u6hjv4-57EDpPo7xK/view?usp=sharing) 下载 `benchmark_mol.tar.gz` 并解压到当前目录：

下载的文件为 `benchmark_mol.tar.gz`。解压并重命名后，目录应为 `benchmarks/`。

```bash
cd Place-MoL
wget -O benchmark_mol.tar.gz 'https://drive.google.com/uc?export=download&id=1RXBa9W5b28w_sv0u6hjv4-57EDpPo7xK'
tar -xzf benchmark_mol.tar.gz -C .
mv benchmark_mol benchmarks
```

### 3. 启动容器

从 `Place-MoL` 根目录运行：

```bash
cd Place-MoL
./start_docker_place.sh
```

容器内，`Place-MoL` 根目录挂载在 `/workspace`。

## 用法

以下命令均应在 `Place-MoL` 根目录下执行。
在 Docker 内，即从 `/workspace` 执行。

### 解析式 MoL

```bash
python src/place_3d/main.py --benchmark=<benchmark> --seed=3 --config_file=<config_json>
```

示例：

```bash
python src/place_3d/main.py --benchmark=ariane133 --seed=3 --config_file=or_3D.json
python src/place_3d/main.py --benchmark=bp_quad --seed=3 --config_file=or_3D_bp_quad.json
python src/place_3d/main.py --benchmark=bp_be --seed=3 --config_file=or_3D_bp_be.json
python src/place_3d/main.py --benchmark=swerv_wrapper --seed=3 --config_file=or_3D_swerv.json
```

该流程构建 2D 原型、细化下 die 宏位置并合法化、优化上 die 宏坐标并再次合法化，最后做下 die 单元布局。
### 平铺 MoL

```bash
python src/place_3d/main_greedy.py --benchmark=<benchmark> --seed=3 --config_file=<config_json>
```

示例：

```bash
python src/place_3d/main_greedy.py --benchmark=ariane133 --seed=3 --config_file=or_3D.json
python src/place_3d/main_greedy.py --benchmark=bp_quad --seed=42 --config_file=or_3D_bp_quad.json
```

与解析式流程相比，该方法使用 skyline 式装箱过程得到更规整的宏布局，然后做下 die 单元布局。

### 批量实验

解析式布局流程：

```bash
./scripts/experiments_mol_analytical.sh
```

平铺布局流程：

```bash
./scripts/experiments_mol_tiling.sh
```

这些脚本会：

- 在 `DREAMPlace/build/` 下构建 DREAMPlace
- 将 DREAMPlace 安装到 `DREAMPlace/install/`
- 运行所选的 3D 基准用例

运行后，生成的输出写在 `results/`，临时构建树重建于 `DREAMPlace/build/`。

## 流水线

### `mol-analytical`

`src/place_3d/main.py`

1. 将宏单元划分到上、下 die
2. 生成 2D 原型布局
3. 细化下 die 宏布局
4. 下 die 宏合法化
5. 上 die 宏布局
6. 上 die 宏合法化
7. 固定宏单元后做单元布局
8. 单元合法化

### `mol-tiling`

`src/place_3d/main_greedy.py`

1. 将宏单元划分到上、下 die
2. 贪心 skyline 上 die 宏布局
3. 贪心 skyline 下 die 宏布局
4. 固定宏单元后做单元布局
5. 单元合法化

## 配置

配置文件在 `config/` 下。

可用配置：

- `or_3D.json`
- `or_3D_bp_quad.json`
- `or_3D_bp_be.json`
- `or_3D_bp_fe.json`
- `or_3D_swerv.json`

配置用法：

- `or_3D.json` 是通用用例的默认配置
- 专用配置仅用于上面列出的特殊用例

关键选项：

- `partition_params.method`：`GNN`、`min-cut` 或 `max-cut`
- `partition_params.GNN`：GNN 训练超参数
- `enable_bottom_die_refinement`：启用/关闭下 die 细化
- `macro_refine_params`：主流程细化设置
- `macro_place_params`：宏布局设置
- `macro_legalize_params`：合法化设置

## 输出

结果写在 `results/` 下。

典型输出目录：

- `results/mol-analytical/`
- `results/mol-analytical-min-cut/`
- `results/mol-analytical-max-cut/`
- `results/mol-tiling/`
- `results/mol-tiling-min-cut/`
- `results/mol-tiling-max-cut/`

典型最终文件：

- `mol_final/<design>_suffixed.def`
- `mol_final/<design>_legalized.png`
- `mol_final/mem_on_logic_results.csv`

这些 DEF 是 MoL 布局输出，之后由 `OpenROAD-3D` 消费，用于布线、时序分析与热评估。