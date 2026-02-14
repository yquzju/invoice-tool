import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
# 备选模型列表
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct", 
    "Qwen/Qwen2-VL-7B-Instruct",
    "TeleAI/TeleMM"
]

# --- 2. 注入 CSS：优化按钮、布局与状态显示 ---
st.markdown("""
    <style>
    /* 高级蓝色按钮，自适应宽度 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.2rem !important;
        border-radius: 8px !important;
        transition: all 0.3s ease;
        width: auto !important;
        min-width: unset !important;
        display: inline-flex !important;
        font-weight: 500 !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 12px rgba(0,123,255,0.3) !important;
    }
    button[data-testid="baseButton-primary"] p::before { content: none !important; }

    /* 底部布局容器 */
    .total-container {
        display: flex;
        align-items: baseline;
        justify-content: flex-end;
        gap: 15px;
        height: 100%;
    }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    
    /* 进度状态文字 */
    .status-text { font-size: 14px; color: #007bff; margin-bottom: 5px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 核心识别函数 (带实时状态反馈) ---
def analyze_invoice(image_bytes, mime_type, status_box):
    """
    status_box: 用于在界面上实时打印当前正在连接哪个模型
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    # 提示词：强制要求提取价税合计
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    last_err = ""
    for model in CANDIDATE_MODELS:
        # 🟢 实时反馈：告诉用户正在尝试哪个模型
        if status_box:
            status_box.markdown(f"🔄 正在请求模型：**{model}** ...")
            
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=30)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
            continue
            
    # 如果所有模型都失败，打印最后一次错误
    if status_box:
        status_box.markdown(f"⚠️ 所有模型尝试失败: {last_err}")
    return None

# --- 4. 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手 (QwenVL)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 实时反馈版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 1. 找出需要处理的文件 (新文件 OR 之前失败的文件)
    files_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 没处理过，或者上次处理失败的，都要加入队列
        if fid not in st.session_state.invoice_cache or st.session_state.invoice_cache[fid].get('status') == 'failed':
            files_to_process.append(f)

    # 2. 批量处理循环 (带可视化反馈)
    if files_to_process:
        # 创建一个固定的状态显示区
        status_container = st.container()
        with status_container:
            st.info(f"🚀 准备处理 {len(files_to_process)} 张发票，请保持网络通畅...")
            main_progress = st.progress(0)
            current_status = st.empty() # 专门用来显示“正在识别 xxx...”
            model_status = st.empty()   # 专门用来显示“正在连接 Qwen...”
        
        for i, file in enumerate(files_to_process):
            fid = f"{file.name}_{file.size}"
            
            # 更新文案：明确告诉用户正在处理哪张图
            current_status.markdown(f"**正在处理 ({i+1}/{len(files_to_process)})：** `{file.name}`")
            
            try:
                # 读取文件
                file.seek(0)
                f_bytes = file.read()
                m_type = file.type
                
                # PDF 转图
                if m_type == "application/pdf":
                    model_status.caption("📄 正在将 PDF 转换为图像...")
                    images = convert_from_bytes(f_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                elif m_type == 'image/jpg': 
                    m_type = 'image/jpeg'

                # 调用识别 (传入 model_status 占位符)
                result = analyze_invoice(f_bytes, m_type, model_status)
                
                if result:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': result}
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
            
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed'}
            
            # 更新进度条
            main_progress.progress((i + 1) / len(files_to_process))
            
            # 🟢 关键：强制刷新 UI 缓存，防止界面卡死
            time.sleep(0.5) 

        # 循环结束，清空状态区并刷新页面显示表格
        status_container.empty()
        st.rerun()

    # --- 3. 数据渲染与表格 ---
    table_data = []
    has_failed_items = False
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        cache = st.session_state.invoice_cache.get(fid)
        
        if cache and cache['status'] == 'success':
            res = cache['data']
            try:
                amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
            except: amt = 0.0
            table_data.append({
                "文件名": file.name, "日期": res.get('Date', ''), "项目": res.get('Item', ''), 
                "金额": amt, "状态": "✅ 成功", "file_id": fid
            })
        elif cache and cache['status'] == 'failed':
            has_failed_items = True
            # 失败的文件也要显示在表格里！
            table_data.append({
                "文件名": file.name, "日期": "-", "项目": "-", 
                "金额": 0.0, "状态": "❌ 失败", "file_id": fid
            })

    if table_data:
        df = pd.DataFrame(table_data)
        
        # 顶部工具栏：如果有失败的，显示重试按钮
        if has_failed_items:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning("⚠️ 部分发票识别失败，可能是网络波动，请点击右侧按钮重试。")
            with c2: 
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True):
                    st.rerun()

        # 表格
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None,
                "金额": st.column_config.NumberColumn(format="%.2f"),
                "状态": st.column_config.TextColumn(width="small", disabled=True),
                "文件名": st.column_config.TextColumn(disabled=True)
            },
            num_rows="dynamic", use_container_width=True, key="invoice_editor"
        )
        
        # 同步删除与修改
        current_ids = set(edited_df["file_id"])
        original_ids = set(df["file_id"])
        if len(current_ids) != len(original_ids):
            st.session_state.ignored_files.update(original_ids - current_ids)
            st.rerun()
            
        for index, row in edited_df.iterrows():
            fid = row['file_id']
            if fid in st.session_state.invoice_cache and st.session_state.invoice_cache[fid]['status'] == 'success':
                 st.session_state.invoice_cache[fid]['data']['Total'] = row['金额']

        # 底部布局：总金额与导出按钮
        total = edited_df[edited_df['状态'] == "✅ 成功"]['金额'].sum()
        
        c_side1, c_main, c_side2 = st.columns([2.5, 5, 2.5])
        with c_main:
            inner_l, inner_r = st.columns([1.5, 1])
            with inner_l:
                st.markdown(f"""
                    <div class="total-container">
                        <span class="total-label">💰 总金额合计</span>
                        <span class="total-value">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            with inner_r:
                output = io.BytesIO()
                df_exp = edited_df.drop(columns=["file_id"])
                df_exp.loc[len(df_exp)] = ['合计', '', '', total, '']
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_exp.to_excel(writer, index=False)
                st.download_button("导出 excel", output.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
