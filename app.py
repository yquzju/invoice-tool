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

def analyze_image_robust(image_bytes, mime_type):
    """
    火力覆盖模式：轮询多个可能的模型地址，直到成功
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
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

    # === 🛑 备选模型名单 (按优先级排序) ===
    # 我们把所有可能的别名都列出来，总有一个能通！
    candidate_urls = [
        # 1. 官方推荐的最新稳定版别名
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}",
        # 2. 指定版本号 001 (非常稳)
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-001:generateContent?key={API_KEY}",
        # 3. 指定版本号 002 (更新更强)
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-002:generateContent?key={API_KEY}",
        # 4. 指定版本号 8b (轻量版，极快)
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-8b:generateContent?key={API_KEY}",
        # 5. 最后大招：如果 Flash 都不行，用 Pro (虽然慢点但能用)
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={API_KEY}",
    ]

    last_error = ""

    # 循环尝试
    for i, url in enumerate(candidate_urls):
        try:
            # st.toast(f"正在尝试第 {i+1} 条通道...", icon="🔌") # 调试用，嫌烦可以注释掉
            response = requests.post(url, headers=headers, json=payload)
            
            # === 成功 ===
            if response.status_code == 200:
                result_json = response.json()
                try:
                    text_content = result_json['candidates'][0]['content']['parts'][0]['text']
                    clean_text = text_content.replace("```json", "").replace("```", "").strip()
                    return json.loads(clean_text)
                except Exception:
                    continue # 解析失败，试下一个
            
            # === 失败处理 ===
            elif response.status_code == 429:
                st.toast("通道拥堵 (429)，自动切换备用线路...", icon="⚠️")
                time.sleep(1) # 小歇一下换下一个
                continue
            
            else:
                # 记录错误 (404等)
                last_error = f"HTTP {response.status_code}"
                continue # 换下一个
                
        except Exception as e:
            last_error = str(e)
            continue

    # 如果循环跑完了都没成功
    st.error(f"❌ 所有通道均响应失败。最后报错: {last_error}")
    return None

# --- 页面布局 ---
st.set_page_config(page_title="发票助手 (终极版)", layout="wide")
st.title("🧾 AI 智能发票汇总 (多通道自动切换版)")
st.success("✅ 已启用多线路冗余：自动在 Flash-001/002/Pro 之间切换，确保连接成功率。")

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

            # 调用多通道函数
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
            else:
                 st.error(f"❌ {file.name} 识别失败")

        except Exception as e:
            st.error(f"系统异常: {e}")
            
        # 基础防抖等待
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
