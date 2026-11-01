import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)
print("連線到：", os.getenv("LLM_API_URL"), "模型：", os.getenv("MODEL_NAME"))

# 測試 1：聊天模型
chat = OpenAI(base_url=os.getenv("LLM_API_URL"), api_key=os.getenv("API_KEY"))
r = chat.chat.completions.create(
    model=os.getenv("MODEL_NAME"),
    messages=[{"role": "user", "content": "用一句話自我介紹"}],
)
print("聊天模型 OK：", r.choices[0].message.content)

# 測試 2：嵌入模型（RAG 會用到）
emb = OpenAI(base_url=os.getenv("EMBEDDING_API_URL"), api_key=os.getenv("EMBEDDING_API_KEY"))
e = emb.embeddings.create(model=os.getenv("EMBEDDING_MODEL_NAME"), input=["圖書館幾點關門？"])
print("嵌入模型 OK：向量長度 =", len(e.data[0].embedding))