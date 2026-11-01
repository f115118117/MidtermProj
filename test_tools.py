from tools import search_books, get_my_account, renew_book

print("1. 查書：")
print(search_books("深度學習"))

print("\n2. 密碼錯誤：")
print(get_my_account("LC1001", "0000"))

print("\n3. 查 LC1002 的帳號（應該有逾期罰款 30 元）：")
print(get_my_account("LC1002", "5678"))

print("\n4. 續借已逾期的書（應該被拒絕）：")
print(renew_book("LC1002", "5678", "L004"))

print("\n5. 續借 L001，還沒確認（應該要求確認）：")
print(renew_book("LC1001", "1234", "L001"))