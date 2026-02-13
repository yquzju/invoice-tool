import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 请填写你的 API Key ---
API_KEY = "AIzaSyARtowfN-m9H80rbXgpXGBR-xZQIzp8LSg"  # <--- 记得把你的 Key 填回来！！！

def analyze_image_robust(image_bytes, mime_type):
    """
    智能尝试多种模型路径，直到成功
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 准备备选方案列表 (优先试正式版 v1，不行试测试版 v1beta)
    candidate_urls = [
        # 方案 1: 正式版 v1 + 标准名 (最稳)
        f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={API_KEY}",
        # 方案 2: 测试版 v1beta + 标准名
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}",
        # 方案 3: 正式版 v1 + Pro (备用)
        f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={API_KEY}",
    ]

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

    last_error = ""
    
    # 循环尝试所有方案
    for url in candidate_urls:
        try:
            # 打印调试信息到后台 (可选)
            print(f"Trying URL: {url.split('?')[0]}...") 
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                # 成功！解析数据
                result_json = response.json()
                text_content = result_json['candidates'][0]['content']['parts'][0]['text']
                clean_text = text_content.replace("```json", "").replace("```", "").strip()
                return json.loads(clean_text)
            else:
                # 记录错误但不立即停止，尝试下一个
                error_info = response.json()
                error_msg = error_info.get('error', {}).get('message', str(response.text))
                last_error = f"Status {response.status_code}: {error_msg}"
                
                # 如果是 Key 无效，直接停止尝试
                if "API key not valid" in last_error:
                    st.error("⛔ API Key 无效！请检查代码第 11 行是否填入了正确的 Key。")
                    return None
                    
        except Exception as e:
            last_error = str(e)
            
    # 如果循环结束还没成功
    st.error(f"❌ 所有尝试都失败了。最后一次报错: {last_error}")
    return None

# --- 页面主逻辑 ---
st.set_page_config(page_title="发票助手 (最终版)", layout="wide")
st.title("🧾 AI 智能发票汇总 (自动寻址版)")
st.info("已启用智能路由：会自动在 v1 正式版和 v1beta 测试版之间寻找可用的通道。")

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

            # 调用智能分析函数
            result = analyze_image_robust(process_bytes, mime_type)
            
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
                
        except Exception as e:
            st.error(f"处理 {file.name} 异常: {e}")
            
        progress_bar.progress((index + 1) / len(uploaded_files))

    if data_list:
        df = pd.DataFrame(data_list)
        total = df['价税合计'].sum()
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        
        df.loc[len(df)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel", output.getvalue(), "发票汇总.xlsx")
