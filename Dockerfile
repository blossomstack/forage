# Deliberately no browser. Adding Chromium would take this image from ~230 MB to
# ~4 GB to serve the minority of pages that need JavaScript to render; the
# cheaper answer is a separate renderer called only on fallback.
FROM python:3.13-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src

# Dependencies first so a source-only change does not re-resolve them.
COPY pyproject.toml README.md ./
COPY forage ./forage
RUN pip install --prefix=/install .

FROM python:3.13-slim

# Runs unprivileged: this process fetches attacker-influenced URLs for a living.
RUN useradd --system --create-home --uid 10001 forage
COPY --from=build /install /usr/local
USER forage

ENV FORAGE_HOST=0.0.0.0 FORAGE_PORT=8080
EXPOSE 8080

# Extracts a real document rather than pinging a liveness route — a broken
# trafilatura install is the failure this service actually has, and a plain
# process check stays green through it.
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if b'true' in urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=8).read().lower() else 1)"

ENTRYPOINT ["forage"]
