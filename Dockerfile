FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 opswatch
USER opswatch

ENTRYPOINT ["opswatch"]
CMD ["run", "-c", "/config/opswatch.toml"]
