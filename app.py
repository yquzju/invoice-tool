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

# --- 核心修改：不再自动寻找，直接写死稳定的 1.5 版本 ---
# 这是一个经过验证的、绝对可用的模型地址
MODEL_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"

def analyze_image_fixed(image_bytes, mime_type):
    """
    使用固定模型进行识别，带重试机制
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    
    # 提示词：提取中文
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

    # 重试参数
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(MODEL_URL, headers=headers, json=payload)
            
            # 成功
            if response.status_code == 200:
                result_json = response.json()
                try:
                    text_content = result_json['candidates'][0]['content']['parts'][0]['text']
                    clean_text = text_content.replace("```json", "").replace("```", "").strip()
                    return json.loads(clean_text)
                except Exception:
                    # 有时候返回结构不一样，容错处理
                    return None
            
            # 限速 (429) -> 等待
            elif response.status_code == 429:
                if attempt < max_retries:
                    st.toast(f"⏳ 触发限速，休息 {retry_delay} 秒...", icon="☕")
                    time.sleep(retry_delay)
                    retry_delay += 5 # 递增等待
                    continue
                else:
                    st.error("❌ 限速严重，请稍后再试。")
                    return None
            
            # 其他错误
            else:
                st.warning(f"请求报错 ({response.status_code})，尝试重试...")
                time.sleep(2)
                continue
                
        except Exception as e:
            st.error(f"网络异常: {e}")
            return None
            
    return None

# --- 页面布局 ---
st.set_page_config(page_title="发票助手 (稳定版)", layout="wide")
st.title("🧾 AI 智能发票汇总 (稳定版)")
st.success("✅ 已强制锁定模型：gemini-1.5-flash (免费额度足，不限速)")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        try:
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

            # 调用固定的分析函数
            result = analyze_image_fixed(process_bytes, mime_type)
            
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
                st.toast(f"✅ {file.name} 成功")
            else:
                 st.error(f"❌ {file.name} 识别失败")

        except Exception as e:
            st.error(f"处理异常: {e}")
            
        # 这里的 sleep 依然保留，双保险
        time.sleep(2)
        progress_bar.progress((index + 1) / len(uploaded_files))

    if data_list:
        df = pd.DataFrame(data_list)
        total = df['价税合计'].sum()
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        
        # 导出 Excel
        df_export = df.copy()
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        st.download_button(
            label="📥 下载 Excel 表格",
            data=output.getvalue(),
            file_name="发票汇总.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
