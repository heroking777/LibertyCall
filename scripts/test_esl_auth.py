#!/usr/bin/env python3
"""
Event Socket Protocol 認証テストスクリプト
FreeSWITCH Event Socketへの接続と認証をテストする
"""
import socket
import sys

def test_esl_auth():
    host = "127.0.0.1"
    port = 8021
    password = "ClueCon"
    test_uuid = "test-uuid-12345"
    
    try:
        print(f"[DEBUG] Event Socket接続試行: {host}:{port}")
        s = socket.create_connection((host, port), timeout=5)
        
        # バナーを受信
        banner = s.recv(1024).decode('utf-8', errors='ignore')
        print(f"[DEBUG] banner: {banner.strip()}")
        
        if "auth/request" in banner:
            # 認証送信（\r\n\r\nを使用）
            auth_cmd = f"auth {password}\r\n\r\n"
            print(f"[DEBUG] 認証コマンド送信: auth {password}")
            s.sendall(auth_cmd.encode('utf-8'))
            
            # 認証応答を受信
            reply = s.recv(1024).decode('utf-8', errors='ignore')
            print(f"[DEBUG] auth reply: {reply.strip()}")
            
            if "OK" not in reply and "accepted" not in reply.lower():
                print("[ERROR] 認証失敗")
                s.close()
                return None
            
            print("[DEBUG] 認証成功")
            
            # uuid_getvarコマンドを送信
            cmd = f"api uuid_getvar {test_uuid} local_media_port\r\n\r\n"
            print(f"[DEBUG] コマンド送信: api uuid_getvar {test_uuid} local_media_port")
            s.sendall(cmd.encode('utf-8'))
            
            # 応答を受信
            response = b""
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break
                response += chunk
                # Content-Lengthを確認
                if b"Content-Length:" in response:
                    # 簡易的に応答が揃ったと判断
                    break
            
            response_text = response.decode('utf-8', errors='ignore')
            print(f"[DEBUG] response: {response_text[:300]}")
            
            # ボディ部分を抽出
            body_start = response_text.find("\n\n")
            if body_start != -1:
                body = response_text[body_start + 2:].strip()
                print(f"[DEBUG] ボディ: {body}")
                if "-ERR" in body:
                    print("[INFO] -ERRは正常（テストUUIDなので）")
                elif body.isdigit():
                    print(f"[SUCCESS] ポート番号取得成功: {body}")
                else:
                    print(f"[INFO] 応答: {body}")
            
            s.close()
            print("[SUCCESS] Event Socket Protocol接続・認証・コマンド実行 すべて成功")
            return True
        else:
            print("[ERROR] 認証リクエストが見つかりません")
            s.close()
            return None
            
    except socket.timeout:
        print("[ERROR] 接続タイムアウト")
        return None
    except socket.error as e:
        print(f"[ERROR] ソケットエラー: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    result = test_esl_auth()
    sys.exit(0 if result else 1)

