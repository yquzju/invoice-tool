import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 基础配置与 Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" # 填入您的 Key
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2-VL-7B-Instruct"

# --- 2. 注入现代 Dashboard CSS ---
def local_css():
    st.markdown("""
    <style>
    /* 1. 强制上传区域上下滚动，取消左右翻页 */
    [data-testid='stFileUploader'] section > div:nth-child(2) {
        max-height: 200px !important;
        overflow-y: auto !important;
        display: block !important;
    }
    
    /* 2. 隐藏 Streamlit 默认的加载/成功提示，保持界面整洁 */
    .stAlert { margin-top: 0px; margin-bottom: 5px; }

    /* 3. 统计卡片样式复刻 */
    .metric-container {
        display: flex; gap: 15px; margin-bottom: 25px;
    }
    .metric-card {
        flex: 1; padding: 20px; border-radius: 12px; color: white;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05);
    }
    .bg-blue { background: linear-gradient(135deg, #3B82F6, #2563EB); }
    .bg-green { background: linear-gradient(135deg, #10B981, #059669); }
    .bg-orange { background: linear-gradient(135deg, #F59E0B, #D97706); }
    .label { font-size: 14px; opacity: 0.9; }
    .value { font-size: 26px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 识别函数 ---
def analyze_invoice(image_bytes, mime_type):
    base64_img = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "提取发票 JSON: 1.Item, 2.Date, 3.Total. JSON only."},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_img}"}}
            ]
        }],
        "temperature": 0.1
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=data, timeout=45)
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content']
            clean = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean[clean.find('{'):clean.rfind('}')+1])
    except: return None
    return None

# --- 4. 页面主体 ---
st.set_page_config(page_title="AI 发票助手 (流式版)", layout="wide")
local_css()

# 初始化全局状态
if 'results' not in st.session_state: st.session_state.results = []
if 'processed_ids' not in st.session_state: st.session_state.processed_ids = set()

st.title("🧾 AI 发票助手 (QwenVL 流式识别版)")

# 🟢 顶部统计占位符
stat_placeholder = st.empty()

uploaded_files = st.file_uploader("上传发票 (多选)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

# 🟢 渲染统计卡片
def update_stats(total_up):
    df_stats = pd.DataFrame(st.session_state.results)
    success_count = len(df_stats)
    total_amt = df_stats['金额'].sum() if not df_stats.empty else 0.0
    
    with stat_placeholder.container():
        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div class="metric-card bg-blue"><div class="label">上传发票数</div><div class="value">{total_up} 张</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card bg-green"><div class="label">识别成功数</div><div class="value">{success_count} 张</div></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="metric-card bg-orange"><div class="label">总金额</div><div class="value">¥ {total_amt:,.2f}</div></div>', unsafe_allow_html=True)

# --- 5. 流式处理核心逻辑 ---
if uploaded_files:
    update_stats(len(uploaded_files))
    
    # 文件识别区域
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.processed_ids: continue
        
        # 🟢 独立文件进度条容器
        status_col = st.empty()
        with status_col.container():
            st.write(f"🔍 正在识别: {file.name}")
            bar = st.progress(0.1) # 初始化该文件的进度条
            
            try:
                # 预处理
                f_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    imgs = convert_from_bytes(f_bytes)
                    buf = io.BytesIO()
                    imgs[0].save(buf, format="JPEG")
                    f_bytes, m_type = buf.getvalue(), "image/jpeg"
                
                bar.progress(0.5) # 预处理完成进度
                
                # 识别
                res = analyze_invoice(f_bytes, m_type)
                if res:
                    amt = float(str(res.get('Total', 0)).replace(',',''))
                    st.session_state.results.append({
                        "文件名": file.name,
                        "项目名称": res.get('Item', ''),
                        "开票日期": res.get('Date', ''),
                        "金额": amt
                    })
                    st.session_state.processed_ids.add(fid)
                    bar.progress(1.0) # 识别完成
                    status_col.empty() # 清除该文件的独立进度提示
                    update_stats(len(uploaded_files)) # 立即刷新顶部统计
                    st.rerun() # 🟢 识别完一个立即重绘页面展示表格
                else:
                    st.error(f"❌ {file.name} 识别失败")
            except Exception as e:
                st.error(f"⚠️ {file.name} 异常: {e}")

# --- 6. 实时表格展示 ---
if st.session_state.results:
    st.markdown("##### 📄 识别明细 (实时更新)")
    df = pd.DataFrame(st.session_state.results)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # 导出功能
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 导出 Excel (CSV格式)", csv, "invoices.csv", "text/csv", type="primary")
else:
    st.info("💡 请上传发票开始识别")
