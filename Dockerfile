FROM python:3.11-slim

WORKDIR /app

# 모든 파이썬 의존성은 manylinux wheel 로 설치되므로 컴파일러가 필요 없다.
# curl 은 헬스체크, fonts-nanum 은 matplotlib 한글 라벨용.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY frontend/ ./frontend/
COPY data/ ./data/

RUN mkdir -p /app/data/uploads

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
