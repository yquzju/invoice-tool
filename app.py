import streamlit as st
import pandas as pd
import google.generativeai as genai
import io
from pdf2image import convert_from_bytes
import zipfile

# --- 1. 配置 AI ---
# 记得把下面这行换成你自己的 key！
GOOGLE_API_KEY = "AIzaSyARtowfN-m9H80rbXgpXGBR-xZQIzp8LSg" 

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-flash')

def analyze_image(image_bytes, mime_type):
    """发送图片给 AI 提取数据"""
    prompt = """
    你是一个财务发票识别助手。请分析这张图片，提取以下三个字段：
    1. 发票项目名称 (Item) - 如果有多个，概括为一个主要项目。
    2. 开票日期 (Date) - 格式统一为 YYYY-MM-DD。
    3. 价税合计 (Total) - 纯数字，不要货币符号。
    
    请严格以 JSON 格式返回，不要包含 ```json 等标记，直接返回大括号内容。
    格式示例: {"Item": "办公用品", "Date": "2023-10-12", "Total": 100.50}
    """
    
    try:
        image_parts = [{"mime_type": mime_type, "data": image_bytes}]
        response = model.generate_content([prompt, image_parts[0]])
        # 清洗数据，防止 AI 话痨
        text = response.text.replace("```json", "").replace("```", "").strip()
        # 尝试修正一些常见的 JSON 格式错误
        import json
        return json.loads(text)
    except Exception as e:
        st.error(f"识别出错，请重试或检查图片清晰度: {e}")
        return None

# --- 2. 页面布局 ---
st.set_page_config(page_title="极速发票助手", layout="wide")
st.title("🧾 AI 智能发票汇总神器")
st.info("支持 JPG/PNG 图片及 PDF 文件。上传后自动生成 Excel。")

# --- 3. 文件上传区 ---
uploaded_files = st.file_uploader("拖入发票文件 (支持批量)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    st.subheader("📊 识别结果")
    
    data_list = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for index, file in enumerate(uploaded_files):
        status_text.text(f"正在处理: {file.name} ...")
        file_bytes = file.read()
        
        # 核心逻辑：如果是PDF，转为图片；如果是图片，直接用
        target_image_bytes = file_bytes
        mime_type = file.type
        
        try:
            if file.type == "application/pdf":
                # PDF 转第一张图
                images = convert_from_bytes(file_bytes)
                if images:
                    img_byte_arr = io.BytesIO()
                    images[0].save(img_byte_arr, format='JPEG')
                    target_image_bytes = img_byte_arr.getvalue()
                    mime_type = "image/jpeg"
                else:
                    st.warning(f"无法读取 PDF 内容: {file.name}")
                    continue
            
            # 调用 AI
            result = analyze_image(target_image_bytes, mime_type)
            
            if result:
                # 确保金额是数字
                try:
                    amount = float(str(result.get('Total', 0)).replace(',',''))
                except:
                    amount = 0.0
                    
                data_list.append({
                    "文件名": file.name,
                    "开票日期": result.get('Date', ''),
                    "发票项目": result.get('Item', ''),
                    "价税合计": amount
                })
        except Exception as e:
            st.error(f"处理 {file.name} 时发生系统错误: {e}")

        progress_bar.progress((index + 1) / len(uploaded_files))
    
    status_text.text("✅ 所有文件处理完毕！")
    
    # --- 4. 生成 Excel ---
    if data_list:
        df = pd.DataFrame(data_list)
        
        # 计算总计
        total_sum = df['价税合计'].sum()
        
        # 显示表格
        st.dataframe(df, use_container_width=True)
        st.metric("💰 发票总金额", f"¥ {total_sum:,.2f}")
        
        # 增加一行总计到导出文件
        df.loc[len(df)] = ['合计', '', '', total_sum]
        
        # 导出按钮
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='发票汇总')
            
        st.download_button(
            label="📥 点击下载整理好的 Excel",
            data=output.getvalue(),
            file_name="发票汇总表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
