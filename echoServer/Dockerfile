FROM python:3.6-alpine
WORKDIR /app
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY echoServer.py service.py
CMD ["python", "service.py"]
