FROM python:3.12-slim
COPY app.py /app/app.py
COPY files/ /srv/files/
RUN mkdir -p /var/private
ENV FLAG=fill-at-launch
EXPOSE 8080 8081
CMD ["python","/app/app.py"]
