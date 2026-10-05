FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY dealintel ./dealintel
RUN pip install --no-cache-dir .
ENV DEALINTEL_HOST=0.0.0.0 DEALINTEL_PORT=8765 DEALINTEL_HOME=/data
VOLUME ["/data"]
EXPOSE 8765
CMD ["dealintel", "run"]
