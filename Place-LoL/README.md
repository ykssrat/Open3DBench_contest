# Place-LoL

`Place-LoL` 是本仓库中的 LoL 工作区，用于两件事：

1. 将通用 3D 基准测试描述转换为 LoL 布局器输入
2. 将 LoL 布局器输出转换为供 `OpenROAD-3D` 使用的标准化 DEF

## 入门

拉取 Docker 镜像（与 Place-MoL 共用，如果在 Place-MoL 已拉取过则无需重复）：

```bash
docker pull shiyunqi/open3dbench:place
```

从 [Google Drive](https://drive.google.com/file/d/1wVYCgee2k7_1JdmV4o6Q4sIgDpoCkAcn/view?usp=sharing) 下载 `benchmarks_lol.tar.gz` 并解压到当前目录：

下载的文件为 `benchmarks_lol.tar.gz`。解压并重命名后，目录应为 `benchmarks/`。

```bash
cd Place-LoL
wget -O benchmarks_lol.tar.gz 'https://drive.google.com/uc?export=download&id=1wVYCgee2k7_1JdmV4o6Q4sIgDpoCkAcn'
tar -xzf benchmarks_lol.tar.gz -C .
mv benchmarks_lol benchmarks
```

从 [Google Drive](https://drive.google.com/file/d/1HHbYQmv12SQ_xUKSnKMVI6RVyX3Z8hPf/view?usp=sharing) 下载 `binaries.tar.gz` 并解压到当前目录：

下载的文件为 `binaries.tar.gz`。解压后目录应为 `binaries/`。

```bash
cd Place-LoL
wget -O binaries.tar.gz 'https://drive.google.com/file/d/1HHbYQmv12SQ_xUKSnKMVI6RVyX3Z8hPf/view?usp=sharing'
tar -xzf binaries.tar.gz -C .
```

从 `Place-LoL` 根目录进入容器：

```bash
cd Place-LoL
./start_docker_place.sh
```

容器内，`Place-LoL` 根目录挂载在 `/workspace`。

## 会用到的文件

```text
Place-LoL/
├── start_docker_place.sh  # 启动 Docker 环境
├── convert_input.sh       # 生成 LoL 输入文件
├── convert_output.sh      # 将布局器原始输出转换为 DEF 文件
├── convert_file.sh        # 上面两个脚本的兼容封装
├── binaries/              # 大赛布局器包、日志、原始输出与转换产物
├── test/                  # default 与 inflated 两个变体的每设计 JSON 配置
├── benchmarks/            # 转换所用的共享基准资源
├── cmake/                 # 转换工具链的 CMake 辅助文件
├── dreamplace/            # 流程用到的 DREAMPlace 相关源码与支撑代码
└── thirdparty/            # 转换与布局工具链的第三方依赖
```

## 变体

支持两种基准变体：

- `default`：默认转换网表，与原始 LEF/DEF 定义一致
- `inflated`：布局时每个单元扩展 5 个 site 宽度（即 `0.95um`），形成更松的布局；对应论文中的 `padded` 设置

它们的 JSON 配置存放在：

- [3D_input_default](./test/3D_input_default)
- [3D_input_inflated](./test/3D_input_inflated)

## 主工作流

**本仓库已包含预生成产物。**

转换后的输入文件已存放在 <u>`binaries/converted_input/`</u>。

每个布局器的运行日志与原始布局输出已存放在该布局器自己的 <u>`logs/`</u> 与 <u>`output/`</u> 目录。

由这些布局器输出转换得到的 DEF 文件已存放在 <u>`binaries/converted_output/`</u>。

**这些 DEF 可直接用于 `OpenROAD-3D` 的评估。**

如需自行复现该流水线，可按以下流程操作。
### 1. 生成 LoL 输入

```bash
cd Place-LoL
bash convert_input.sh <design|iccad_2022_all|iccad_2023_all> <default|inflated> 100
```

这里单位是 `0.01um`，端子尺寸设为 `100`，对应端子尺寸 `1um`、间距 `1um`。

示例：

```bash
bash convert_input.sh aes default 100
bash convert_input.sh bp default 100
bash convert_input.sh iccad_2022_all default 100
bash convert_input.sh iccad_2023_all inflated 100
```

这会在 `binaries/converted_input/` 下生成标准化输入文件。

### 2. 运行 LoL 布局器

在 `binaries/iccad2022/` 或 `binaries/iccad2023/` 中运行所选布局器。

举一个具体例子：本仓库在 [Place-LoL/binaries/iccad2023/tcad25](./binaries/iccad2023/tcad25) 下收录了 `tcad25` 布局器，其再分发获得赵宇轩博士与虞 Bei 教授的授权。该布局器对应论文 [`Analytical Heterogeneous Die-to-Die 3D Placement with Macros`](https://ieeexplore.ieee.org/document/10637265/)，详细用法见 [`tcad25` README](./binaries/iccad2023/tcad25/README.md)。我们衷心感谢两位老师的授权与支持。

示例：

```bash
cd Place-LoL/binaries/iccad2023/tcad25
bash run.sh default
bash run.sh inflated
```

此阶段，每个布局器应把原始结果写入自己的 `output/` 目录。

### 3. 将原始输出转换为 DEF

```bash
cd Place-LoL
bash convert_output.sh <design|iccad2022_all|iccad2023_all> <method> <default|inflated>
```

只能使用匹配的 ICCAD 2022 / ICCAD 2023 组合：

- ICCAD 2022：设计 `aes`、`dynamic_node`、`ibex`、`jpeg`、`swerv`；方法 `cadb1021`、`cadb1051`
- ICCAD 2023：设计 `ariane133`、`ariane136`、`bp`、`bp_be`、`bp_fe`、`bp_multi`、`bp_quad`、`swerv_wrapper`；方法 `cadb0013`、`cadb1038`、`cadb1049`、`tcad25`

示例：

```bash
bash convert_output.sh aes cadb1021 default
bash convert_output.sh iccad2022_all cadb1051 default
bash convert_output.sh ariane133 cadb1038 default
bash convert_output.sh iccad2023_all tcad25 inflated
```

这会把 DEF 文件写入 `binaries/converted_output/`。

## 输出位置

- 生成的 LoL 输入：
  `binaries/converted_input/<variant>/`
- 转换后的 DEF 输出：
  `binaries/converted_output/<variant>/<method>/`

示例：

- `binaries/converted_input/default/aes.input`
- `binaries/converted_input/default/bp_quad.input`
- `binaries/converted_output/default/cadb1021/aes.def`
- `binaries/converted_output/default/cadb1038/ariane133.def`
- `binaries/converted_output/inflated/tcad25/bp.def`

## LoL 评估

`Place-LoL` 不做最终评估。DEF 转换完成后，最终输出为：

```text
Place-LoL/binaries/converted_output/<variant>/<method>/*.def
```

这些 DEF 之后由 `OpenROAD-3D` 消费，用于后端实现与评估。

因此完整流程是：

1. 在 `Place-LoL` 生成 LoL 输入
2. 在 `binaries/` 运行 LoL 布局器
3. 在 `Place-LoL` 把输出转换为 DEF
4. 在 `OpenROAD-3D` 评估这些 DEF

## 备注

- 大赛专用的评估器辅助脚本与各布局器说明见：
  [iccad2022](./binaries/iccad2022/README.md)
  [iccad2023](./binaries/iccad2023/README.md)