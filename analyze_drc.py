#!/usr/bin/env python3
"""
增强版 DRC 报告解析脚本
不仅输出到终端，还会自动生成独立的 .txt 报告和 .csv 详细数据表。
"""
import re
import sys
import csv
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime

def parse_drc_report(file_path):
    violations = []
    type_pattern = re.compile(r'^violation type:\s*(.+)$')
    srcs_pattern = re.compile(r'^srcs:\s*(.+)$')
    bbox_pattern = re.compile(r'^bbox\s*=\s*\(([^)]+)\)\s*-\s*\(([^)]+)\)\s*on\s+Layer\s*(.+)$')
    
    current_violation = {}
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
                
            type_match = type_pattern.match(line)
            if type_match:
                current_violation['type'] = type_match.group(1).strip()
                continue
                
            srcs_match = srcs_pattern.match(line)
            if srcs_match:
                current_violation['srcs'] = srcs_match.group(1).strip()
                continue
                
            bbox_match = bbox_pattern.match(line)
            if bbox_match:
                current_violation['bbox'] = bbox_match.group(0).strip()
                current_violation['layer'] = bbox_match.group(3).strip()
                violations.append(current_violation)
                current_violation = {}
                
    return violations

def analyze_violations(violations):
    type_counter = Counter()
    layer_counter = defaultdict(Counter)
    net_counter = Counter()
    
    for v in violations:
        v_type = v.get('type', 'Unknown')
        layer = v.get('layer', 'Unknown')
        srcs = v.get('srcs', '')
        
        type_counter[v_type] += 1
        layer_counter[v_type][layer] += 1
        
        nets = [n.strip().replace('net:', '') for n in srcs.split()]
        for net in nets:
            net_counter[net] += 1
            
    return type_counter, layer_counter, net_counter

def generate_text_report(type_counter, layer_counter, net_counter, output_txt, total_violations):
    """生成结构化的文本报告"""
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write(" " * 20 + "DRC 错误统计分析报告\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
        
        f.write(f"📊 总览:\n")
        f.write(f"  - 总 DRC 错误数: {total_violations}\n")
        f.write(f"  - 错误类型种类数: {len(type_counter)}\n\n")
        
        f.write("-" * 70 + "\n")
        f.write("1️⃣ 错误类型 Top 10:\n")
        f.write("-" * 70 + "\n")
        for v_type, count in type_counter.most_common(10):
            top_layer = layer_counter[v_type].most_common(1)[0][0]
            pct = (count / total_violations * 100) if total_violations > 0 else 0
            f.write(f"  [{v_type:<15}] 数量: {count:<7} ({pct:>5.1f}%) | 主要发生层: {top_layer}\n")
            
        f.write("\n" + "-" * 70 + "\n")
        f.write("2️⃣ 各错误类型详细层级分布 (Top 3):\n")
        f.write("-" * 70 + "\n")
        for v_type in list(type_counter.keys())[:10]:
            f.write(f"  ▶ {v_type}:\n")
            for layer, count in layer_counter[v_type].most_common(3):
                f.write(f"      - {layer}: {count} 次\n")
                
        f.write("\n" + "-" * 70 + "\n")
        f.write("3️⃣ 最常出错的 Net (Top 20):\n")
        f.write("-" * 70 + "\n")
        for net, count in net_counter.most_common(20):
            f.write(f"  {net:<60} : {count} 次\n")
            
        f.write("\n" + "=" * 70 + "\n")
        f.write("报告生成完毕。\n")

def export_to_csv(violations, output_csv):
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['type', 'srcs', 'layer', 'bbox'])
        writer.writeheader()
        writer.writerows(violations)

def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <drc_report.txt> [output_prefix]", file=sys.stderr)
        sys.exit(1)
        
    file_path = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else file_path.stem
    
    if not file_path.exists():
        print(f"❌ 错误: 找不到文件 '{file_path}'")
        sys.exit(1)
        
    print(f"⏳ 正在解析文件: {file_path} ...")
    violations = parse_drc_report(file_path)
    total_violations = len(violations)
    print(f"✅ 成功解析 {total_violations} 条 DRC 错误。\n")
    
    if total_violations == 0:
        print("🎉 恭喜！未发现任何 DRC 错误！")
        return

    type_counter, layer_counter, net_counter = analyze_violations(violations)
    
    # 1. 打印到终端 (会被 bash 的 tee 自动捕获到 run_xxx.log)
    print("=" * 70)
    print(" " * 20 + "📊 DRC 错误统计报告")
    print("=" * 70)
    print(f"\n总 DRC 错误数: {total_violations}")
    print(f"错误类型种类数: {len(type_counter)}")
    print("-" * 70)
    for v_type, count in type_counter.most_common(10):
        top_layer = layer_counter[v_type].most_common(1)[0][0]
        pct = (count / total_violations * 100) if total_violations > 0 else 0
        print(f"  [{v_type:<15}] 数量: {count:<7} ({pct:>5.1f}%) | 主要发生层: {top_layer}")
        
    print(f"\n最常出错的 Net (Top 10):")
    print("-" * 70)
    for net, count in net_counter.most_common(10):
        print(f"  {net:<60} : {count} 次")

    # 2. 生成独立的文本报告文件
    txt_report = f"drc_report_{prefix}.txt"
    generate_text_report(type_counter, layer_counter, net_counter, txt_report, total_violations)
    print(f"\n💾 结构化文本报告已保存至: {txt_report}")

    # 3. 生成详细的 CSV 数据表
    csv_report = f"drc_details_{prefix}.csv"
    export_to_csv(violations, csv_report)
    print(f"💾 详细数据表 (CSV) 已保存至: {csv_report}")

if __name__ == "__main__":
    main()