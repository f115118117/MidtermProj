from dotenv import load_dotenv
load_dotenv(override=True)

from rag import RuleSearcher

searcher = RuleSearcher()
print("共切成", len(searcher.chunks), "段\n")

for q in ["書逾期可以減免罰款嗎？", "可以帶咖啡進圖書館嗎？", "討論室最多可以預約幾天後？"]:
    print("問題：", q)
    for hit in searcher.search(q):
        print(f"   {hit['score']}  {hit['source']} > {hit['section']}")
    print()