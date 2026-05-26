"""
TDMS 文件结构探查脚本
用法: python inspect_tdms.py <文件1.tdms> [文件2.tdms]
"""

import sys
import json
from pathlib import Path

try:
    from nptdms import TdmsFile
except ImportError:
    print("正在安装 nptdms...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "nptdms", "--break-system-packages", "-q"])
    from nptdms import TdmsFile


def inspect_tdms(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {"error": f"文件不存在: {filepath}"}

    tdms = TdmsFile.read(filepath)
    result = {
        "file": str(path.name),
        "file_size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "groups": []
    }

    # 文件级属性
    file_props = dict(tdms.properties)
    if file_props:
        result["file_properties"] = file_props

    for group in tdms.groups():
        group_info = {
            "group_name": group.name,
            "channels": []
        }

        # 组级属性
        group_props = dict(group.properties)
        if group_props:
            group_info["group_properties"] = group_props

        for channel in group.channels():
            data = channel[:]
            ch_info = {
                "channel_name": channel.name,
                "data_type": str(channel.dtype) if hasattr(channel, 'dtype') else "unknown",
                "num_samples": len(data),
                "properties": dict(channel.properties),
            }

            # 采样率 / 时间信息
            if "wf_increment" in channel.properties:
                dt = channel.properties["wf_increment"]
                ch_info["sample_interval_s"] = dt
                ch_info["sample_rate_hz"] = round(1.0 / dt, 2) if dt else None
                ch_info["duration_s"] = round(len(data) * dt, 4)

            if "wf_start_time" in channel.properties:
                ch_info["start_time"] = str(channel.properties["wf_start_time"])

            # 数值统计
            if len(data) > 0:
                try:
                    import numpy as np
                    arr = data.astype(float)
                    ch_info["stats"] = {
                        "min": round(float(arr.min()), 6),
                        "max": round(float(arr.max()), 6),
                        "mean": round(float(arr.mean()), 6),
                        "std": round(float(arr.std()), 6),
                    }
                    ch_info["first_5_values"] = [round(float(v), 6) for v in arr[:5]]
                except Exception as e:
                    ch_info["stats_error"] = str(e)

            group_info["channels"].append(ch_info)

        result["groups"].append(group_info)

    return result


def main():
    files = sys.argv[1:]
    if not files:
        print("用法: python inspect_tdms.py <文件1.tdms> [文件2.tdms ...]")
        print("\n示例: python inspect_tdms.py plant_a.tdms plant_b.tdms")
        sys.exit(1)

    all_results = []
    for f in files:
        print(f"\n{'='*60}")
        print(f"正在分析: {f}")
        print('='*60)
        info = inspect_tdms(f)
        all_results.append(info)
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))

    # 同时保存到 JSON 文件
    out_path = Path("tdms_inspection_result.json")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(all_results, fp, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 结果已保存到: {out_path.resolve()}")


if __name__ == "__main__":
    main()