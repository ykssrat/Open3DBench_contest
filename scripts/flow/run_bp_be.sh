#!/bin/bash

# 获取脚本所在目录
# 脚本位于 scripts/flow/，向上两级 = 仓库根（input/ output/ reports/ logs/ 均在仓库根）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SCRIPT_DIR"

# 定义当前case
CASE="bp_be"

# 设置输入路径（使用绝对路径）
INPUT="${SCRIPT_DIR}/input/open3dbench_8cases_post_hbt_input_20260724"

# 设置标签
LABEL="baseline"

# ================= 新增：日志记录配置 =================
mkdir -p "${SCRIPT_DIR}/logs"
LOG_FILE="${SCRIPT_DIR}/logs/run_${CASE}.log"
# 将标准输出(stdout)和标准错误(stderr)同时输出到屏幕和日志文件
exec > >(tee -a "$LOG_FILE") 2>&1
# ======================================================

echo "========================================="
echo "脚本目录: $SCRIPT_DIR"
echo "开始运行 case: $CASE"
echo "日志文件: $LOG_FILE"
echo "========================================="
echo "输入路径: $INPUT"
echo "运行标签: $LABEL"
echo "========================================="

# 检查输入目录是否存在
if [ ! -d "$INPUT" ]; then
    echo "错误: 输入目录不存在: $INPUT"
    exit 1
fi

echo "========================================="
echo "运行GRT..."
echo "========================================="
contest run-grt "$CASE" "$INPUT" "$LABEL"

if [ $? -eq 0 ]; then
    echo "GRT运行成功！"
else
    echo "警告: $CASE 的GRT运行可能有问题"
fi

echo "========================================="
echo "评估结果..."
echo "========================================="
contest evaluate     "$CASE"     "$INPUT"     "${SCRIPT_DIR}/output/$CASE/$LABEL"     "${SCRIPT_DIR}/reports/$CASE/$LABEL"

if [ $? -eq 0 ]; then
    echo "$CASE 评估完成！"
else
    echo "警告: $CASE 的评估可能有问题"
fi

echo ""
echo "========================================="
echo "case $CASE 运行完成！"
echo "========================================="
