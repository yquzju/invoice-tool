import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 基础配置与 Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct"]

# --- 2. 精简 CSS：只管颜色，不管位置 ---
st.markdown("""
    <style>
    /* 只定义按钮的高级蓝色和圆角 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 2rem !important;
        border-radius: 8px !important;
        width: auto !important; /* 确保宽度自适应，不会变竖 */
        min-width: 150px !important;
    }
    /* 总金额文字样式 */
    .total-text-box {
        display: flex;
        align-items: baseline;
        justify-content: center; /* 居中显示 */
        gap: 15px;
        margin-top: 20px;
    }
    .total-label { font-size: 1.2rem; color: #666; }
    .total-value { font-size: 2.2rem; font-weight: bold; color: #333; }
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
st.title("🧾 AI 发票助手 (QwenVL 版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    current_data_list = []
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        if fid in st.session_state.invoice_cache:
            res = st.session_state.invoice_cache[fid]
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
                if res: st.session_state.invoice_cache[fid] = res
            except: res = None
        if res:
            amt = float(str(res.get('Total', 0)).replace('¥','').replace(',',''))
            current_data_list.append({"文件名": file.name, "日期": res.get('Date', ''), "项目": res.get('Item', ''), "金额": amt, "file_id": fid})

    if current_data_list:
        df = pd.DataFrame(current_data_list)
        edited_df = st.data_editor(df, column_config={"file_id": None, "金额": st.column_config.NumberColumn(format="%.2f")}, num_rows="dynamic", use_container_width=True)
        
        # 实时计算总额
        total_amt = edited_df['金额'].sum()

        # --- 🟢 重新排版布局 ---
        # 第一步：居中显示总金额
        st.markdown(f"""
            <div class="total-text-box">
                <span class="total-label">💰 总金额合计</span>
                <span class="total-value">¥ {total_amt:,.2f}</span>
            </div>
        """, unsafe_allow_html=True)

        # 第二步：使用列布局，把下载按钮放到最右侧
        col_left, col_right = st.columns([8, 2]) # 8:2 比例，把按钮挤到右边
        with col_right:
            output = io.BytesIO()
            df_export = edited_df.drop(columns=["file_id"])
            df_export.loc[len(df_export)] = ['合计', '', '', total_amt]
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False)
            
            st.download_button(
                label="📥 下载 excel", 
                data=output.getvalue(), 
                file_name="发票汇总.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
