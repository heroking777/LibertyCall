"""
資料請求フォーム用APIエンドポイント
Flaskを使用してフォーム送信を処理し、自動返信メールを送信
"""

import os
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_sender.sendgrid_client import send_email, send_email_with_attachment

app = Flask(__name__)
CORS(app)  # CORSを有効化（必要に応じて設定を調整）


def get_pdf_path():
    """PDFファイルのパスを取得"""
    # PDFファイルのパスを環境変数から取得、またはデフォルトパスを使用
    pdf_path = os.getenv("MATERIAL_PDF_PATH", None)
    if pdf_path and os.path.exists(pdf_path):
        return pdf_path
    
    # デフォルトのパスを試す（優先順位順）
    default_paths = [
        os.path.join(os.path.dirname(__file__), "サービス概要.pdf"),  # 実際のファイル名
        os.path.join(os.path.dirname(__file__), "LibertyCall_資料.pdf"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "lp", "サービス概要.pdf"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "lp", "LibertyCall_資料.pdf"),
    ]
    
    for path in default_paths:
        if os.path.exists(path):
            return path
    
    return None


@app.route("/api/contact", methods=["POST"])
def handle_contact_form():
    """資料請求フォームの送信を処理"""
    try:
        data = request.get_json()
        
        # 必須項目のチェック
        required_fields = ["company", "name", "email", "type"]
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            return jsonify({
                "success": False,
                "error": f"以下の項目が未入力です: {', '.join(missing_fields)}"
            }), 400
        
        company = data.get("company", "")
        name = data.get("name", "")
        email = data.get("email", "")
        tel = data.get("tel", "")
        inquiry_type = data.get("type", "")
        message = data.get("message", "")
        
        # メールアドレスの検証
        if "@" not in email:
            return jsonify({
                "success": False,
                "error": "無効なメールアドレスが入力されました。"
            }), 400
        
        # 配信停止リストをチェック
        if is_unsubscribed(email):
            return jsonify({
                "success": False,
                "error": "このメールアドレスは配信停止済みです。"
            }), 400
        
        # 管理者宛メールを送信（通知用）
        admin_email = os.getenv("ADMIN_EMAIL", "sales@libcall.com")
        
        admin_subject = f"新しいフォーム送信: {inquiry_type}"
        admin_body = f"""新しいフォーム送信がありました。

会社名: {company}
担当者名: {name}
メールアドレス: {email}
電話番号: {tel}
お問い合わせ種別: {inquiry_type}
ご相談内容:
{message if message else '(未記入)'}
"""
        
        # 管理者宛メール送信（失敗しても続行）
        try:
            send_email(admin_email, admin_subject, admin_body)
        except Exception as e:
            print(f"管理者宛メール送信エラー: {e}")
        
        # 自動返信メールを送信
        if inquiry_type == "資料請求":
            # 資料請求の場合
            template_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "email_sender",
                "templates",
                "material_request_reply.txt"
            )
            
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    template_content = f.read()
                
                # テンプレート内の変数を置換
                body_text = template_content.replace("{name}", name)
                body_text = body_text.replace("{email}", email)
                
                subject = "資料請求ありがとうございます - LibertyCallの詳細資料をお送りします"
                
                # PDFファイルのパスを取得
                pdf_path = get_pdf_path()
                attachments = None
                if pdf_path:
                    # 添付ファイル名は「LibertyCall_資料.pdf」に統一
                    attachments = [{"filename": "LibertyCall_資料.pdf", "path": pdf_path}]
                    success = send_email_with_attachment(
                        recipient_email=email,
                        subject=subject,
                        body_text=body_text,
                        attachments=attachments,
                    )
                else:
                    # PDFがない場合は通常のメール送信
                    print("警告: PDFファイルが見つかりません。添付なしで送信します。")
                    success = send_email(
                        recipient_email=email,
                        subject=subject,
                        body_text=body_text,
                    )
                
                if not success:
                    return jsonify({
                        "success": False,
                        "error": "自動返信メールの送信に失敗しました。"
                    }), 500
        
        elif inquiry_type == "導入相談":
            # 導入相談の場合
            template_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "email_sender",
                "templates",
                "consultation_reply.txt"
            )
            
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    template_content = f.read()
                
                # テンプレート内の変数を置換
                body_text = template_content.replace("{name}", name)
                body_text = body_text.replace("{email}", email)
                
                subject = "導入相談ありがとうございます - 次のステップをご案内します"
                
                # 導入相談はPDF添付なしで送信
                success = send_email(
                    recipient_email=email,
                    subject=subject,
                    body_text=body_text,
                )
                
                if not success:
                    return jsonify({
                        "success": False,
                        "error": "自動返信メールの送信に失敗しました。"
                    }), 500
        
        return jsonify({
            "success": True,
            "message": "お問い合わせありがとうございます。送信が完了しました。"
        })
    
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"サーバーエラーが発生しました: {str(e)}"
        }), 500


@app.route("/api/unsubscribe", methods=["POST"])
def handle_unsubscribe():
    """配信停止処理"""
    try:
        data = request.get_json()
        email = data.get("email", "").strip()
        
        if not email:
            return jsonify({
                "success": False,
                "error": "メールアドレスが入力されていません。"
            }), 400
        
        # メールアドレスの検証
        if "@" not in email:
            return jsonify({
                "success": False,
                "error": "無効なメールアドレスが入力されました。"
            }), 400
        
        # 配信停止リストに追加（CSVファイルまたはデータベース）
        # ここでは簡単な実装として、CSVファイルに記録
        unsubscribe_list_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "unsubscribe_list.csv"
        )
        
        import csv
        from datetime import datetime
        
        # 既存のリストを読み込む
        existing_emails = set()
        if os.path.exists(unsubscribe_list_path):
            with open(unsubscribe_list_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # ヘッダーをスキップ
                for row in reader:
                    if row:
                        existing_emails.add(row[0].lower())
        
        # 新しいメールアドレスを追加
        email_lower = email.lower()
        if email_lower not in existing_emails:
            with open(unsubscribe_list_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                # ファイルが空の場合はヘッダーを書き込む
                if os.path.getsize(unsubscribe_list_path) == 0:
                    writer.writerow(["email", "unsubscribed_at"])
                writer.writerow([email_lower, datetime.now().isoformat()])
        
        return jsonify({
            "success": True,
            "message": "配信停止が完了しました。今後、メール配信は行いません。"
        })
    
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"サーバーエラーが発生しました: {str(e)}"
        }), 500


def is_unsubscribed(email: str) -> bool:
    """メールアドレスが配信停止リストに含まれているか確認"""
    unsubscribe_list_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "unsubscribe_list.csv"
    )
    
    if not os.path.exists(unsubscribe_list_path):
        return False
    
    import csv
    email_lower = email.lower()
    
    try:
        with open(unsubscribe_list_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # ヘッダーをスキップ
            for row in reader:
                if row and row[0].lower() == email_lower:
                    return True
    except Exception:
        pass
    
    return False


if __name__ == "__main__":
    # 開発用サーバー
    app.run(debug=True, host="0.0.0.0", port=5001)

