import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
# 【重要】请填入您的 API Key
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct", "TeleAI/TeleMM"]

# --- 2. 页面设置（已修改为您指定的标题） ---
st.set_page_config(page_title="AI 发票助手(QwenVL可编辑版)", layout="wide")

st.markdown("""
    <style>
    div.stDownloadButton > button {
        background-color: #007bff !important; color: white !important; border: none !important;
        padding: 0.5rem 1.2rem !important; border-radius: 8px !important;
    }
    div.stDownloadButton > button:hover { background-color: #0056b3 !important; }
    .dashboard-box {
        padding: 15px; border-radius: 10px; background-color: #f8f9fa; border: 1px solid #e9ecef;
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center;
    }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    .total-container { display: flex; align-items: baseline; justify-content: flex-end; gap: 15px; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    </style>
""", unsafe_allow_html=True)

# --- 3. Session 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
# 存储表格数据，供回调使用
if 'current_table_data' not in st.session_state: st.session_state.current_table_data = []

# --- 4. 核心功能函数 (增强版错误捕获) ---

def call_api_once(image_bytes, mime_type, log_placeholder):
    """
    发送单次请求，返回 (result_dict, error_message)
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    last_error = ""

    for model in CANDIDATE_MODELS:
        if log_placeholder: log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp; 正在连接模型 `{model}`...")
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=40) # 增加超时时间到40s
            
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e]), None
            else:
                # 捕获具体的 HTTP 错误 (如 429)
                last_error = f"HTTP {resp.status_code}: {resp.text[:100]}"
                continue
        except Exception as e:
            last_error = f"Exception: {str(e)}"
            continue
            
    return None, last_error if last_error else "所有模型尝试均失败"

def analyze_with_retry(image_bytes, mime_type, log_container):
    """
    带重试机制的调用，返回 (result, error_msg)
    """
    MAX_RETRIES = 3
    final_error = "未知错误"
    
    for attempt in range(1, MAX_RETRIES + 1):
        result, error = call_api_once(image_bytes, mime_type, log_container)
        if result: 
            return result, None
        
        final_error = error
        if attempt < MAX_RETRIES:
            wait_time = attempt * 2 
            log_container.warning(f" ⚠️ 识别失败: {error}。正在第 {attempt} 次重试 (等待 {wait_time}s)...")
            time.sleep(wait_time)
    
    return None, final_error

def on_table_change():
    """表格回调：即时保存修改"""
    state = st.session_state["invoice_editor"]
    current_data = st.session_state.current_table_data # 从 session 获取映射
    
    for idx, changes in state["edited_rows"].items():
        row_idx = int(idx)
        if row_idx < len(current_data):
            fid = current_data[row_idx]['file_id']
            # 改名
            if "文件名" in changes:
                st.session_state.renamed_files[fid] = changes["文件名"]
            # 改金额
            if "金额" in changes and fid in st.session_state.invoice_cache:
                if st.session_state.invoice_cache[fid].get('data'):
                    st.session_state.invoice_cache[fid]['data']['Total'] = changes["金额"]

# --- 5. 主程序逻辑 ---
st.title(" AI 发票助手(QwenVL可编辑版)")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 1. 队列计算
    queue_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 只要不是 success 状态（包含 failed 和 null），且不在当前 session 处理过，就加入队列
        cache_status = st.session_state.invoice_cache.get(fid, {}).get('status')
        if cache_status != 'success' and fid not in st.session_state.processed_session_ids:
            queue_to_process.append(f)

    # 2. 统计看板
    success_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'success')
    fail_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'failed')
    
    dash = st.empty()
    dash.markdown(f"""
        <div class="dashboard-box">
            <div class="stat-item"> 文件总数: {len(uploaded_files)}</div>
            <div class="stat-item stat-success"> 识别成功: {success_count}</div>
            <div class="stat-item stat-fail"> 识别失败: {fail_count}</div>
            <div class="stat-item" style="color:#666"> 待处理: {len(uploaded_files) - success_count - fail_count}</div>
        </div>
    """, unsafe_allow_html=True)

    # 3. 处理循环 (核心修复区域)
    if queue_to_process:
        st.write("---")
        prog_bar = st.progress(0)
        status_txt = st.empty()
        log_area = st.empty()
        
        total_q = len(queue_to_process)
        
        for i, file in enumerate(queue_to_process):
            # 【核心修复1】强制降速：每张发票之间间隔 1 秒，给 API 喘息时间
            if i > 0: time.sleep(1.0)
            
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid)
            
            display_name = st.session_state.renamed_files.get(fid, file.name)
            status_txt.markdown(f"<div class='processing-highlight'> 正在处理 ({i+1}/{total_q}): {display_name}</div>", unsafe_allow_html=True)
            
            try:
                # 读取文件
                file.seek(0)
                f_bytes = file.read()
                m_type = file.type
                
                # PDF 转图
                if m_type == "application/pdf":
                    log_area.caption(f" 📄 正在解析 PDF: {display_name}")
                    images = convert_from_bytes(f_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                    else:
                        raise Exception("PDF 转图片失败（可能是加密PDF或空文件）")
                
                # 调用 API
                res, err_msg = analyze_with_retry(f_bytes, m_type, log_area)
                
                if res:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': res}
                    success_count += 1
                    log_area.success(f" ✅ {display_name} 成功")
                else:
                    # 【核心修复2】记录真实报错
                    st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': err_msg}
                    fail_count += 1
                    log_area.error(f" ❌ {display_name} 失败: {err_msg}")
            
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': str(e)}
                fail_count += 1
                log_area.error(f" ❌ {display_name} 异常: {e}")

            # 更新进度
            prog_bar.progress((i + 1) / total_q)
        
        # 循环结束，稍作停顿展示结果
        time.sleep(1.5)
        st.rerun()

    # 4. 数据展示准备
    table_data = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        d_name = st.session_state.renamed_files.get(fid, f.name)
        cache = st.session_state.invoice_cache.get(fid)
        
        if cache and cache['status'] == 'success':
            d = cache['data']
            try: amt = float(str(d.get('Total',0)).replace(',','').replace('元',''))
            except: amt = 0.0
            table_data.append({"文件名": d_name, "日期": d.get('Date',''), "项目": d.get('Item',''), "金额": amt, "状态": "成功", "file_id": fid})
        elif cache and cache['status'] == 'failed':
            # 【核心修复3】在表格中显示具体错误原因
            err = cache.get('error', '未知错误')
            table_data.append({"文件名": d_name, "日期": "识别失败", "项目": f"❌ {err}", "金额": 0.0, "状态": "失败", "file_id": fid})
        else:
            table_data.append({"文件名": d_name, "日期": "", "项目": "", "金额": 0.0, "状态": "待处理", "file_id": fid})

    # 保存到 session 供回调使用
    st.session_state.current_table_data = table_data

    # 5. 表格与操作
    if table_data:
        df = pd.DataFrame(table_data)
        
        # 统计未完成任务
        pending_or_failed = [r for r in table_data if r['状态'] != '成功']
        
        c1, c2 = st.columns([7, 3])
        with c1:
            if pending_or_failed:
                st.warning(f" 当前有 {len(pending_or_failed)} 个任务需要处理或重试。")
        with c2:
            # 重试按钮：重置所有非成功任务的状态
            if st.button("🔄 重试所有未完成/失败任务", type="primary", use_container_width=True, disabled=not pending_or_failed):
                for row in pending_or_failed:
                    fid = row['file_id']
                    # 从已处理集合中移除，下次循环会自动加入 queue_to_process
                    if fid in st.session_state.processed_session_ids:
                        st.session_state.processed_session_ids.remove(fid)
                st.rerun()

        # 可编辑表格
        edited = st.data_editor(
            df,
            column_config={
                "file_id": None,
                "金额": st.column_config.NumberColumn(format="%.2f", required=True),
                "状态": st.column_config.TextColumn(width="small", disabled=True),
                "文件名": st.column_config.TextColumn(disabled=False, help="双击修改文件名"),
                "项目": st.column_config.TextColumn(width="large")
            },
            num_rows="dynamic", use_container_width=True, 
            key="invoice_editor", on_change=on_table_change
        )

        # 6. 底部统计
        total = sum(r['金额'] for r in table_data if r['状态'] == '成功')
        
        bc1, bc2, bc3 = st.columns([2, 5, 2])
        with bc2:
            l, r = st.columns([1.5, 1])
            with l: st.markdown(f"""<div class="total-container"><span class="total-value">合计: {total:,.2f}</span></div>""", unsafe_allow_html=True)
            with r:
                out = io.BytesIO()
                # 导出清洗数据
                export_df = pd.DataFrame(table_data).drop(columns=['file_id'])
                with pd.ExcelWriter(out, engine='openpyxl') as writer: export_df.to_excel(writer, index=False)
                st.download_button("导出 Excel", out.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
