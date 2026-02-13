import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- ⚠️ 请填入你的 API Key ---
API_KEY = "AIzaSyARtowfN-m9H80rbXgpXGBR-xZQIzp8LSg"

def get_best_model():
    """
    诊断模式：列出所有可用模型，并自动选择一个
    """
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
        response = requests.get(url)
        
        if response.status_code != 200:
            st.error(f"连接 Google 失败 (Status {response.status_code})，请检查网络或 API Key。")
            return None, []

        data = response.json()
        models = data.get('models', [])
        
        # 筛选支持生成的模型
        candidates = []
        for m in models:
            if 'generateContent' in m.get('supportedGenerationMethods', []):
                # 只保留名字
                name = m['name'].replace('models/', '')
                candidates.append(name)
        
        if not candidates:
            return None, []
            
        # 智能选择策略：优先找 flash
        selected = candidates[0]
        for name in candidates:
            if 'flash' in name:
                selected = name
                break
                
        return selected, candidates

    except Exception as e:
        st.error(f"获取模型列表失败: {e}")
        return None, []

def analyze_with_retry(image_bytes, mime_type, model_name):
    """
    针对 2.5 模型的慢速重试逻辑
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={API_KEY}"
    headers = {'Content-Type': 'application/json'}
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "Extract 3 fields into JSON:\n1. Item (Main product name, keep Chinese)\n2. Date (YYYY-MM-DD)\n3. Total (Number only)\n\nFormat: {\"Item\": \"...\", \"Date\": \"...\", \"Total\": 0.0}"},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64_image
                    }
                }
            ]
        }]
    }
    
    # 针对新模型的激进重试策略
    for attempt in range(1, 4):
        try:
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                # 成功！
                try:
                    res_json = response.json()
                    text = res_json['candidates'][0]['content']['parts'][0]['text']
                    clean_text = text.replace("```json", "").replace("```", "").strip()
                    return json.loads(clean_text)
                except:
                    return None
            
            elif response.status_code == 429:
                # 遇到限速，根据次数指数级等待
                wait_time = 15 * attempt  # 第一次等15秒，第二次等30秒...
                st.toast(f"⏳ 触发限速 (429)，正在冷却 {wait_time} 秒...", icon="🧊")
                time.sleep(wait_time)
                continue
            
            else:
                st.warning(f"请求报错 {response.status_code}，重试中...")
                time.sleep(5)
                continue
                
        except Exception as e:
            st.error(f"网络错误: {e}")
            time.sleep(5)
            
    return None

# --- 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手 (诊断版)", layout="wide")
st.title("🧾 AI 发票助手 (自动降速版)")

# 1. 启动时自动获取模型
if 'target_model' not in st.session_state:
    with st.spinner("正在连接 Google 服务器检测可用模型..."):
        best_model, all_models = get_best_model()
        if best_model:
            st.session_state['target_model'] = best_model
            st.session_state['all_models'] = all_models
        else:
            st.error("❌ 未找到任何可用模型，请检查 Key 是否有效。")
            st.stop()

# 显示当前状态
st.info(f"🚀 已自动锁定可用模型: **{st.session_state['target_model']}**")
with st.expander("查看所有可用模型列表 (调试用)"):
    st.write(st.session_state.get('all_models', []))

# 2. 文件上传
uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    st.warning("⚠️ 注意：检测到使用的是最新版模型，为防止封号，每张图片处理间隔较长 (10秒+)，请耐心等待。")
    
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        # 🟢 核心降速逻辑：每处理一张前，强制休息 10 秒
        if index > 0:
            with st.spinner(f"⏳ 正在冷却，防止限速 (10秒)..."):
                time.sleep(10)
        
        try:
            # 预处理
            file_bytes = file.read()
            process_bytes = file_bytes
            mime_type = file.type
            
            if file.type == "application/pdf":
                images = convert_from_bytes(file_bytes)
                if images:
                    img_buffer = io.BytesIO()
                    images[0].save(img_buffer, format="JPEG")
                    process_bytes = img_buffer.getvalue()
                    mime_type = "image/jpeg"
            if mime_type == 'image/jpg': mime_type = 'image/jpeg'

            # 识别
            st.toast(f"正在处理: {file.name}")
            result = analyze_with_retry(process_bytes, mime_type, st.session_state['target_model'])
            
            if result:
                try:
                    amt = float(str(result.get('Total', 0)).replace('¥','').replace(',',''))
                except:
                    amt = 0.0
                
                data_list.append({
                    "文件名": file.name,
                    "开票日期": result.get('Date', ''),
                    "发票项目": result.get('Item', ''),
                    "价税合计": amt
                })
                st.success(f"✅ {file.name} 处理完成")
            else:
                 st.error(f"❌ {file.name} 失败")

        except Exception as e:
            st.error(f"异常: {e}")
            
        progress_bar.progress((index + 1) / len(uploaded_files))

    # 3. 结果导出
    if data_list:
        df = pd.DataFrame(data_list)
        total = df['价税合计'].sum()
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        
        df_export = df.copy()
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel 表格", output.getvalue(), "发票汇总.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
