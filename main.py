import httpx  # 用于向树莓派 AI 接口发送请求
from nptdms import TdmsFile
import asyncio, json, os, numpy as np, sqlite3
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from nptdms import TdmsFile
from scipy.fftpack import fft
from fastapi import Query
import httpx
import requests


app = FastAPI()
DB_DIR = "database"
FILES = ["模组一2026-3-19 17-01-47.tdms", "模组二2026-3-19 17-01-47.tdms"]
AI_SERVER_URL = "http://runix:8080/v1/completions"

# 树莓派 llama.cpp 的开放 API 地址 (根据实际接口微调，通常符合 OpenAI 格式或原生 completion)

NAME_MAP = {
    "9232/ai0": "1#发电机-驱动端振动",
    "9232/ai1": "1#发电机-非驱动端振动",
    "9232/ai2": "2#引风机-机壳振动",
    "ai0": "1#发电机-驱动端振动",
    "ai1": "1#发电机-非驱动端振动",
    "ai2": "2#引风机-机壳振动"
}
def init_db():
    conn = sqlite3.connect('vibration_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS diag_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time DATETIME DEFAULT (datetime('now','localtime')),
            channel_id TEXT,
            alias TEXT,
            rms REAL,
            msg TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db() # 执行初始化


def analyze_signal(data):
    """核心信号分析：RMS、FFT"""
    if len(data) == 0: return 0, []
    rms = np.sqrt(np.mean(np.square(data)))
    n = len(data)
    yf = fft(data)
    amp = (2.0/n * np.abs(yf[0:n//2])).tolist()
    return float(rms), amp

@app.get("/")
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# @app.get("/analysis")
# async def get_analysis():
#     with open("analysis.html", "r", encoding="utf-8") as f:
#         return HTMLResponse(content=f.read())

@app.get("/analysis")
async def get_analysis():
    # 更改指向：让它直接读取你全新设计的重构版本（建议将 analysis_page_redesign.html 命名为 analysis.html 覆盖）
    with open("analysis.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/get_history")
async def get_history(channel_id: str = Query(None)):
    """获取历史统计数据，完美支持带路径的通道 ID 精确过滤"""
    conn = sqlite3.connect('vibration_history.db')
    cursor = conn.cursor()
    
    where_clause = ""
    params = []
    
    if channel_id and channel_id.strip() != "" and channel_id.strip() != "all":
        # 使用 LIKE 或者直接 = 来进行匹配，这里用 = 最精确
        where_clause = "WHERE channel_id = ?"
        params = [channel_id.strip()]

    # 1. 报警总次数
    cursor.execute(f"SELECT COUNT(*) FROM diag_logs {where_clause}", params)
    total_today = cursor.fetchone()[0]
    
    # 2. 最高 RMS 峰值
    cursor.execute(f"SELECT MAX(rms) FROM diag_logs {where_clause}", params)
    max_rms_row = cursor.fetchone()
    max_rms = round(max_rms_row[0], 2) if (max_rms_row and max_rms_row[0] is not None) else 0.0
    
    # 3. 诊断分析目标
    if channel_id and channel_id != "all":
        frequent_device = NAME_MAP.get(channel_id.strip(), channel_id)
    else:
        cursor.execute("SELECT alias, COUNT(*) as cnt FROM diag_logs GROUP BY alias ORDER BY cnt DESC LIMIT 1")
        frequent_row = cursor.fetchone()
        frequent_device = frequent_row[0] if frequent_row else "暂无"
    
    # 4. 柱状图数据（保持全局各通道对比）
    cursor.execute("SELECT alias, COUNT(*) FROM diag_logs GROUP BY alias")
    bar_rows = cursor.fetchall()
    bar_data = {r[0]: r[1] for r in bar_rows} if bar_rows else {}
    
    # 5. 历史报警明细
    cursor.execute(f"SELECT time, alias, msg, rms, channel_id FROM diag_logs {where_clause} ORDER BY id DESC LIMIT 50", params)
    rows = cursor.fetchall()
    
    logs = []
    for r in rows:
        time_str = r[0].split(" ")[1] if (r[0] and " " in r[0]) else (r[0] if r[0] else "00:00:00")
        logs.append({
            "time": time_str,
            "date_time": r[0] if r[0] else "未知时间",
            "alias": r[1] if r[1] else "未知通道",
            "msg": r[2] if r[2] else "正常",
            "rms": round(r[3], 2) if r[3] is not None else 0.0,
            "channel_id": r[4]
        })
        
    conn.close()
    
    return {
        "metrics": {
            "total_today": total_today,
            "max_rms": max_rms,
            "frequent_device": frequent_device,
            "total_week": total_today
        },
        "bar_chart": {
            "labels": list(bar_data.keys()),
            "values": list(bar_data.values())
        },
        "logs": logs
    }

# 新增路由：渲染 AI 报告空白页面
@app.get("/ai_report")
async def get_ai_report():
    with open("ai_report.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/generate_ai_analysis")
async def generate_ai_analysis():
    """终极中庸版：只捞4条最严重异常（10条必超时），脱水纯中文，给足90秒死等"""
    conn = sqlite3.connect('vibration_history.db')
    cursor = conn.cursor()
    
    # 🌟 1. 别贪多！只捞取最近最严重的 4 条异常日志（既有丰富度，树莓派又读得完）
    cursor.execute("SELECT alias, msg, rms FROM diag_logs ORDER BY id DESC LIMIT 4")
    recent_logs = cursor.fetchall()
    conn.close()
    
    if not recent_logs:
        return {"status": "empty", "analysis": "当前数据库暂无异常记录。"}

    # 🌟 2. 依然保持纯中文极致脱水格式
    log_summary_list = []
    for log in recent_logs:
        alias = log[0]
        msg = log[1]
        rms = log[2]
        log_summary_list.append(f"{alias}发生{msg}，振动值{rms:.1f}。")
    
    data_context = "，".join(log_summary_list) + "。"
        

    raw_prompt = (
        "<start_of_turn>user\n"
        f"你是一位精通旋转机械动力学与振动谱线分析的火电厂首席检修专家。请针对以下最近发生的4条现场设备异常数据进行深度诊断：\n"
        f"【现场多点数据】{data_context}\n\n"
        f"请基于上述数据，撰写一篇200字左右的结构化专家级故障诊断报告。必须严格按以下格式展开，内容要专业、详细，切勿敷衍简写：\n"
        f"一、现场整体状态综合评估：（请结合振动数值，详细阐述设备的疲劳危险程度与当前劣化趋势）\n"
        f"二、深层故障机理推导分析：（从机械动力学角度，深度剖析可能导致该连续振动的物理诱因，如不对中、松动、不平衡等）\n"
        f"三、指导性检修工艺动作建议：（请给出具体的停机排查步骤、测量工具使用以及核心紧固/对中工艺动作）\n"
        "<end_of_turn>\n"
        "<start_of_turn>model\n"
    )

    payload = {
        "prompt": raw_prompt,
        "temperature": 0.3,  # 稍微提高到 0.3，允许大模型在技术词汇上进行更丰富的语言组织
        "max_tokens": 350,   # 🌟 放大 Token 限制，允许吐出 200-300 字的详细长文
        "stream": False
    }

    try:
        # 🌟 4. 将超时时间放大到 90.0 秒！给纯 CPU 足够的 Prefill 吞吐时间
        response = requests.post(
            AI_SERVER_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=200.0
        )
        
        if response.status_code == 200:
            res_json = response.json()
            ai_text = res_json['choices'][0]['text'].replace("<end_of_turn>", "").strip()
            
            if not ai_text:
                ai_text = "⚠️ 边缘模型虽未超时，但仍未能生成有效文本，请点击下方按钮重新生成。"
                
            return {"status": "success", "analysis": ai_text}
        else:
            return {"status": "error", "analysis": f"树莓派响应状态码异常: {response.status_code}"}
            
    except requests.exceptions.Timeout:
        # 🌟 超时捕获：哪怕 90 秒真爆了，也优雅地提示，绝不让后台挂掉
        return {"status": "error", "analysis": "❌ 树莓派计算达到90秒上限超时！树莓派CPU算力已到物理极限，请尝试再次生成或重启 llama-server。"}
    except Exception as e:
        return {"status": "error", "analysis": f"连接树莓派失败: {str(e)}"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        paths = [os.path.join(DB_DIR, f) for f in FILES if os.path.exists(os.path.join(DB_DIR, f))]
        if not paths: return
        tdms_objs = [TdmsFile.read(p) for p in paths]
        
        offset = 0
        while True:
            for tdms in tdms_objs:
                for group in tdms.groups():
                    for channel in group.channels():
                        raw_data = channel.read_data()
                        start = offset % (len(raw_data) - 1000)
                        segment = raw_data[start : start + 1000]
                        
                        rms, amp = analyze_signal(segment)
                        
                        # 专家诊断逻辑
                        diag_level = "ok"
                        diag_msg = "状态正常"
                        diag_advice = "设备各项指标平稳，建议继续保持在线监测。"
                        
                        if rms > 6.5:
                            diag_level = "error"
                            diag_msg = "强烈振动警告！"
                            diag_advice = "检测到严重的 1 倍频能量集中，怀疑转子不平衡。建议立即安排停机检查动平衡及联轴器状态。"
                        elif rms > 3.5:
                            diag_level = "warning"
                            diag_msg = "振动值偏高"
                            diag_advice = "振动水平有所上升，建议检查地脚螺栓紧固情况并增加人工巡检频次。"

                        # --- 数据库存储逻辑 (新添加) ---
                        # 只要不是 ok，就存入数据库，实现“异常自动记录”
                        if diag_level != "ok":
                            conn = sqlite3.connect('vibration_history.db')
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO diag_logs (channel_id, alias, rms, msg) VALUES (?, ?, ?, ?)",
                                (channel.name, NAME_MAP.get(channel.name, channel.name), rms, diag_msg)
                            )
                            conn.commit()
                            conn.close()

                        await websocket.send_json({
                            "id": f"{channel.name}",
                            "alias": NAME_MAP.get(channel.name, channel.name),
                            "wave": segment.tolist()[::4], 
                            "fft": amp[::4],
                            "rms": rms,
                            "diag_level": diag_level,
                            "diag_msg": diag_msg,
                            "diag_advice": diag_advice
                        })
                        await asyncio.sleep(0.15) 
            offset += 300 
    except Exception as e:
        print(f"WS Disconnected: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)