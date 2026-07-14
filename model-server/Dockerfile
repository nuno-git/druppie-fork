FROM voipmonitor/vllm:eldritch-enlightenment-v8722ac7-b12x15cd38c-cu132-20260629

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx pydantic

COPY main.py /app/main.py
COPY requirements.txt /app/requirements.txt

WORKDIR /app

EXPOSE 8001

CMD ["python3", "/app/main.py"]
