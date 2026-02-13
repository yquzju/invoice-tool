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

# --- 注入自定义 CSS 以实现高级感 UI ---
st.markdown("""
    <style>
    /* 定制下载按钮样式：高级蓝色，限制最大宽度 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.6rem 2.5rem !important; /* 增加内边距让按钮更饱满 */
        border-radius: 8px !important;
        transition: all 0.3s ease;
        min-width: 180px !important;    /* 设置最小宽度 */
        max-width: 240px !important;    /* 🟢 限制最大宽度，不再无限拉长 */
        font-weight: 500 !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 15px rgba(0,123,255,0.3) !important;
        transform: translateY(-1px);
    }
    /* 调整右侧列对齐 */
    [data-testid="column"]:last-child {
        display: flex;
        flex-direction: column;
        align-items: flex-end; /* 🟢 强制右侧列内容靠右对齐 */
    }
    [data-testid="stMetric"] {
        text-align: right;
    }
    </style>
""", unsafe_allow_html=True)

def analyze_image_auto_switch(image_bytes, mime_type):
    """自动轮询模型识别"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在尝试: {model_name} ...")
        
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Extract invoice: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "temperature": 0.1
        }
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if response.status_code == 200:
                status_placeholder.empty()
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except:
            status_placeholder.empty()
            continue
    return None

# --- 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 可编辑版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    current_data_list = []
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        if file_id in st.session_state.ignored_files: continue

        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
        else:
            try:
                file_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    from pdf2image import convert_from_bytes
                    img = convert_from_bytes(file_bytes)[0]
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    file_bytes, m_type = buf.getvalue(), "image/jpeg"
                
                result = analyze_image_auto_switch(file_bytes, m_type)
                if result: st.session_state.invoice_cache[file_id] = result
            except: result = None

        if result:
            amt = float(str(result.get('Total', 0)).replace('¥','').replace(',',''))
            current_data_list.append({
                "文件名": file.name, "日期": result.get('Date', ''),
                "项目": result.get('Item', ''), "金额": amt, "file_id": file_id
            })

    if current_data_list:
        df = pd.DataFrame(current_data_list)
        edited_df = st.data_editor(
            df,
            column_config={"file_id": None, "金额": st.column_config.NumberColumn(format="%.2f")},
            num_rows="dynamic", use_container_width=True, key="invoice_editor"
        )
        
        # 同步删除与编辑
        deleted_ids = set(df["file_id"]) - set(edited_df["file_id"])
        if deleted_ids:
            st.session_state.ignored_files.update(deleted_ids)
            st.rerun()

        # --- 🟢 优化后的布局：右下角自适应 ---
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 调整比例为 8:2，让右侧列更窄，按钮就不会被强制拉得很长
        col_left, col_right = st.columns([8, 2])
        
        with col_right:
            total = edited_df['金额'].sum()
            st.metric("总金额合计", f"¥ {total:,.2f}")
            
            # 下载逻辑
            df_export = edited_df.drop(columns=["file_id"])
            df_export.loc[len(df_export)] = ['合计', '', '', total]
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False)
            
            st.download_button(
                label="📥 下载 excel", 
                data=output.getvalue(), 
                file_name="发票汇总.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
