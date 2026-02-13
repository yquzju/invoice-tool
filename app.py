import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- ⚠️ 填入你的 SiliconFlow Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# --- 备选模型名单 ---
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct",
    "Qwen/Qwen2-VL-7B-Instruct",
    "deepseek-ai/deepseek-vl-7b-chat",
    "TeleAI/TeleMM"
]

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

# --- 样式美化 (CSS) ---
def local_css():
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .stApp {
        background-color: #F8F9FA;
    }

    /* 卡片样式 */
    .metric-card-container {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        color: white;
        margin-bottom: 20px;
        height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .card-title { font-size: 14px; opacity: 0.9; margin-bottom: 5px; }
    .card-value { font-size: 28px; font-weight: bold; }
    .card-icon { font-size: 24px; float: right; opacity: 0.8; }

    /* 背景色 */
    .bg-blue { background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%); }
    .bg-green { background: linear-gradient(135deg, #10B981 0%, #059669 100%); }
    .bg-orange { background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%); }

    /* 上传框样式优化 */
    [data-testid='stFileUploader'] {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        border: 2px dashed #E5E7EB;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 核心识别逻辑 ---
def analyze_image_auto_switch(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    last_error = ""

    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在通过 {model_name} 识别...")
        
        data = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract invoice data into JSON: 1.Item 2.Date 3.Total. JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 512,
            "temperature": 0.1
        }

        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if response.status_code == 200:
                status_placeholder.empty()
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s = clean.find('{')
                e = clean.rfind('}') + 1
                return json.loads(clean[s:e]) if s != -1 else json.loads(clean)
            elif response.status_code == 403:
                status_placeholder.empty()
                if "7B" in model_name: raise Exception("余额不足")
                continue
            else:
                status_placeholder.empty()
                continue
        except Exception as e:
            status_placeholder.empty()
            last_error = str(e)
            continue
    raise Exception(f"识别失败: {last_error}")

# --- 主页面逻辑 ---
st.set_page_config(page_title="智能发票系统", layout="wide", initial_sidebar_state="collapsed")
local_css()

# 初始化状态
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

# 1. 标题与上传
st.markdown("### 🧾 智能发票识别系统")
uploaded_files = st.file_uploader("点击或拖拽上传发票 (支持 PDF/JPG/PNG)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

# 2. 数据处理
current_data_list = []

if uploaded_files:
    # 筛选新文件用于进度条显示
    new_files = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.invoice_cache and f"{f.name}_{f.size}" not in st.session_state.ignored_files]
    if new_files:
        progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        
        # 跳过已删除文件
        if file_id in st.session_state.ignored_files: continue

        # 缓存检查
        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
        else:
            try:
                # 转换
                file_bytes = file.read()
                mime_type = file.type
                process_bytes = file_bytes
                
                if file.type == "application/pdf":
                    images = convert_from_bytes(file_bytes)
                    if images:
                        img_buffer = io.BytesIO()
                        images[0].save(img_buffer, format="JPEG")
                        process_bytes = img_buffer.getvalue()
                        mime_type = "image/jpeg"
                if mime_type == 'image/jpg': mime_type = 'image/jpeg'

                # 识别
                result = analyze_image_auto_switch(process_bytes, mime_type)
                if result:
                    st.session_state.invoice_cache[file_id] = result
                
                # 更新进度
                if file in new_files:
                    progress_bar.progress((new_files.index(file) + 1) / len(new_files))

            except Exception as e:
                result = None

        if result:
            try:
                amt = float(str(result.get('Total', 0)).replace('¥','').replace(',','').replace('元',''))
            except: amt = 0.0
            
            current_data_list.append({
                "序号": index + 1,
                "文件名": file.name,
                "项目名称": result.get('Item', ''),
                "开票时间": result.get('Date', ''),
                "金额": amt,
                "状态": "✅ 完成",
                "file_id": file_id
            })

# 3. 统计卡片显示
total_files = len(current_data_list)
total_amount = sum(item['金额'] for item in current_data_list)
success_count = total_files

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"""
    <div class="metric-card-container bg-blue">
        <div class="card-icon">📄</div>
        <div class="card-title">发票总数 (张)</div>
        <div class="card-value">{total_files}</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="metric-card-container bg-green">
        <div class="card-icon">✅</div>
        <div class="card-title">识别成功 (张)</div>
        <div class="card-value">{success_count}</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="metric-card-container bg-orange">
        <div class="card-icon">💰</div>
        <div class="card-title">合计金额 (元)</div>
        <div class="card-value">¥ {total_amount:,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

# 4. 表格与操作
st.markdown("##### 📄 发票明细列表")
col_spacer, col_btn1, col_btn2 = st.columns([6, 1.5, 1.5])

if current_data_list:
    df = pd.DataFrame(current_data_list)
    
    # 导出逻辑
    df_export = df.drop(columns=["file_id", "序号", "状态"])
    df_export.loc[len(df_export)] = ['合计', '', '', total_amount]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False)
    
    with col_btn2:
        st.download_button(
            label="📥 导出 Excel",
            data=output.getvalue(),
            file_name="发票汇总.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )

    # 清空逻辑
    with col_btn1:
        if st.button("🗑️ 清空列表", use_container_width=True):
            st.session_state.invoice_cache = {}
            st.session_state.ignored_files = set()
            st.rerun()

    # 编辑器
    edited_df = st.data_editor(
        df,
        column_config={
            "file_id": None, 
            "序号": st.column_config.NumberColumn(width="small"),
            "文件名": st.column_config.TextColumn(width="medium", disabled=True),
            "项目名称": st.column_config.TextColumn(width="medium"),
            "开票时间": st.column_config.TextColumn(width="small"),
            "金额": st.column_config.NumberColumn(format="¥ %.2f", width="small"),
            "状态": st.column_config.TextColumn(width="small", disabled=True)
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="invoice_editor"
    )

    # 4.1 检测删除
    current_ids = set(edited_df["file_id"])
    original_ids = set(df["file_id"])
    deleted_ids = original_ids - current_ids
    
    if deleted_ids:
        st.session_state.ignored_files.update(deleted_ids)
        st.rerun()
        
    # 4.2 检测修改 (反向更新缓存)
    for index, row in edited_df.iterrows():
        fid = row['file_id']
        if fid in st.session_state.invoice_cache:
            cache = st.session_state.invoice_cache[fid]
            if cache['Item'] != row['项目名称'] or cache['Total'] != row['金额'] or cache['Date'] != row['开票时间']:
                cache['Item'] = row['项目名称']
                cache['Date'] = row['开票时间']
                cache['Total'] = row['金额']

else:
    # 空状态显示
    st.info("👆 请在上方上传发票文件，识别结果将显示在这里。")
    empty_df = pd.DataFrame(columns=["序号", "文件名", "项目名称", "开票时间", "金额", "状态"])
    st.dataframe(empty_df, use_container_width=True, hide_index=True)
