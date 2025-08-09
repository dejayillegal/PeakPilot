from app import create_app
from settings import DEBUG

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(__import__('os').environ.get('PORT', '5000')), debug=DEBUG)
