FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --create-home --uid 10001 checker

USER checker
# 8788: webhook receiver (items 8 and 11); 8787: include stub (item 6 pull alternative only)
EXPOSE 8788 8787
ENTRYPOINT ["mervia-check"]
