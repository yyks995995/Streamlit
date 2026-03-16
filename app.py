import streamlit as st
import requests
import re
from openai import OpenAI

st.set_page_config(page_title="Twitch VOD 弹幕 AI 舆情分析", page_icon="🎮", layout="wide")

st.title("🎮 Twitch 录播(VOD) 弹幕舆情分析台")

# ================= 核心抓取逻辑 (Twitch GraphQL) =================
def get_vod_id(url):
    match = re.search(r'videos/(\d+)', url)
    return match.group(1) if match else None

def fetch_twitch_chat_gql(vod_id, max_msgs):
    """
    使用 Twitch GraphQL API 抓取弹幕
    由于 V5 接口已失效返回 404，我们通过构造 GQL 请求来获取弹幕数据
    """
    url = "https://gql.twitch.tv/gql"
    headers = {
        "Client-Id": "kimne78kx3ncx6brgo4mv6wki5h1ko",
        "Content-Type": "text/plain;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    messages = []
    cursor = None
    
    max_loops = (int(max_msgs) // 50) + 10
    
    for _ in range(max_loops):
        if not cursor:
            variables = {"videoID": vod_id, "contentOffsetSeconds": 0.0}
        else:
            variables = {"videoID": vod_id, "cursor": cursor}
            
        payload = [
            {
                "operationName": "VideoCommentsByOffsetOrCursor",
                "variables": variables,
                "extensions": {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
                    }
                }
            }
        ]
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            raise Exception(f"网络请求失败: {e}")
            
        if response.status_code != 200:
            raise Exception(f"Twitch API 拒绝连接: HTTP {response.status_code}。请确认视频是否存在。")
            
        try:
            data = response.json()[0]
        except:
            break
            
        video_data = data.get("data", {}).get("video")
        if not video_data:
            raise Exception(f"未能获取到视频数据。请确认视频是否属于订阅者专享(Sub-only)或已被删除。")
            
        comments_data = video_data.get("comments")
        if not comments_data:
            break
            
        edges = comments_data.get("edges", [])
        if not edges:
            break
            
        for edge in edges:
            node = edge.get("node", {})
            
            # 解析时间
            offset = node.get("contentOffsetSeconds", 0)
            m, s = divmod(int(offset), 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            
            # 解析作者
            commenter = node.get("commenter")
            author = commenter.get("displayName", "Unknown") if commenter else "Unknown"
            
            # 解析消息体
            fragments = node.get("message", {}).get("fragments", [])
            body = "".join(f.get("text", "") for f in fragments)
            
            if len(body.strip()) > 1:
                messages.append(f"[{time_str}] {author}: {body}")
                
            if len(messages) >= max_msgs:
                return messages
                
        # 获取下一页游标
        has_next = comments_data.get("pageInfo", {}).get("hasNextPage")
        if not has_next:
            break
            
        cursor = edges[-1].get("cursor")
        if not cursor:
            break
            
    return messages

# ================= 界面与交互 =================
with st.sidebar:
    st.header("⚙️ 全局设置")
    default_key = st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets else ""
    openai_api_key = st.text_input("填入你的 OpenAI API Key", value=default_key, type="password")
    model_choice = st.selectbox("选择大模型版本", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])

vod_url = st.text_input("📺 输入 Twitch VOD 链接 (例如: https://www.twitch.tv/videos/2723303877)")
max_messages = st.number_input("📥 抓取上限", min_value=100, max_value=50000, value=8000, step=1000)

if st.button("🚀 开始抓取并生成报告"):
    vod_id = get_vod_id(vod_url)
    if not vod_id:
        st.error("无法识别 VOD ID，请确认链接格式。")
        st.stop()

    # ================= 阶段 1：扒取弹幕 =================
    st.subheader("1️⃣ 正在抓取 Twitch 弹幕...")
    
    with st.spinner("正在使用底层接口提取弹幕..."):
        try:
            chat_messages = fetch_twitch_chat_gql(vod_id, max_messages)
            if len(chat_messages) > 0:
                st.success(f"✅ 成功抓取了 {len(chat_messages)} 条弹幕数据！")
        except Exception as e:
            st.error(f"抓取发生异常: {str(e)}")
            st.stop()

    if len(chat_messages) == 0:
        st.warning(f"视频 {vod_id} 提取到的弹幕数为 0。\n可能的原因：\n1. 这是无弹幕的视频\n2. 该主播设置了【仅订阅者(Sub-only)可见VOD】\n3. 视频太老，弹幕记录已被 Twitch 清理。")
        st.stop()

    raw_chat_text = "\n".join(chat_messages)
    st.download_button(
        label="📥 下载原始弹幕 (TXT文本)",
        data=raw_chat_text,
        file_name=f"twitch_vod_{vod_id}_chat.txt",
        mime="text/plain"
    )

    # ================= 阶段 2：AI 分析 =================
    st.subheader("2️⃣ ChatGPT 分析中...")
    
    system_prompt = """你是一个专业的游戏行业 KOL 舆情分析专家。
你的任务是根据用户提供的 Twitch 录播弹幕（Chat Logs），严格按照提供的专业模板输出舆情分析报告。请保持客观、专业。

【必须严格遵循的 Markdown 输出格式】：

# [替换为主播名字] 弹幕分析

## 一、核心结论
总结该场直播最重要的3个结论。
* **结论1：** [核心发现，如：XXX成为直播互动核心节点]
  * [具体表现与数据支撑]
  * **启示：** [对产品发行的启示]
* **结论2：** [关于主播行为或内容节奏的发现]
  * [具体表现与典型弹幕]
  * **启示：** [启示]
* **结论3：** [关于 Gameplay 体验或产品讨论的发现]
  * [具体表现与典型弹幕]
  * **启示：** [启示]

## 二、核心观点分布
提取弹幕中最核心的 4-5 个观点进行拆解。

* **观点一「[核心主题词]」**（占比约 XX%）
  * **出现时间/场景：** [如：战斗阶段/开箱阶段]
  * **二级表达结构：**
    1. [类型1，如煽动型]：[列举2-3条典型原声弹幕]
    2. [类型2，如吐槽型]：[列举2-3条典型原声弹幕]
  * **观察：** [深度分析该观点的互动特征]

**弹幕结构总结：**
[一句话总结，例如：整体呈现 娱乐事件驱动 >> Gameplay讨论 的特征]

## 三、主播类型四象限模型归类
基于弹幕表现，将主播定位在【玩法驱动 vs 情绪驱动】与【娱乐体验 vs 产品理解】的十字模型中。
* **所属象限：** [例如：娱乐体验 × 情绪驱动]
* **特征观察：** [解释其在此象限的依据]
* **典型弹幕：** [列举该象限的标志性弹幕]
"""
    
    client = OpenAI(api_key=openai_api_key)
    user_prompt = f"以下是该 VOD 的弹幕记录采样：\n\n{raw_chat_text[:80000]}"

    try:
        with st.spinner("AI 拆解中，预计需要 1 分钟..."):
            response = client.chat.completions.create(
                model=model_choice,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                max_tokens=3000
            )
            
        analysis_result = response.choices[0].message.content
        st.success("✅ 舆情报告生成完毕！")
        st.markdown(analysis_result)
        
    except Exception as e:
        st.error(f"AI 分析阶段报错: {str(e)}")
