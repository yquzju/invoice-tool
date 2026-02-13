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

# --- 🟢 注入 CSS：按钮样式定制 + 居中同行布局 ---
st.markdown("""
    <style>
    /* 1. 定制下载按钮：蓝色、自适应大小、无图标 */
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
    /* 去除按钮自带图标 */
    button[data-testid="baseButton-primary"] p::before {
        content: none !important;
    }

    /* 2. 统计文案样式 */
    .total-label {
        font-size: 1.2rem;
        color: #6C757D;
    }
    .total-val {
        font-size: 2rem;
        font-weight: 700;
        color: #212529;
    }
    </style>
""", unsafe_allow_html=True)

def analyze_image_auto_switch(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f" 正在尝试: {model_name} ...")
        data = {
            "model": model_name,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract invoice data into JSON: 1.Item 2.Date 3.Total. JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            }],
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
        except: continue
    return None

# --- 页面主逻辑 ---
st.set_page_config(page_title="发票助手 (QwenVL 版)", layout="wide")
st.title("🧾 发票助手 (QwenVL 可编辑版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    new_files = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.invoice_cache and f"{f.name}_{f.size}" not in st.session_state.ignored_files]
    
    if new_files:
        progress_bar = st.progress(0)
        st.info(f"检测到 {len(new_files)} 张新发票，准备识别...")
    
    current_data_list = []
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        if file_id in st.session_state.ignored_files: continue

        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
        else:
            try:
                file_bytes = file.read()
                process_bytes = file_bytes
                mime_type = file.type
                if file.type == "application/pdf":
                    images = convert_from_bytes(file_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        process_bytes, mime_type = buf.getvalue(), "image/jpeg"
                if mime_type == 'image/jpg': mime_type = 'image/jpeg'
                result = analyze_image_auto_switch(process_bytes, mime_type)
                if result: st.session_state.invoice_cache[file_id] = result
                if file in new_files:
                    progress_bar.progress((new_files.index(file) + 1) / len(new_files))
            except: result = None

        if result:
            amt = float(str(result.get('Total', 0)).replace(',','').replace('元',''))
            current_data_list.append({"文件名": file.name, "日期": result.get('Date', ''), "项目": result.get('Item', ''), "金额": amt, "file_id": file_id})

    if current_data_list:
        df = pd.DataFrame(current_data_list)
        edited_df = st.data_editor(
            df, 
            column_config={"file_id": None, "金额": st.column_config.NumberColumn(format="%.2f"), "文件名": st.column_config.TextColumn(disabled=True)},
            num_rows="dynamic", use_container_width=True, key="invoice_editor"
        )
        
        # 同步更新与删除
        if len(edited_df) != len(df):
            st.session_state.ignored_files.update(set(df["file_id"]) - set(edited_df["file_id"]))
            st.rerun()

        # --- 🟢 居中同行展示区 ---
        total = edited_df['金额'].sum()
        
        # 布局：[留白, 内容, 留白]
        col_side1, col_center, col_side2 = st.columns([2.5, 5, 2.5])
        with col_center:
            inner_left, inner_right = st.columns([1.5, 1])
            with inner_left:
                st.markdown(f"""
                    <div style="display: flex; align-items: baseline; justify-content: flex-end; gap: 10px; height: 100%;">
                        <span class="total-label">💰 总金额合计</span>
                        <span class="total-val">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            with inner_right:
                output = io.BytesIO()
                df_export = edited_df.drop(columns=["file_id"])
                df_export.loc[len(df_export)] = ['合计', '', '', total]
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False)
                st.download_button(label="导出 excel", data=output.getvalue(), file_name="发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
