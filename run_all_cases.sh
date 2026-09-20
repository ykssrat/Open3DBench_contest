#!/bin/bash

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ================= 新增：全局日志配置 =================
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"
# 全局日志文件名带时间戳，防止多次运行被覆盖
GLOBAL_LOG="${LOG_DIR}/run_all_$(date +%Y%m%d_%H%M%S).log"
# 将后续所有的标准输出和标准错误同时输出到屏幕和全局日志
exec > >(tee -a "$GLOBAL_LOG") 2>&1
echo "========================================="
echo "全局日志已开启: $GLOBAL_LOG"
echo "========================================="
# ==================================================

# 定义所有cases
CASES=(
    "ariane133"
    "ariane136"
    "bp"
    "bp_be"
    "bp_fe"
    "bp_multi"
    "bp_quad"
    "swerv_wrapper"
)

# 设置输入路径（使用绝对路径）
INPUT="${SCRIPT_DIR}/input/open3dbench_8cases_post_hbt_input_20260724"

# 设置标签
LABEL="baseline"

echo "脚本目录: $SCRIPT_DIR"
echo "开始批量运行所有cases"
echo "========================================="
echo "Cases数量: ${#CASES[@]}"
echo "输入路径: $INPUT"
echo "运行标签: $LABEL"
echo "========================================="

# 检查输入目录是否存在
if [ ! -d "$INPUT" ]; then
    echo "错误: 输入目录不存在: $INPUT"
    exit 1
fi

# 遍历所有cases
for i in "${!CASES[@]}"; do
    CASE="${CASES[$i]}"
    NUM=$((i + 1))
    
    # ================= 新增：Case 独立日志配置 =================
    CASE_LOG="${LOG_DIR}/${CASE}.log"
    # 清空旧的独立日志（如果存在）
    > "$CASE_LOG" 
    echo "[$CASE] 独立日志将保存到: $CASE_LOG"
    # ===========================================================
    
    echo ""
    echo "========================================="
    echo "[$NUM/${#CASES[@]}] 运行case: $CASE"
    echo "========================================="
    
    # 使用子shell (...) 将当前 case 的所有输出同时追加到独立日志
    (
        # 运行GRT
        echo "运行GRT..."
        contest run-grt "$CASE" "$INPUT" "$LABEL"
        
        if [ $? -eq 0 ]; then
            echo "GRT运行成功！"
        else
            echo "警告: $CASE 的GRT运行可能有问题"
        fi
        
        # 评估结果
        echo "评估结果..."
        contest evaluate \
            "$CASE" \
            "$INPUT" \
            "${SCRIPT_DIR}/output/$CASE/$LABEL" \
            "${SCRIPT_DIR}/reports/$CASE/$LABEL"
        
        if [ $? -eq 0 ]; then
            echo "$CASE 评估完成！"
        else
            echo "警告: $CASE 的评估可能有问题"
        fi
    ) 2>&1 | tee -a "$CASE_LOG"
    
done

echo ""
echo "========================================="
echo "所有cases运行完成！"
echo "========================================="
echo "输出目录: ${SCRIPT_DIR}/output/"
echo "报告目录: ${SCRIPT_DIR}/reports/"
echo "========================================="