FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY fundautopsy/ ./fundautopsy/

# Install package with web dependencies
RUN pip install --no-cache-dir ".[web]"

# SEC EDGAR requires a User-Agent header with contact info
ENV EDGAR_IDENTITY="FundAutopsy tombstoneresearch@proton.me"

EXPOSE 8000

CMD ["uvicorn", "fundautopsy.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
