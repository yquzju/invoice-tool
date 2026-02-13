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
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct"]

# --- 2. 注入 CSS：实现高级感、同行对齐、居中及按钮自适应 ---
st.markdown("""
    <style>
    /* 下载按钮：高级蓝、完全动态适配文案大小 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.2rem !important; /* 精简内边距 */
        border-radius: 6px !important;
        transition: all 0.3s ease;
        font-weight: 500 !important;
        width: auto !important;   /* 核心：宽度随内容变化 */
        min-width: unset !important; /* 核心：取消最小宽度限制 */
        display: inline-block !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 10px rgba(0,123,255,0.25) !important;
    }

    /* 居中对齐容器样式 */
    .total-label {
        font-size: 1.1rem;
        color: #6C757D;
        white-space: nowrap;
    }
    .total-value {
        font-size: 2rem;
        font-weight: 700;
        color: #212529;
        white-space: nowrap;
    }
    </style>
""", unsafe_allow_html=True)

def analyze_image(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    for model in CANDIDATE_MODELS:
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Extract invoice: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except: continue
    return None

# --- 3. 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 可编辑版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票文件", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    current_data_list = []
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        if file_id in st.session_state.ignored_files: continue
        if file_id in st.session_state.invoice_cache:
            res = st.session_state.invoice_cache[file_id]
        else:
            try:
                f_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    img = convert_from_bytes(f_bytes)[0]
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    f_bytes, m_type = buf.getvalue(), "image/jpeg"
                res = analyze_image(f_bytes, m_type)
                if res: st.session_state.invoice_cache[file_id] = res
            except: res = None
        if res:
            amt = float(str(res.get('Total', 0)).replace('¥','').replace(',',''))
            current_data_list.append({"文件名": file.name, "日期": res.get('Date', ''), "项目": res.get('Item', ''), "金额": amt, "file_id": file_id})

    if current_data_list:
        df = pd.DataFrame(current_data_list)
        edited_df = st.data_editor(df, column_config={"file_id": None, "金额": st.column_config.NumberColumn(format="%.2f")}, num_rows="dynamic", use_container_width=True)
        
        # 处理删除逻辑
        deleted_ids = set(df["file_id"]) - set(edited_df["file_id"])
        if deleted_ids:
            st.session_state.ignored_files.update(deleted_ids)
            st.rerun()

        # --- 🟢 核心修改：文案更新与布局微调 ---
        total = edited_df['金额'].sum()
        
        # 居中对齐容器
        col_side1, col_main, col_side2 = st.columns([3, 4, 3])
        
        with col_main:
            inner_left, inner_right = st.columns([1.6, 1])
            
            with inner_left:
                st.markdown(f"""
                    <div style="display: flex; align-items: baseline; justify-content: flex-end; gap: 10px; height: 100%;">
                        <span class="total-label">💰 总计金额</span>
                        <span class="total-value">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            
            with inner_right:
                df_export = edited_df.drop(columns=["file_id"])
                df_export.loc[len(df_export)] = ['合计', '', '', total]
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False)
                
                # 更新文案：导出 excel，去掉图标
                st.download_button(
                    label="导出 excel", 
                    data=output.getvalue(), 
                    file_name="发票汇总.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
